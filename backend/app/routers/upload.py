import time

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from app.schemas.responses import UploadResponse
from app.services.file_parser import parse_upload
from app.services.column_detector import detect_columns
from app.utils.logger import get_logger, log_stage, audit_log

logger = get_logger("upload_router")
router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload", response_model=UploadResponse)
async def upload_file(request: Request, file: UploadFile = File(...)):
    t0 = time.perf_counter()
    session_id = getattr(request.state, "session_id", None)
    try:
        with log_stage(logger, "data_processing"):
            df, file_hash = await parse_upload(file)

            columns = detect_columns(df, file_hash=file_hash)

            preview = df.head(5).fillna("").to_dict(orient="records")

            duration = round((time.perf_counter() - t0) * 1000, 1)
            audit_log(
                event_type="file_upload",
                component="upload_router",
                session_id=session_id,
                duration_ms=duration,
            )

            return UploadResponse(
                date_columns=columns["date_columns"],
                numeric_columns=columns["numeric_columns"],
                preview=preview,
                file_hash=file_hash,
                row_count=len(df),
            )
    except HTTPException as e:
        duration = round((time.perf_counter() - t0) * 1000, 1)
        detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        audit_log(
            event_type="error",
            component="upload_router",
            session_id=session_id,
            notes=detail.get("message", str(e.detail)),
            error_code=detail.get("error_code"),
            duration_ms=duration,
        )
        raise
    except Exception as e:
        duration = round((time.perf_counter() - t0) * 1000, 1)
        audit_log(
            event_type="error",
            component="upload_router",
            session_id=session_id,
            notes=str(e),
            error_code="INTERNAL_ERROR",
            duration_ms=duration,
        )
        raise
