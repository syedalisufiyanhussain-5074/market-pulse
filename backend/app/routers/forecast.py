import hashlib
import io
import json
import math
import time
import threading
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.config import APP_VERSION
from app.schemas.responses import ForecastResponse
from app.schemas.requests import PDFExportRequest, ExcelExportRequest
from app.services.excel_export import generate_excel
from app.services.file_parser import parse_upload, parse_from_bytes
from app.services.validator import validate_data
from app.services.data_prep import prepare_data
from app.services.modeling import run_models, fit_ets, fit_arima, build_forecast_df
from app.services.evaluation import evaluate_models, compute_forecast_deviation_pct
from app.services.decision import select_best_model, update_comparison_summary
from app.services.visualization import generate_charts
from app.services.pdf_export import generate_pdf
from app.utils.logger import get_logger, log_stage, audit_log
from app.utils import file_cache

logger = get_logger("forecast_router")
router = APIRouter(prefix="/api", tags=["forecast"])


def _sanitize(value):
    """Replace NaN/Inf with None for JSON-safe serialization."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _build_result(prepared_df, model_result, metrics, decision, charts, forecast_horizon, freq, preference):
    """Build the forecast result dict (shared by both endpoints)."""
    forecasts = model_result["forecasts"]
    sel_model = decision["selected_model"]
    pred_col_matches = [c for c in forecasts.columns if sel_model in c and "lo" not in c and "hi" not in c]
    if not pred_col_matches:
        raise HTTPException(status_code=500, detail={"message": "Something went wrong while building the forecast. Please try again.", "error_code": "INTERNAL_ERROR"})
    pred_col = pred_col_matches[0]
    lo_col = [c for c in forecasts.columns if sel_model in c and "lo" in c]
    hi_col = [c for c in forecasts.columns if sel_model in c and "hi" in c]

    def _safe_round(val):
        v = float(val)
        return None if math.isnan(v) or math.isinf(v) else round(v, 2)

    forecast_data = []
    for i, row in forecasts.iterrows():
        entry = {
            "date": row["ds"].isoformat(),
            "value": _safe_round(row[pred_col]),
        }
        if lo_col:
            entry["lower_bound"] = _safe_round(row[lo_col[0]])
        if hi_col:
            entry["upper_bound"] = _safe_round(row[hi_col[0]])
        forecast_data.append(entry)

    historical_data = [
        {"date": row["ds"].isoformat(), "value": round(float(row["y"]), 2)}
        for _, row in prepared_df.iterrows()
    ]

    forecast_bias = "Over-Forecast" if preference == "capacity-buffered" else "Under-Forecast"

    return _sanitize({
        "selected_model": decision["selected_model"],
        "mae_value": decision["selected_metrics"]["mae"],
        "forecast_horizon": forecast_horizon,
        "forecast_bias": forecast_bias,
        "chart1_base64": charts["chart1_base64"],
        "chart2_base64": charts["chart2_base64"],
        "summary1": decision["summary1"],
        "summary2": decision["summary2"],
        "forecast_data": forecast_data,
        "historical_data": historical_data,
        "frequency": freq,
        "metrics": {
            "AutoETS": metrics["AutoETS"],
            "AutoARIMA": metrics["AutoARIMA"],
            "Moving Average (Excel)": metrics["Moving Average (Excel)"],
            "ETS (Excel)": metrics["ETS (Excel)"],
        },
    })


@router.post("/forecast", response_model=ForecastResponse)
async def run_forecast(
    request: Request,
    file: UploadFile = File(...),
    date_column: str = Form(...),
    target_column: str = Form(...),
    preference: str = Form(...),
    frequency: str | None = Form(None),
    num_predictions: int | None = Form(None),
):
    t0 = time.perf_counter()
    session_id = getattr(request.state, "session_id", None)
    try:
        with log_stage(logger, "prediction_generation"):
            df, file_hash = await parse_upload(file)
            file_cache.put(file_hash, df)
            parsed = validate_data(df, date_column, target_column, file_hash=file_hash)
            prep_result = prepare_data(df, date_column, target_column, file_hash=file_hash, parsed_columns=parsed, frequency_override=frequency, horizon_override=num_predictions)
            prepared_df = prep_result["df"]
            freq = prep_result["freq"]
            seasonal_period = prep_result["seasonal_period"]
            forecast_horizon = prep_result["forecast_horizon"]

            model_result = run_models(
                prepared_df, freq, seasonal_period, forecast_horizon, file_hash=file_hash
            )

            metrics, excel_ets_forecast = evaluate_models(
                model_result["cv_results"],
                prepared_df,
                forecast_horizon,
                file_hash=file_hash,
            )

            decision = select_best_model(metrics, preference, file_hash=file_hash)

            forecast_dev_pct = compute_forecast_deviation_pct(
                model_result["forecasts"],
                decision["selected_model"],
                prepared_df["y"].values,
                forecast_horizon,
                excel_ets_forecast,
            )
            update_comparison_summary(decision, metrics, forecast_dev_pct)

            charts = generate_charts(
                historical_df=prepared_df,
                forecasts=model_result["forecasts"],
                selected_model=decision["selected_model"],
                alternative_model=decision["alternative_model"],
                forecast_horizon=forecast_horizon,
                excel_ets_forecast=excel_ets_forecast,
                file_hash=file_hash,
            )

            result = _build_result(prepared_df, model_result, metrics, decision, charts, forecast_horizon, freq, preference)
            audit_log(
                event_type="forecast_run",
                component="forecast_router",
                session_id=session_id,
                notes=result["forecast_bias"],
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
            return ForecastResponse(**result)
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        audit_log(
            event_type="error",
            component="forecast_router",
            session_id=session_id,
            notes=detail.get("message", str(e.detail)),
            error_code=detail.get("error_code"),
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
        raise
    except Exception as e:
        audit_log(
            event_type="error",
            component="forecast_router",
            session_id=session_id,
            notes=str(e),
            error_code="INTERNAL_ERROR",
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
        raise


def _sse(event: str, **data) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _run_with_heartbeats(fn, interval=10):
    """Run fn() in a background thread, yielding heartbeats while it runs."""
    result = [None]
    error = [None]

    def worker():
        try:
            result[0] = fn()
        except Exception as e:
            error[0] = e

    thread = threading.Thread(target=worker)
    thread.start()
    while thread.is_alive():
        thread.join(timeout=interval)
        if thread.is_alive():
            yield _sse("heartbeat")
    if error[0] is not None:
        raise error[0]
    yield result[0]


@router.post("/forecast/stream")
async def run_forecast_stream(
    request: Request,
    file: UploadFile = File(...),
    date_column: str = Form(...),
    target_column: str = Form(...),
    preference: str = Form(...),
    frequency: str | None = Form(None),
    num_predictions: int | None = Form(None),
):
    # Read file bytes in async context before entering sync generator
    contents = await file.read()
    filename = file.filename or ""
    session_id = getattr(request.state, "session_id", None)

    def generate():
        t0 = time.perf_counter()
        try:
            yield _sse("progress", progress=5, message="Reading your data...")
            # Try cache first (DataFrame was cached during upload)
            file_hash = hashlib.sha256(contents).hexdigest()[:12]
            cached_df = file_cache.get(file_hash)
            if cached_df is not None:
                df = cached_df
            else:
                parse_result = None
                for item in _run_with_heartbeats(
                    lambda: parse_from_bytes(contents, filename)
                ):
                    if isinstance(item, str):
                        yield item
                    else:
                        parse_result = item
                df, file_hash = parse_result

            yield _sse("progress", progress=15, message="Checking data quality...")
            parsed = None
            for item in _run_with_heartbeats(
                lambda: validate_data(df, date_column, target_column, file_hash=file_hash)
            ):
                if isinstance(item, str):
                    yield item
                else:
                    parsed = item

            yield _sse("progress", progress=25, message="Preparing time series...")
            prep_result = None
            for item in _run_with_heartbeats(
                lambda: prepare_data(df, date_column, target_column, file_hash=file_hash, parsed_columns=parsed, frequency_override=frequency, horizon_override=num_predictions)
            ):
                if isinstance(item, str):
                    yield item
                else:
                    prep_result = item
            prepared_df = prep_result["df"]
            freq = prep_result["freq"]
            seasonal_period = prep_result["seasonal_period"]
            forecast_horizon = prep_result["forecast_horizon"]

            yield _sse("heartbeat")
            yield _sse("progress", progress=35, message="Training forecast model 1 of 2...")
            ets_result = None
            for item in _run_with_heartbeats(
                lambda: fit_ets(prepared_df, seasonal_period, forecast_horizon, file_hash=file_hash)
            ):
                if isinstance(item, str):
                    yield item
                else:
                    ets_result = item

            yield _sse("heartbeat")
            yield _sse("progress", progress=55, message="Training forecast model 2 of 2...")
            arima_result = None
            for item in _run_with_heartbeats(
                lambda: fit_arima(prepared_df, seasonal_period, forecast_horizon, file_hash=file_hash)
            ):
                if isinstance(item, str):
                    yield item
                else:
                    arima_result = item

            yield _sse("heartbeat")
            yield _sse("progress", progress=68, message="Generating predictions...")
            model_result = build_forecast_df(prepared_df, freq, forecast_horizon, ets_result, arima_result, file_hash=file_hash)

            yield _sse("heartbeat")
            yield _sse("progress", progress=78, message="Comparing model accuracy...")
            metrics, excel_ets_forecast = evaluate_models(
                model_result["cv_results"],
                prepared_df,
                forecast_horizon,
                file_hash=file_hash,
            )

            yield _sse("heartbeat")
            yield _sse("progress", progress=85, message="Selecting the best model...")
            decision = select_best_model(metrics, preference, file_hash=file_hash)

            forecast_dev_pct = compute_forecast_deviation_pct(
                model_result["forecasts"],
                decision["selected_model"],
                prepared_df["y"].values,
                forecast_horizon,
                excel_ets_forecast,
            )
            update_comparison_summary(decision, metrics, forecast_dev_pct)

            yield _sse("heartbeat")
            yield _sse("progress", progress=92, message="Building visualizations...")
            charts = generate_charts(
                historical_df=prepared_df,
                forecasts=model_result["forecasts"],
                selected_model=decision["selected_model"],
                alternative_model=decision["alternative_model"],
                forecast_horizon=forecast_horizon,
                excel_ets_forecast=excel_ets_forecast,
                file_hash=file_hash,
            )

            yield _sse("progress", progress=98, message="Finalizing your forecast...")
            result = _build_result(prepared_df, model_result, metrics, decision, charts, forecast_horizon, freq, preference)
            audit_log(
                event_type="forecast_run",
                component="forecast_router",
                session_id=session_id,
                notes=result["forecast_bias"],
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
            yield _sse("complete", **result)

        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
            audit_log(
                event_type="error",
                component="forecast_router",
                session_id=session_id,
                notes=detail.get("message", str(e.detail)),
                error_code=detail.get("error_code"),
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
            yield _sse("error", **detail)
        except Exception as e:
            audit_log(
                event_type="error",
                component="forecast_router",
                session_id=session_id,
                notes=str(e),
                error_code="INTERNAL_ERROR",
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
            yield _sse("error", message=str(e), error_code="INTERNAL_ERROR")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/export/pdf")
async def export_pdf(http_request: Request, request: PDFExportRequest):
    t0 = time.perf_counter()
    session_id = getattr(http_request.state, "session_id", None)
    pdf_bytes = generate_pdf(
        selected_model=request.selected_model,
        mae_value=request.mae_value,
        forecast_horizon=request.forecast_horizon,
        summary1=request.summary1,
        summary2=request.summary2,
        chart1_base64=request.chart1_base64,
        chart2_base64=request.chart2_base64,
        metrics=request.metrics,
        forecast_bias=request.forecast_bias,
        data_processing_ms=request.data_processing_ms,
        prediction_generation_ms=request.prediction_generation_ms,
    )

    filename = f"MarketPulse_{datetime.now().strftime('%d%m%Y')}_V{APP_VERSION}_Report.pdf"
    audit_log(
        event_type="report_download_pdf",
        component="forecast_router",
        session_id=session_id,
        report_type="pdf",
        generated_filename=filename,
        duration_ms=round((time.perf_counter() - t0) * 1000, 1),
    )

    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/export/excel")
async def export_excel(http_request: Request, request: ExcelExportRequest):
    t0 = time.perf_counter()
    session_id = getattr(http_request.state, "session_id", None)
    excel_bytes = generate_excel(
        selected_model=request.selected_model,
        historical_data=request.historical_data,
        forecast_data=request.forecast_data,
        frequency=request.frequency,
        forecast_bias=request.forecast_bias,
    )

    filename = f"MarketPulse_{datetime.now().strftime('%d%m%Y')}_V{APP_VERSION}_Report.xlsx"
    audit_log(
        event_type="report_download_excel",
        component="forecast_router",
        session_id=session_id,
        report_type="excel",
        generated_filename=filename,
        duration_ms=round((time.perf_counter() - t0) * 1000, 1),
    )

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
