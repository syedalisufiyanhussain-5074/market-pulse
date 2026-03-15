import pandas as pd
import numpy as np

from fastapi import HTTPException

from app.services.time_parser import parse_time_column
from app.utils.logger import get_logger, log_stage

logger = get_logger("data_prep")

FREQUENCY_MAP = {
    "D": {"alias": "D", "seasonal_period": 7, "label": "daily"},
    "W": {"alias": "W", "seasonal_period": 52, "label": "weekly"},
    "MS": {"alias": "MS", "seasonal_period": 12, "label": "monthly"},
    "QS": {"alias": "QS", "seasonal_period": 4, "label": "quarterly"},
    "YS": {"alias": "YS", "seasonal_period": None, "label": "yearly"},
}

# Per-frequency forecast horizon bounds (min, max periods)
HORIZON_BOUNDS = {
    "D": (7, 30),
    "W": (2, 12),
    "MS": (2, 6),
    "QS": (1, 2),
    "YS": (1, 2),
}

MAX_ROWS_FOR_MODELING = 150

# Ordered from finest to coarsest — used to validate frequency overrides
FREQ_ORDER = ["D", "W", "MS", "QS", "YS"]

# Defines the next coarser frequency for automatic downsampling
_UPSAMPLE_MAP = {
    "D": "W",
    "W": "MS",
}


def prepare_data(
    df: pd.DataFrame,
    date_column: str,
    target_column: str,
    file_hash: str = "",
    parsed_columns: dict | None = None,
    frequency_override: str | None = None,
    horizon_override: int | None = None,
) -> dict:
    with log_stage(logger, "data_preparation", file_hash=file_hash, row_count=len(df)):
        # Use pre-parsed columns from validator if available, otherwise parse here
        prepared = pd.DataFrame()
        if parsed_columns:
            prepared["ds"] = parsed_columns["parsed_dates"]
            prepared["y"] = parsed_columns["parsed_values"]
        else:
            parsed_dates, _ = parse_time_column(df[date_column])
            prepared["ds"] = parsed_dates
            prepared["y"] = pd.to_numeric(df[target_column], errors="coerce")
        prepared = prepared.dropna(subset=["ds"])

        # Sort chronologically
        prepared = prepared.sort_values("ds").reset_index(drop=True)

        # Aggregate duplicate dates using SUM
        prepared = prepared.groupby("ds", as_index=False)["y"].sum()

        # Detect frequency
        freq_info = detect_frequency(prepared["ds"])

        # Apply user-specified frequency override (must be coarser or equal)
        if frequency_override and frequency_override in FREQUENCY_MAP:
            detected_idx = FREQ_ORDER.index(freq_info["alias"])
            override_idx = FREQ_ORDER.index(frequency_override)
            if override_idx >= detected_idx and frequency_override != freq_info["alias"]:
                logger.info(
                    f"User override: resampling from {freq_info['label']} to "
                    f"{FREQUENCY_MAP[frequency_override]['label']}",
                    extra={"file_hash": file_hash},
                )
                resampled = prepared.set_index("ds").resample(frequency_override).sum().reset_index()
                resampled = resampled[resampled["y"] != 0]
                if len(resampled) >= 3:
                    prepared = resampled
                    freq_info = FREQUENCY_MAP[frequency_override]
                else:
                    logger.warning(
                        f"Resampling to {frequency_override} produced only {len(resampled)} rows, keeping detected frequency",
                        extra={"file_hash": file_hash},
                    )

        # Downsample if too many rows for efficient modeling
        prepared, freq_info = _maybe_downsample(prepared, freq_info, file_hash)

        # Interpolate missing values
        prepared["y"] = prepared["y"].interpolate(method="linear")
        prepared["y"] = prepared["y"].bfill().ffill()

        if prepared["y"].isna().all() or len(prepared) == 0:
            raise HTTPException(
                status_code=400,
                detail={"message": "No valid numbers found after processing. Check that your data column contains numeric values.", "error_code": "NO_VALID_VALUES"},
            )

        # Detect seasonal period (after downsampling, since freq may have changed)
        seasonal_period = _detect_seasonal_period(prepared, freq_info)

        # Add unique_id for statsforecast
        prepared["unique_id"] = "series_1"

        # Compute forecast horizon: 20% of data, clamped per frequency
        freq_alias = freq_info["alias"]
        min_h, max_h = HORIZON_BOUNDS.get(freq_alias, (4, 12))
        raw_horizon = max(min_h, min(max_h, round(len(prepared) * 0.20)))
        # Snap to nearest seasonal cycle if seasonality detected
        if seasonal_period and seasonal_period > 0:
            cycles = max(1, round(raw_horizon / seasonal_period))
            forecast_horizon = cycles * seasonal_period
            forecast_horizon = max(min_h, min(max_h, forecast_horizon))
        else:
            forecast_horizon = raw_horizon

        # Apply user-specified horizon override
        if horizon_override is not None:
            forecast_horizon = max(1, min(horizon_override, len(prepared)))
            logger.info(
                f"User override: horizon set to {forecast_horizon} (requested {horizon_override})",
                extra={"file_hash": file_hash},
            )

        logger.info(
            f"Prepared: {len(prepared)} rows, freq={freq_info['alias']}, "
            f"seasonal_period={seasonal_period}, horizon={forecast_horizon}",
            extra={"file_hash": file_hash, "row_count": len(prepared)},
        )

        return {
            "df": prepared[["unique_id", "ds", "y"]],
            "freq": freq_info["alias"],
            "seasonal_period": seasonal_period,
            "forecast_horizon": forecast_horizon,
            "freq_label": freq_info["label"],
        }


def _maybe_downsample(
    df: pd.DataFrame, freq_info: dict, file_hash: str = ""
) -> tuple[pd.DataFrame, dict]:
    """Resample to a coarser frequency if row count exceeds MAX_ROWS_FOR_MODELING."""
    current_alias = freq_info["alias"]

    while len(df) > MAX_ROWS_FOR_MODELING and current_alias in _UPSAMPLE_MAP:
        target_alias = _UPSAMPLE_MAP[current_alias]
        target_freq_info = FREQUENCY_MAP[target_alias]

        logger.info(
            f"Downsampling from {freq_info['label']} ({len(df)} rows) to "
            f"{target_freq_info['label']} to stay within {MAX_ROWS_FOR_MODELING}-row limit",
            extra={"file_hash": file_hash},
        )

        resampled = df.set_index("ds").resample(target_alias).sum().reset_index()
        resampled = resampled[resampled["y"] != 0]  # drop periods with no data
        if len(resampled) == 0:
            logger.warning(
                f"Downsampling to {target_alias} produced empty data, keeping current granularity",
                extra={"file_hash": file_hash},
            )
            break
        df = resampled
        freq_info = target_freq_info
        current_alias = target_alias

    # Safety cap: keep most recent rows if still too large
    if len(df) > MAX_ROWS_FOR_MODELING:
        logger.info(
            f"Capping data from {len(df)} to {MAX_ROWS_FOR_MODELING} most recent rows",
            extra={"file_hash": file_hash},
        )
        df = df.iloc[-MAX_ROWS_FOR_MODELING:].reset_index(drop=True)

    return df, freq_info


def detect_frequency(dates: pd.Series) -> dict:
    if len(dates) < 2:
        return FREQUENCY_MAP["MS"]

    diffs = dates.diff().dropna()
    if len(diffs) == 0:
        return FREQUENCY_MAP["MS"]

    median_diff = diffs.median()
    if pd.isna(median_diff):
        return FREQUENCY_MAP["MS"]

    days = median_diff.days

    if days <= 2:
        return FREQUENCY_MAP["D"]
    elif days <= 10:
        return FREQUENCY_MAP["W"]
    elif days <= 45:
        return FREQUENCY_MAP["MS"]
    elif days <= 200:
        return FREQUENCY_MAP["QS"]
    else:
        return FREQUENCY_MAP["YS"]


def _detect_seasonal_period(df: pd.DataFrame, freq_info: dict) -> int | None:
    sp = freq_info["seasonal_period"]
    if sp is None:
        return None
    # Need at least 2 full seasonal cycles
    if len(df) < 2 * sp:
        return None
    return sp
