import pandas as pd
import numpy as np

from app.utils.logger import get_logger, log_stage

logger = get_logger("data_prep")

FREQUENCY_MAP = {
    "D": {"alias": "D", "seasonal_period": 7, "label": "daily"},
    "W": {"alias": "W", "seasonal_period": 52, "label": "weekly"},
    "MS": {"alias": "MS", "seasonal_period": 12, "label": "monthly"},
    "QS": {"alias": "QS", "seasonal_period": 4, "label": "quarterly"},
}

MIN_PERIODS_FOR_SEASONALITY = 24


def prepare_data(
    df: pd.DataFrame,
    date_column: str,
    target_column: str,
    file_hash: str = "",
) -> dict:
    with log_stage(logger, "data_preparation", file_hash=file_hash, row_count=len(df)):
        # Parse dates and numeric target
        prepared = pd.DataFrame()
        prepared["ds"] = pd.to_datetime(df[date_column], format="mixed", errors="coerce")
        prepared["y"] = pd.to_numeric(df[target_column], errors="coerce")
        prepared = prepared.dropna(subset=["ds"])

        # Sort chronologically
        prepared = prepared.sort_values("ds").reset_index(drop=True)

        # Aggregate duplicate dates using SUM
        prepared = prepared.groupby("ds", as_index=False)["y"].sum()

        # Detect frequency
        freq_info = _detect_frequency(prepared["ds"])

        # Interpolate missing values
        prepared["y"] = prepared["y"].interpolate(method="linear")
        prepared["y"] = prepared["y"].bfill().ffill()

        # Detect seasonal period
        seasonal_period = _detect_seasonal_period(prepared, freq_info)

        # Add unique_id for statsforecast
        prepared["unique_id"] = "series_1"

        # Compute forecast horizon: 20% of data, clamped to [4, 12]
        raw_horizon = max(4, min(12, round(len(prepared) * 0.20)))
        # Snap to nearest seasonal cycle if seasonality detected
        if seasonal_period and seasonal_period > 0:
            cycles = max(1, round(raw_horizon / seasonal_period))
            forecast_horizon = cycles * seasonal_period
            forecast_horizon = max(4, min(12, forecast_horizon))
        else:
            forecast_horizon = raw_horizon

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


def _detect_frequency(dates: pd.Series) -> dict:
    if len(dates) < 2:
        return FREQUENCY_MAP["MS"]

    diffs = dates.diff().dropna()
    median_diff = diffs.median()
    days = median_diff.days

    if days <= 2:
        return FREQUENCY_MAP["D"]
    elif days <= 10:
        return FREQUENCY_MAP["W"]
    elif days <= 45:
        return FREQUENCY_MAP["MS"]
    else:
        return FREQUENCY_MAP["QS"]


def _detect_seasonal_period(df: pd.DataFrame, freq_info: dict) -> int | None:
    if len(df) < MIN_PERIODS_FOR_SEASONALITY:
        return None
    return freq_info["seasonal_period"]
