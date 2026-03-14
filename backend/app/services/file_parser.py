import hashlib
import io
from pathlib import Path

import pandas as pd
from fastapi import HTTPException, UploadFile

from app.utils.logger import get_logger, log_stage

logger = get_logger("file_parser")

ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
MAX_ROWS = 100_000
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_COLUMNS = 20


def parse_from_bytes(contents: bytes, filename: str) -> tuple[pd.DataFrame, str]:
    """Sync parsing logic shared by both async upload and SSE stream endpoints."""
    extension = Path(filename or "").suffix.lower()
    file_hash = hashlib.sha256(contents).hexdigest()[:12]

    with log_stage(logger, "file_parsing", file_hash=file_hash):
        try:
            if extension == ".csv":
                df = pd.read_csv(io.BytesIO(contents))
            else:
                try:
                    df = pd.read_excel(io.BytesIO(contents), sheet_name=0, engine="calamine")
                except Exception:
                    df = pd.read_excel(io.BytesIO(contents), sheet_name=0, engine="openpyxl")
        except Exception as e:
            logger.error(f"Parse error: {e}", extra={"file_hash": file_hash})
            raise HTTPException(
                status_code=400,
                detail={"message": "Unable to read the file. Please ensure it is a valid CSV or Excel file.", "error_code": "PARSE_ERROR"},
            )

    if len(df) == 0:
        raise HTTPException(
            status_code=400,
            detail={"message": "The file appears to be empty. Please upload a file with data.", "error_code": "EMPTY_FILE"},
        )

    if len(df.columns) > MAX_COLUMNS:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Too many columns (max {MAX_COLUMNS}). Remove extra columns and try again.", "error_code": "TOO_MANY_COLUMNS"},
        )

    if len(df) > MAX_ROWS:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Too many rows (max {MAX_ROWS:,}). Trim your dataset and try again.", "error_code": "TOO_MANY_ROWS"},
        )

    logger.info(
        f"Parsed {len(df)} rows, {len(df.columns)} columns",
        extra={"file_hash": file_hash, "row_count": len(df)},
    )
    return df, file_hash


async def parse_upload(file: UploadFile) -> tuple[pd.DataFrame, str]:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail={"message": "Unsupported file format. Please upload a .csv or .xlsx file.", "error_code": "UNSUPPORTED_FORMAT"},
        )

    # Pre-check file size if available
    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail={"message": "File is too large (max 10 MB). Try a smaller file.", "error_code": "FILE_TOO_LARGE"},
        )

    contents = await file.read()

    # Fallback size check (file.size may not always be set)
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail={"message": "File is too large (max 10 MB). Try a smaller file.", "error_code": "FILE_TOO_LARGE"},
        )

    return parse_from_bytes(contents, file.filename or "")
