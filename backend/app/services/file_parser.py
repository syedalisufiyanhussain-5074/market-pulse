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
            detail={"message": "The uploaded file contains no data.", "error_code": "EMPTY_FILE"},
        )

    if len(df.columns) > MAX_COLUMNS:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Dataset exceeds the maximum of {MAX_COLUMNS} columns. Please reduce the number of columns.", "error_code": "TOO_MANY_COLUMNS"},
        )

    if len(df) > MAX_ROWS:
        raise HTTPException(
            status_code=400,
            detail={"message": f"Dataset exceeds the maximum of {MAX_ROWS:,} rows. Please reduce the dataset size.", "error_code": "TOO_MANY_ROWS"},
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
            detail={"message": f"File exceeds the maximum size of {MAX_FILE_SIZE // (1024 * 1024)}MB. Please reduce the file size.", "error_code": "FILE_TOO_LARGE"},
        )

    contents = await file.read()

    # Fallback size check (file.size may not always be set)
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail={"message": f"File exceeds the maximum size of {MAX_FILE_SIZE // (1024 * 1024)}MB. Please reduce the file size.", "error_code": "FILE_TOO_LARGE"},
        )

    return parse_from_bytes(contents, file.filename or "")
