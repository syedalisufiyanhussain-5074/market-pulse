import pandas as pd
from fastapi import HTTPException

from app.services.time_parser import parse_time_column
from app.utils.logger import get_logger, log_stage

logger = get_logger("validator")

MIN_PERIODS = 12
MAX_MISSING_RATIO = 0.05


def validate_data(
    df: pd.DataFrame,
    date_column: str,
    target_column: str,
    file_hash: str = "",
) -> dict:
    """Validate data and return pre-parsed columns to avoid double parsing in data_prep."""
    with log_stage(logger, "data_validation", file_hash=file_hash):
        _validate_columns_exist(df, date_column, target_column)

        with log_stage(logger, "date_parsing", file_hash=file_hash):
            parsed_dates, _ = parse_time_column(df[date_column])
        _validate_date_column(parsed_dates, file_hash)

        with log_stage(logger, "numeric_parsing", file_hash=file_hash):
            parsed_values = pd.to_numeric(df[target_column], errors="coerce")
        _validate_target_column(parsed_values, file_hash)

        return {"parsed_dates": parsed_dates, "parsed_values": parsed_values}


def _validate_columns_exist(df: pd.DataFrame, date_column: str, target_column: str) -> None:
    if date_column not in df.columns:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Column '{date_column}' not found in dataset.", "error_code": "COLUMN_NOT_FOUND"},
        )
    if target_column not in df.columns:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Column '{target_column}' not found in dataset.", "error_code": "COLUMN_NOT_FOUND"},
        )


def _validate_date_column(dates: pd.Series, file_hash: str) -> None:
    unique_periods = dates.dropna().nunique()

    if unique_periods < MIN_PERIODS:
        logger.warning(
            f"Insufficient time periods: {unique_periods} (need {MIN_PERIODS})",
            extra={"file_hash": file_hash},
        )
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Not enough data — we need at least {MIN_PERIODS} time periods for a reliable forecast. Found only {unique_periods}.",
                "error_code": "INSUFFICIENT_PERIODS",
            },
        )


def _validate_target_column(numeric_series: pd.Series, file_hash: str) -> None:
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
            detail={
                "message": "Too many missing values in your data. Fill in the gaps or use a more complete dataset.",
                "error_code": "EXCESSIVE_MISSING",
            },
        )
