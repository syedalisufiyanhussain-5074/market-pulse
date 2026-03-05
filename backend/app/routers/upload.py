from fastapi import APIRouter, File, UploadFile

from app.schemas.responses import UploadResponse
from app.services.file_parser import parse_upload
from app.services.column_detector import detect_columns

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    df, file_hash = await parse_upload(file)

    columns = detect_columns(df, file_hash=file_hash)

    preview = df.head(5).fillna("").to_dict(orient="records")

    return UploadResponse(
        date_columns=columns["date_columns"],
        numeric_columns=columns["numeric_columns"],
        preview=preview,
        file_hash=file_hash,
        row_count=len(df),
    )
