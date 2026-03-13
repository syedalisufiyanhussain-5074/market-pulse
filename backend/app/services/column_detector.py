import pandas as pd

from app.services.time_parser import looks_like_time_column
from app.utils.logger import get_logger, log_stage

logger = get_logger("column_detector")

NUMERIC_DENSITY_THRESHOLD = 0.95


def detect_columns(df: pd.DataFrame, file_hash: str = "") -> dict:
    with log_stage(logger, "column_detection", file_hash=file_hash):
        date_columns = []
        numeric_columns = []

        for col in df.columns:
            series = df[col].dropna()
            if len(series) == 0:
                continue

            # Check for date-like columns
            if _is_date_column(series):
                date_columns.append(str(col))
                continue

            # Check for numeric columns with >=95% density
            if _is_numeric_column(df[col]):
                numeric_columns.append(str(col))

    logger.info(
        f"Detected {len(date_columns)} date columns, {len(numeric_columns)} numeric columns",
        extra={"file_hash": file_hash},
    )
    return {"date_columns": date_columns, "numeric_columns": numeric_columns}


def _is_date_column(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    return looks_like_time_column(series)


def _is_numeric_column(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        non_null_ratio = series.notna().sum() / len(series)
        return non_null_ratio >= NUMERIC_DENSITY_THRESHOLD

    coerced = pd.to_numeric(series, errors="coerce")
    total = len(series)
    if total == 0:
        return False
    valid_ratio = coerced.notna().sum() / total
    return valid_ratio >= NUMERIC_DENSITY_THRESHOLD
