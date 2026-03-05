import pandas as pd
from fastapi import HTTPException

from app.utils.logger import get_logger, log_stage

logger = get_logger("validator")

MIN_PERIODS = 12
MAX_MISSING_RATIO = 0.05


def validate_data(
    df: pd.DataFrame,
    date_column: str,
    target_column: str,
    file_hash: str = "",
) -> None:
    with log_stage(logger, "data_validation", file_hash=file_hash):
        _validate_columns_exist(df, date_column, target_column)
        _validate_date_column(df, date_column, file_hash)
        _validate_target_column(df, target_column, file_hash)


def _validate_columns_exist(df: pd.DataFrame, date_column: str, target_column: str) -> None:
    if date_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{date_column}' not found in dataset.")
    if target_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Column '{target_column}' not found in dataset.")


def _validate_date_column(df: pd.DataFrame, date_column: str, file_hash: str) -> None:
    dates = pd.to_datetime(df[date_column], format="mixed", errors="coerce")
    unique_periods = dates.dropna().nunique()

    if unique_periods < MIN_PERIODS:
        logger.warning(
            f"Insufficient time periods: {unique_periods} (need {MIN_PERIODS})",
            extra={"file_hash": file_hash},
        )
        raise HTTPException(
            status_code=400,
            detail=f"The dataset requires at least {MIN_PERIODS} unique time periods for reliable forecasting. Found {unique_periods}.",
        )


def _validate_target_column(df: pd.DataFrame, target_column: str, file_hash: str) -> None:
    numeric_series = pd.to_numeric(df[target_column], errors="coerce")
    total = len(numeric_series)
    missing = numeric_series.isna().sum()
    missing_ratio = missing / total if total > 0 else 1.0

    if missing_ratio > MAX_MISSING_RATIO:
        logger.warning(
            f"Excessive missing values: {missing}/{total} ({missing_ratio:.1%})",
            extra={"file_hash": file_hash},
        )
        raise HTTPException(
            status_code=400,
            detail="The dataset contains excessive missing values. Please provide a more complete dataset for reliable forecasting.",
        )
