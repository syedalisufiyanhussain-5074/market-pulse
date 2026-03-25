import pandas as pd

from app.services.time_parser import looks_like_time_column
from app.utils.logger import get_logger, log_stage

logger = get_logger("column_detector")

NUMERIC_DENSITY_THRESHOLD = 0.50


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


_SAMPLE_SIZE = 1000


def _is_date_column(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if pd.api.types.is_numeric_dtype(series):
        # Check if values look like years (e.g., 2020, 2021, 2022)
        clean = series.dropna()
        if len(clean) >= 3:
            vals = clean.astype(float)
            all_integer = (vals == vals.astype(int)).all()
            in_range = (vals >= 1900).all() and (vals <= 2100).all()
            if all_integer and in_range:
                return True
        return False
    # Sample first for speed, full validation only if sample passes
    if len(series) > _SAMPLE_SIZE:
        if not looks_like_time_column(series.head(_SAMPLE_SIZE)):
            return False
    return looks_like_time_column(series)


def _is_numeric_column(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        non_null_ratio = series.notna().sum() / len(series)
        return non_null_ratio >= NUMERIC_DENSITY_THRESHOLD

    total = len(series)
    if total == 0:
        return False
    # Sample first for speed
    if total > _SAMPLE_SIZE:
        sample = pd.to_numeric(series.head(_SAMPLE_SIZE), errors="coerce")
        if sample.notna().sum() / len(sample) < NUMERIC_DENSITY_THRESHOLD:
            return False
    coerced = pd.to_numeric(series, errors="coerce")
    return coerced.notna().sum() / total >= NUMERIC_DENSITY_THRESHOLD
