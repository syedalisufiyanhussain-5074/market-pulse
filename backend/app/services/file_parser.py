import hashlib
import io
from pathlib import Path

import pandas as pd
from fastapi import HTTPException, UploadFile

from app.utils.logger import get_logger, log_stage

logger = get_logger("file_parser")

ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
MAX_ROWS = 100_000


async def parse_upload(file: UploadFile) -> tuple[pd.DataFrame, str]:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Please upload a .csv or .xlsx file.",
        )

    contents = await file.read()
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
                detail="Unable to read the file. Please ensure it is a valid CSV or Excel file.",
            )

    if len(df) > MAX_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"Dataset exceeds the maximum of {MAX_ROWS:,} rows. Please reduce the dataset size.",
        )

    if len(df) == 0:
        raise HTTPException(status_code=400, detail="The uploaded file contains no data.")

    logger.info(
        f"Parsed {len(df)} rows, {len(df.columns)} columns",
        extra={"file_hash": file_hash, "row_count": len(df)},
    )
    return df, file_hash
