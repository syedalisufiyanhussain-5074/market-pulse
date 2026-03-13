import re

import numpy as np
import pandas as pd

from app.utils.logger import get_logger

logger = get_logger("time_parser")

DATE_PARSE_THRESHOLD = 0.90

# Pattern for quarter strings: 2023-Q1, 2023Q2, Q3-2023, etc.
_QUARTER_PATTERN = re.compile(
    r"^\d{4}[-/]?Q[1-4]$|^Q[1-4][-/]?\d{4}$", re.IGNORECASE
)


def parse_time_column(series: pd.Series) -> tuple[pd.Series, str | None]:
    """
    Parse a column into datetime timestamps.

    Returns (parsed_series, detected_format) where detected_format is one of:
    "datetime", "year_only", "quarter", "mixed", or None if unparseable.

    The returned series has NaT for values that couldn't be parsed.
    """
    non_null = series.dropna()
    if len(non_null) == 0:
        return pd.Series(dtype="datetime64[ns]"), None

    # 1. Already datetime
    if pd.api.types.is_datetime64_any_dtype(series):
        return series, "datetime"

    # 2. Numeric → check if plausible years (4-digit ints in 1900–2100)
    if pd.api.types.is_numeric_dtype(series):
        if _looks_like_years(non_null):
            parsed = pd.to_datetime(
                series.astype(float).astype("Int64"), format="%Y", errors="coerce"
            )
            return parsed, "year_only"
        return pd.Series([pd.NaT] * len(series), index=series.index, dtype="datetime64[ns]"), None

    # 3. String → try quarter pattern first (pd.to_datetime can't handle it)
    str_series = series.astype(str).str.strip()
    non_null_str = str_series[series.notna()]
    if _looks_like_quarters(non_null_str):
        try:
            parsed = pd.Series(
                pd.PeriodIndex(str_series, freq="Q").to_timestamp(),
                index=series.index,
            )
            return parsed, "quarter"
        except Exception:
            pass

    # 4. Standard pd.to_datetime (handles full dates, YYYY-MM, ISO, etc.)
    parsed = pd.to_datetime(str_series, format="mixed", dayfirst=False, errors="coerce")
    valid_ratio = parsed.notna().sum() / len(non_null) if len(non_null) > 0 else 0
    if valid_ratio >= DATE_PARSE_THRESHOLD:
        return parsed, "mixed"

    return parsed, None


def looks_like_time_column(series: pd.Series) -> bool:
    """Quick check: could this column be a date/time column?"""
    non_null = series.dropna()
    if len(non_null) == 0:
        return False
    parsed, fmt = parse_time_column(series)
    if fmt is None:
        return False
    valid_ratio = parsed.notna().sum() / len(non_null)
    return valid_ratio >= DATE_PARSE_THRESHOLD


def _looks_like_years(series: pd.Series) -> bool:
    """Check if numeric series contains plausible 4-digit years."""
    non_null = series.dropna()
    if len(non_null) == 0:
        return False
    # Must all be integers (no fractional part)
    try:
        if not np.all(non_null == non_null.astype(int)):
            return False
    except (ValueError, TypeError):
        return False
    int_vals = non_null.astype(int)
    return bool((int_vals >= 1900).all() and (int_vals <= 2100).all())


def _looks_like_quarters(str_series: pd.Series) -> bool:
    """Check if >=90% of non-null string values match quarter patterns."""
    if len(str_series) == 0:
        return False
    matches = str_series.str.match(_QUARTER_PATTERN, na=False)
    return matches.sum() / len(str_series) >= DATE_PARSE_THRESHOLD
