import time

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from app.schemas.responses import UploadResponse
from app.services.file_parser import parse_upload
from app.services.column_detector import detect_columns
from app.services.time_parser import parse_time_column
from app.services.data_prep import detect_frequency
from app.utils.logger import get_logger, log_stage, audit_log
from app.utils import file_cache

logger = get_logger("upload_router")
router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload", response_model=UploadResponse)
async def upload_file(request: Request, file: UploadFile = File(...)):
    t0 = time.perf_counter()
    session_id = getattr(request.state, "session_id", None)
    try:
        with log_stage(logger, "data_processing"):
            df, file_hash = await parse_upload(file)
            file_cache.put(file_hash, df)

            columns = detect_columns(df, file_hash=file_hash)

            # Detect frequency and unique period count for each date column
            frequency_map = {}
            period_count_map = {}
            for col in columns["date_columns"]:
                try:
                    parsed_dates, _ = parse_time_column(df[col])
                    valid_dates = parsed_dates.dropna().drop_duplicates().sort_values().reset_index(drop=True)
                    if len(valid_dates) >= 2:
                        freq_info = detect_frequency(valid_dates)
                        frequency_map[col] = freq_info["alias"]
                        period_count_map[col] = int(valid_dates.nunique())
                    else:
                        frequency_map[col] = "MS"
                        period_count_map[col] = len(valid_dates)
                except Exception:
                    frequency_map[col] = "MS"
                    period_count_map[col] = 0

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
                frequency_map=frequency_map,
                period_count_map=period_count_map,
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
