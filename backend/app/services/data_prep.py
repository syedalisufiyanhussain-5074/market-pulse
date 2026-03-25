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
    "D": (7, 365),
    "W": (2, 52),
    "MS": (2, 36),
    "QS": (1, 8),
    "YS": (1, 5),
}

MAX_ROWS_FOR_MODELING = 150
MAX_MISSING_DATE_RATIO = 0.05

# Approximate days per period — used to scale horizon after downsampling
APPROX_DAYS = {"D": 1, "W": 7, "MS": 30, "QS": 91, "YS": 365}

# Ordered from finest to coarsest — used to validate frequency overrides
FREQ_ORDER = ["D", "W", "MS", "QS", "YS"]

# Defines the next coarser frequency for automatic downsampling
_UPSAMPLE_MAP = {
    "D": "W",
    "W": "MS",
}


def _is_irregular(dates: pd.Series) -> bool:
    """Check if date spacing is too inconsistent for any regular frequency."""
    diffs = dates.diff().dropna().dt.days
    if len(diffs) < 2:
        return False
    median = diffs.median()
    if median == 0:
        return True
    cv = diffs.std() / median
    return cv > 0.5


def _validate_date_gaps(df: pd.DataFrame, freq_alias: str, file_hash: str = "") -> None:
    """Reject data with >5% missing dates based on detected frequency."""
    if len(df) < 2:
        return

    date_range = pd.date_range(start=df["ds"].min(), end=df["ds"].max(), freq=freq_alias)
    expected_count = len(date_range)
    actual_count = len(df)
    missing_dates = expected_count - actual_count

    if missing_dates <= 0:
        return

    missing_ratio = missing_dates / expected_count
    if missing_ratio > MAX_MISSING_DATE_RATIO:
        logger.warning(
            f"Excessive date gaps: {missing_dates}/{expected_count} periods missing ({missing_ratio:.1%})",
            extra={"file_hash": file_hash},
        )
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    f"The dataset contains {missing_dates} missing time periods out of {expected_count} expected "
                    f"({missing_ratio:.0%}), exceeding the 5% allowable threshold. "
                    f"Please fill in the missing periods or upload a more complete dataset to proceed."
                ),
                "error_code": "EXCESSIVE_DATE_GAPS",
            },
        )


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
        # Infer missing dates from position + frequency before dropping anything
        has_date = prepared["ds"].notna()
        if has_date.any() and not has_date.all():
            nat_count = (~has_date).sum()
            nat_ratio = nat_count / len(prepared)

            # Reject if >5% dates are missing (same threshold as _validate_date_gaps)
            if nat_ratio > 0.05:
                expected_count = len(prepared)
                pct = int(round(nat_ratio * 100))
                logger.warning(
                    f"Excessive date gaps: {nat_count}/{expected_count} periods missing ({nat_ratio:.1%})",
                    extra={"file_hash": file_hash},
                )
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": (
                            f"The dataset contains {nat_count} missing time periods out of {expected_count} expected "
                            f"({pct}%), exceeding the 5% allowable threshold. "
                            f"Please fill in the missing periods or upload a more complete dataset to proceed."
                        ),
                        "error_code": "EXCESSIVE_DATE_GAPS",
                    },
                )

            # Detect frequency from rows that have valid dates
            valid_dates = prepared.loc[has_date, "ds"].sort_values().reset_index(drop=True)
            freq_guess = detect_frequency(valid_dates)
            freq_alias = freq_guess["alias"]

            # Build expected date sequence from the first valid date
            first_valid_idx = has_date.idxmax()
            first_valid_date = prepared.loc[first_valid_idx, "ds"]

            # Infer dates for NaT rows based on position relative to first valid date
            for i in range(len(prepared)):
                if pd.isna(prepared.loc[i, "ds"]):
                    offset = i - first_valid_idx
                    prepared.loc[i, "ds"] = first_valid_date + offset * pd.tseries.frequencies.to_offset(freq_alias)

        prepared = prepared.dropna(subset=["ds"])

        # Sort chronologically
        prepared = prepared.sort_values("ds").reset_index(drop=True)

        # Aggregate duplicate dates using SUM (min_count=1 preserves NaN)
        prepared = prepared.groupby("ds", as_index=False)["y"].sum(min_count=1)

        # Detect frequency
        freq_info = detect_frequency(prepared["ds"])

        # Validate: reject data with >5% date gaps; auto-resample if irregular
        try:
            _validate_date_gaps(prepared, freq_info["alias"], file_hash)
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, dict) else {}
            if detail.get("error_code") == "EXCESSIVE_DATE_GAPS" and _is_irregular(prepared["ds"]):
                # Try auto-resample to monthly
                resampled = prepared.set_index("ds").resample("MS").mean(numeric_only=True).reset_index()
                resampled = resampled.dropna(subset=["y"])
                if len(resampled) >= 12:
                    logger.info(
                        f"Irregular data auto-resampled to monthly ({len(resampled)} rows)",
                        extra={"file_hash": file_hash},
                    )
                    prepared = resampled
                    freq_info = FREQUENCY_MAP["MS"]
                    # Re-validate after resample
                    _validate_date_gaps(prepared, freq_info["alias"], file_hash)
                else:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "message": (
                                "The dataset has irregular time intervals that cannot be automatically resampled. "
                                "Market Pulse requires regularly spaced data (e.g., every month, every week). "
                                "Please resample your data to a consistent frequency before uploading."
                            ),
                            "error_code": "IRREGULAR_INTERVALS",
                        },
                    )
            else:
                raise

        # Reindex to fill missing dates with NaN values (enables interpolation)
        # Use infer_freq for exact anchor (e.g., W-MON vs W-SUN), fall back to detected alias
        _exact_freq = pd.infer_freq(prepared["ds"]) or freq_info["alias"]
        full_index = pd.date_range(
            start=prepared["ds"].min(),
            end=prepared["ds"].max(),
            freq=_exact_freq,
        )
        prepared = prepared.set_index("ds").reindex(full_index).reset_index()
        prepared = prepared.rename(columns={"index": "ds"})

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
                resampled = prepared.set_index("ds").resample(frequency_override).sum(min_count=1).reset_index()
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
        original_alias = freq_info["alias"]
        prepared, freq_info = _maybe_downsample(prepared, freq_info, file_hash)

        # Scale horizon_override if downsampling changed the frequency
        if horizon_override is not None and freq_info["alias"] != original_alias:
            original_override = horizon_override
            orig_days = APPROX_DAYS.get(original_alias, 1)
            new_days = APPROX_DAYS.get(freq_info["alias"], 1)
            horizon_override = max(1, round(horizon_override * orig_days / new_days))
            logger.info(
                f"Horizon scaled: {original_override} {original_alias} → {horizon_override} {freq_info['alias']}",
                extra={"file_hash": file_hash},
            )

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

        # Guarantee CV can produce at least one valid training window
        # CV needs: len(data) - horizon >= horizon → horizon <= len(data) // 2
        max_cv_horizon = max(1, -(-len(prepared) // 2))  # ceil division
        if forecast_horizon > max_cv_horizon:
            logger.info(
                f"Horizon clamped from {forecast_horizon} to {max_cv_horizon} "
                f"(need at least {forecast_horizon * 2} rows for {forecast_horizon}-step CV)",
                extra={"file_hash": file_hash},
            )
            forecast_horizon = max_cv_horizon

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

        resampled = df.set_index("ds").resample(target_alias).sum(min_count=1).reset_index()
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
