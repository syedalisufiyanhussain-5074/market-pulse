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
from app.schemas.requests import PDFExportRequest, ExcelExportRequest, IndependentValidationRequest, ManualValidationRequest, ValidationExportRequest
from app.services.excel_export import generate_excel
from app.services.file_parser import parse_upload, parse_from_bytes
from app.services.validator import validate_data
from app.services.data_prep import prepare_data
from app.services.modeling import run_models, fit_ets, fit_arima, build_forecast_df, _has_seasonality
from app.services.evaluation import evaluate_models, compute_forecast_deviation_pct
from app.services.decision import select_best_model, update_comparison_summary
from app.services.visualization import generate_charts
from app.services.pdf_export import generate_pdf
from app.utils.logger import get_logger, log_stage, audit_log
from app.utils import file_cache

logger = get_logger("forecast_router")
router = APIRouter(prefix="/api", tags=["forecast"])

# Centralized frequency → seasonal period mapping
FREQ_SP_MAP = {"D": 7, "W": 52, "MS": 12, "M": 12, "QS": 4, "Q": 4, "YS": None, "Y": None}


def _sanitize(value):
    """Replace NaN/Inf with None for JSON-safe serialization."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _build_result(prepared_df, model_result, metrics, decision, charts, forecast_horizon, freq, preference, metrics_source="cross_validation", excel_ets_forecast=None, model_params=None, file_hash=""):
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

    # Build comparison_forecasts: all 4 models' forecast arrays
    import numpy as np
    comparison_forecasts = {}
    for model_name in ["AutoETS", "AutoARIMA"]:
        col = [c for c in forecasts.columns if model_name in c and "lo" not in c and "hi" not in c]
        if col:
            vals = forecasts[col[0]].values
            comparison_forecasts[model_name] = [_safe_round(v) for v in vals]

    # Moving Average: flat line = mean of last `window` historical values
    y_values = prepared_df["y"].values
    window = min(forecast_horizon, len(y_values) - forecast_horizon)
    if window > 0:
        ma_val = float(np.mean(y_values[-window:]))
    else:
        ma_val = float(np.mean(y_values))
    comparison_forecasts["Moving Average (Excel)"] = [round(ma_val, 2)] * forecast_horizon

    # ETS (Excel): use the pre-computed forecast array
    if excel_ets_forecast is not None:
        comparison_forecasts["ETS (Excel)"] = [_safe_round(v) for v in excel_ets_forecast[:forecast_horizon]]

    # Validate alignment: all arrays must have same length
    lengths = {k: len(v) for k, v in comparison_forecasts.items()}
    if len(set(lengths.values())) > 1:
        logger.warning(f"Comparison forecast length mismatch: {lengths}")
        comparison_forecasts = None  # fail gracefully

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
        "metrics_source": metrics_source,
        "comparison_forecasts": comparison_forecasts,
        "model_params": model_params,
        "file_hash": file_hash,
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

            sp_val = seasonal_period if seasonal_period and seasonal_period > 1 else None
            data_has_seasonality = _has_seasonality(prepared_df["y"].values, sp_val) if sp_val else False
            decision = select_best_model(
                metrics, preference, file_hash=file_hash,
                model_params=model_result.get("model_params"),
                seasonal_period=seasonal_period,
                has_seasonality=data_has_seasonality,
            )

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
                freq=freq,
            )

            metrics_source = model_result.get("metrics_source", "cross_validation")
            result = _build_result(prepared_df, model_result, metrics, decision, charts, forecast_horizon, freq, preference, metrics_source=metrics_source, excel_ets_forecast=excel_ets_forecast, model_params=model_result.get("model_params"), file_hash=file_hash)
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
            sp_val = seasonal_period if seasonal_period and seasonal_period > 1 else None
            data_has_seasonality = _has_seasonality(prepared_df["y"].values, sp_val) if sp_val else False
            decision = select_best_model(
                metrics, preference, file_hash=file_hash,
                model_params=model_result.get("model_params"),
                seasonal_period=seasonal_period,
                has_seasonality=data_has_seasonality,
            )

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
                freq=freq,
            )

            yield _sse("progress", progress=98, message="Finalizing your forecast...")
            metrics_source = model_result.get("metrics_source", "cross_validation")
            result = _build_result(prepared_df, model_result, metrics, decision, charts, forecast_horizon, freq, preference, metrics_source=metrics_source, excel_ets_forecast=excel_ets_forecast, model_params=model_result.get("model_params"), file_hash=file_hash)

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
        comparison_forecasts=request.comparison_forecasts,
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


@router.post("/export/independent-validation")
async def export_independent_validation(http_request: Request, request: IndependentValidationRequest):
    """Run R-inspired models and generate Independent Validation Excel."""
    import traceback
    import numpy as np
    from app.services.independent_validation import (
        run_independent_models, compute_variance, compute_agreement_score,
        compute_independent_metrics, compute_python_metrics,
    )
    from app.services.independent_validation_export import generate_independent_validation_excel
    t0 = time.perf_counter()
    session_id = getattr(http_request.state, "session_id", None)

    try:
        # Reconstruct y array from historical data
        y = np.array([entry["value"] for entry in request.historical_data], dtype=float)
        forecast_horizon = len(request.forecast_data)

        # Strict alignment check on Python forecasts
        py_forecasts = request.comparison_forecasts
        py_lengths = {k: len(v) for k, v in py_forecasts.items()}
        if len(set(py_lengths.values())) > 1 or any(l != forecast_horizon for l in py_lengths.values()):
            raise HTTPException(
                status_code=422,
                detail={"message": f"Python forecast arrays have mismatched lengths: {py_lengths}. Expected {forecast_horizon}.", "error_code": "ALIGNMENT_ERROR"},
            )

        # Derive seasonal period from frequency
        _freq_sp = {"D": 7, "W": 52, "MS": 12, "M": 12, "QS": 4, "Q": 4, "YS": None, "Y": None}
        sp = _freq_sp.get(request.frequency)

        # Try IV cache first (populated by background thread after forecast)
        iv_cache_key = f"iv_{request.file_hash}_{request.frequency}_{sp}_{forecast_horizon}"
        cached = file_cache.get_iv(iv_cache_key)

        if cached:
            logger.info(f"IV cache HIT (key={iv_cache_key})", extra={"file_hash": request.file_hash})
            ind_forecasts = cached["ind_forecasts"]
            status_overrides = cached["status_overrides"]
            variance_data = cached["var_data"]
            ind_metrics = cached["ind_metrics"]
            py_metrics = cached["py_metrics"]
            score_result = cached["agreement_score"]
            agreement_score = score_result["score"]
            validation_warnings = score_result["warnings"]
        else:
            logger.info(f"IV cache MISS (key={iv_cache_key}) — computing from scratch", extra={"file_hash": request.file_hash})

            # Run independent models (returns forecasts + status overrides)
            ind_forecasts, status_overrides = run_independent_models(y, sp, forecast_horizon)

            # Strict alignment check on independent forecasts
            ind_lengths = {k: len(v) for k, v in ind_forecasts.items()}
            if any(l != forecast_horizon for l in ind_lengths.values()):
                raise HTTPException(
                    status_code=500,
                    detail={"message": f"Independent forecast arrays have mismatched lengths: {ind_lengths}. Expected {forecast_horizon}.", "error_code": "ALIGNMENT_ERROR"},
                )

            # Compute variance and metrics (pass status overrides for underfit marking)
            variance_data = compute_variance(ind_forecasts, py_forecasts, status_overrides)

            # Detect if data was downsampled by checking date gaps vs declared frequency
            observation_count = len(y)
            _freq_expected_days = {"D": 1, "W": 7, "MS": 30, "M": 30, "QS": 91, "Q": 91, "YS": 365, "Y": 365}
            was_downsampled = False
            if len(request.historical_data) >= 2:
                from datetime import datetime as _dt
                d0 = _dt.fromisoformat(request.historical_data[0]["date"])
                d1 = _dt.fromisoformat(request.historical_data[1]["date"])
                actual_gap_days = (d1 - d0).days
                expected_days = _freq_expected_days.get(request.frequency, actual_gap_days)
                was_downsampled = actual_gap_days > expected_days * 2

            score_result = compute_agreement_score(
                variance_data,
                observation_count=observation_count,
                was_downsampled=was_downsampled,
            )
            agreement_score = score_result["score"]
            validation_warnings = score_result["warnings"]

            ind_metrics = compute_independent_metrics(y, forecast_horizon, ind_forecasts)
            py_metrics = compute_python_metrics(y, forecast_horizon, py_forecasts)

            # Populate cache for next download
            file_cache.put_iv(iv_cache_key, {
                "ind_forecasts": ind_forecasts, "status_overrides": status_overrides,
                "var_data": variance_data, "ind_metrics": ind_metrics,
                "py_metrics": py_metrics, "agreement_score": score_result,
            })

        excel_bytes = generate_independent_validation_excel(
            historical_data=request.historical_data,
            forecast_data=request.forecast_data,
            ind_forecasts=ind_forecasts,
            py_forecasts=py_forecasts,
            variance_data=variance_data,
            ind_metrics=ind_metrics,
            py_metrics=py_metrics,
            agreement_score=agreement_score,
            frequency=request.frequency,
            selected_model=request.selected_model,
            validation_warnings=validation_warnings,
        )

        filename = f"MarketPulse_{datetime.now().strftime('%d%m%Y')}_V{APP_VERSION}_IndependentValidation.xlsx"
        audit_log(
            event_type="report_download_independent_validation",
            component="forecast_router",
            session_id=session_id,
            report_type="independent_validation",
            generated_filename=filename,
            notes=f"agreement_score={agreement_score}",
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )

        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Independent validation export failed: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail={"message": f"Independent validation failed: {e}", "error_code": "VALIDATION_ERROR"},
        )


@router.post("/export/manual-validation")
async def export_manual_validation(http_request: Request, request: ManualValidationRequest):
    """Generate Manual Validation Excel with parameters and empty cells for user."""
    from app.services.manual_validation_export import generate_manual_validation_excel

    t0 = time.perf_counter()
    session_id = getattr(http_request.state, "session_id", None)

    excel_bytes = generate_manual_validation_excel(
        historical_data=request.historical_data,
        forecast_data=request.forecast_data,
        comparison_forecasts=request.comparison_forecasts,
        frequency=request.frequency,
        model_params=request.model_params,
    )

    filename = f"MarketPulse_{datetime.now().strftime('%d%m%Y')}_V{APP_VERSION}_ManualValidation.xlsx"
    audit_log(
        event_type="report_download_manual_validation",
        component="forecast_router",
        session_id=session_id,
        report_type="manual_validation",
        generated_filename=filename,
        duration_ms=round((time.perf_counter() - t0) * 1000, 1),
    )

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/export/validation")
async def export_validation(http_request: Request, request: ValidationExportRequest):
    """Generate IV + MV validation reports as a single ZIP."""
    import zipfile
    import numpy as np
    from app.services.independent_validation import (
        run_independent_models, compute_variance, compute_agreement_score,
        compute_independent_metrics, compute_python_metrics,
    )
    from app.services.independent_validation_export import generate_independent_validation_excel
    from app.services.manual_validation_export import generate_manual_validation_excel

    t0 = time.perf_counter()
    session_id = getattr(http_request.state, "session_id", None)

    try:
        y = np.array([e["value"] for e in request.historical_data], dtype=float)
        forecast_horizon = len(request.forecast_data)
        sp = FREQ_SP_MAP.get(request.frequency)
        py_forecasts = request.comparison_forecasts

        # --- Independent Validation (wrapped — ZIP still returns MV if IV fails) ---
        iv_bytes = None
        iv_error = None
        agreement_notes = ""
        try:
            t_iv = time.perf_counter()

            use_cache = bool(request.file_hash)
            iv_cache_key = f"iv_{request.file_hash}_{request.frequency}_{sp}_{forecast_horizon}" if use_cache else ""
            if not use_cache:
                logger.warning("file_hash missing — IV cache disabled for this request")

            cached = file_cache.get_iv(iv_cache_key) if use_cache else None
            if cached:
                logger.info(f"IV cache HIT (key={iv_cache_key})")
                ind_forecasts = cached["ind_forecasts"]
                status_overrides = cached["status_overrides"]
                variance_data = cached["var_data"]
                ind_metrics = cached["ind_metrics"]
                py_metrics = cached["py_metrics"]
                score_result = cached["agreement_score"]
            else:
                if use_cache:
                    logger.info(f"IV cache MISS (key={iv_cache_key}) — computing")
                ind_forecasts, status_overrides = run_independent_models(y, sp, forecast_horizon)
                variance_data = compute_variance(ind_forecasts, py_forecasts, status_overrides)
                observation_count = len(y)
                was_downsampled = False
                if len(request.historical_data) >= 2:
                    from datetime import datetime as _dt
                    d0 = _dt.fromisoformat(request.historical_data[0]["date"])
                    d1 = _dt.fromisoformat(request.historical_data[1]["date"])
                    _freq_days = {"D": 1, "W": 7, "MS": 30, "QS": 91, "YS": 365}
                    was_downsampled = (d1 - d0).days > _freq_days.get(request.frequency, 999) * 2
                score_result = compute_agreement_score(variance_data, observation_count=observation_count, was_downsampled=was_downsampled)
                ind_metrics = compute_independent_metrics(y, forecast_horizon, ind_forecasts)
                py_metrics = compute_python_metrics(y, forecast_horizon, py_forecasts)
                if use_cache:
                    file_cache.put_iv(iv_cache_key, {
                        "ind_forecasts": ind_forecasts, "status_overrides": status_overrides,
                        "var_data": variance_data, "ind_metrics": ind_metrics,
                        "py_metrics": py_metrics, "agreement_score": score_result,
                    })

            iv_bytes = generate_independent_validation_excel(
                request.historical_data, request.forecast_data,
                ind_forecasts, py_forecasts, variance_data,
                ind_metrics, py_metrics, score_result["score"],
                request.frequency, request.selected_model, score_result["warnings"],
            )
            agreement_notes = f"agreement_score={score_result['score']}"
            logger.info(f"IV generated in {(time.perf_counter() - t_iv) * 1000:.0f}ms")
        except Exception as e:
            iv_error = str(e)
            logger.error(f"IV generation failed: {e}")

        # --- Manual Validation ---
        t_mv = time.perf_counter()
        mv_bytes = generate_manual_validation_excel(
            request.historical_data, request.forecast_data,
            request.comparison_forecasts, request.frequency, request.model_params,
        )
        logger.info(f"MV generated in {(time.perf_counter() - t_mv) * 1000:.0f}ms")

        # --- ZIP (always includes MV; includes IV if successful) ---
        t_zip = time.perf_counter()
        date_str = datetime.now().strftime("%d%m%Y")
        base = f"MarketPulse_{date_str}_V{APP_VERSION}"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            if iv_bytes:
                zf.writestr("Independent_Validation_Report.xlsx", iv_bytes)
            else:
                zf.writestr(
                    "Independent_Validation_ERROR.txt",
                    f"Independent Validation report could not be generated.\nError: {iv_error}\n\nPlease try again or contact support.",
                )
            zf.writestr("Manual_Validation_Report.xlsx", mv_bytes)
        zip_bytes = buf.getvalue()
        logger.info(f"ZIP created in {(time.perf_counter() - t_zip) * 1000:.0f}ms ({len(zip_bytes)} bytes)")

        audit_log(
            event_type="report_download_validation",
            component="forecast_router",
            session_id=session_id,
            report_type="validation_zip",
            notes=agreement_notes or f"iv_failed={iv_error}",
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )

        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={base}_ValidationReports.zip"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Validation export failed: {e}")
        raise HTTPException(status_code=500, detail={"message": "Failed to generate validation reports.", "error_code": "EXPORT_ERROR"})


# ---------------------------------------------------------------------------
# Streaming validation export (SSE progress + two-phase ZIP download)
# ---------------------------------------------------------------------------

@router.post("/export/validation/stream")
async def export_validation_stream(http_request: Request, request: ValidationExportRequest):
    """Stream progress for IV + MV validation report generation."""
    import zipfile
    import uuid
    import numpy as np
    from app.services.independent_validation import (
        run_independent_models, compute_variance, compute_agreement_score,
        compute_independent_metrics, compute_python_metrics,
    )
    from app.services.independent_validation_export import generate_independent_validation_excel
    from app.services.manual_validation_export import generate_manual_validation_excel

    session_id = getattr(http_request.state, "session_id", None)

    def generate():
        t0 = time.perf_counter()
        try:
            yield _sse("progress", progress=10, message="Preparing validation data...")

            y = np.array([e["value"] for e in request.historical_data], dtype=float)
            forecast_horizon = len(request.forecast_data)
            sp = FREQ_SP_MAP.get(request.frequency)
            py_forecasts = request.comparison_forecasts

            # --- Independent Validation ---
            iv_bytes = None
            iv_error = None
            agreement_notes = ""

            try:
                use_cache = bool(request.file_hash)
                iv_cache_key = f"iv_{request.file_hash}_{request.frequency}_{sp}_{forecast_horizon}" if use_cache else ""
                cached = file_cache.get_iv(iv_cache_key) if use_cache else None

                if cached:
                    yield _sse("progress", progress=30, message="Loading cached validation models...")
                    ind_forecasts = cached["ind_forecasts"]
                    status_overrides = cached["status_overrides"]
                    variance_data = cached["var_data"]
                    ind_metrics = cached["ind_metrics"]
                    py_metrics = cached["py_metrics"]
                    score_result = cached["agreement_score"]
                    yield _sse("progress", progress=65, message="Computing variance analysis...")
                else:
                    yield _sse("progress", progress=30, message="Running independent validation models...")
                    ind_result = None
                    for item in _run_with_heartbeats(lambda: run_independent_models(y, sp, forecast_horizon)):
                        if isinstance(item, str):
                            yield item  # heartbeat
                        else:
                            ind_result = item

                    ind_forecasts, status_overrides = ind_result
                    yield _sse("progress", progress=65, message="Computing variance analysis...")
                    variance_data = compute_variance(ind_forecasts, py_forecasts, status_overrides)

                    observation_count = len(y)
                    was_downsampled = False
                    if len(request.historical_data) >= 2:
                        from datetime import datetime as _dt
                        d0 = _dt.fromisoformat(request.historical_data[0]["date"])
                        d1 = _dt.fromisoformat(request.historical_data[1]["date"])
                        _freq_days = {"D": 1, "W": 7, "MS": 30, "QS": 91, "YS": 365}
                        was_downsampled = (d1 - d0).days > _freq_days.get(request.frequency, 999) * 2

                    score_result = compute_agreement_score(
                        variance_data, observation_count=observation_count, was_downsampled=was_downsampled,
                    )
                    ind_metrics = compute_independent_metrics(y, forecast_horizon, ind_forecasts)
                    py_metrics = compute_python_metrics(y, forecast_horizon, py_forecasts)

                    if use_cache:
                        file_cache.put_iv(iv_cache_key, {
                            "ind_forecasts": ind_forecasts, "status_overrides": status_overrides,
                            "var_data": variance_data, "ind_metrics": ind_metrics,
                            "py_metrics": py_metrics, "agreement_score": score_result,
                        })

                yield _sse("progress", progress=75, message="Generating Independent Validation report...")
                iv_result = None
                for item in _run_with_heartbeats(lambda: generate_independent_validation_excel(
                    request.historical_data, request.forecast_data,
                    ind_forecasts, py_forecasts, variance_data,
                    ind_metrics, py_metrics, score_result["score"],
                    request.frequency, request.selected_model, score_result.get("warnings", []),
                )):
                    if isinstance(item, str):
                        yield item
                    else:
                        iv_result = item
                iv_bytes = iv_result
                agreement_notes = f"agreement_score={score_result['score']}"

            except Exception as e:
                iv_error = str(e)
                logger.error(f"IV generation failed in stream: {e}")

            # --- Manual Validation ---
            yield _sse("progress", progress=85, message="Generating Manual Validation report...")
            mv_bytes = None
            for item in _run_with_heartbeats(lambda: generate_manual_validation_excel(
                request.historical_data, request.forecast_data,
                request.comparison_forecasts, request.frequency, request.model_params,
            )):
                if isinstance(item, str):
                    yield item
                else:
                    mv_bytes = item

            # --- ZIP ---
            yield _sse("progress", progress=95, message="Packaging reports...")
            date_str = datetime.now().strftime("%d%m%Y")
            base = f"MarketPulse_{date_str}_V{APP_VERSION}"
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                if iv_bytes:
                    zf.writestr("Independent_Validation_Report.xlsx", iv_bytes)
                else:
                    zf.writestr(
                        "Independent_Validation_ERROR.txt",
                        f"Independent Validation report could not be generated.\nError: {iv_error}\n\nPlease try again or contact support.",
                    )
                zf.writestr("Manual_Validation_Report.xlsx", mv_bytes)
            zip_bytes = buf.getvalue()

            cache_key = str(uuid.uuid4())
            file_cache.put_zip(cache_key, zip_bytes)

            filename = f"{base}_ValidationReports.zip"
            yield _sse("progress", progress=100, message="Reports ready!")
            yield _sse("complete", cache_key=cache_key, filename=filename)

            audit_log(
                event_type="report_download_validation_stream",
                component="forecast_router",
                session_id=session_id,
                report_type="validation_zip",
                notes=agreement_notes or f"iv_failed={iv_error}",
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )

        except Exception as e:
            logger.error(f"Validation stream failed: {e}")
            yield _sse("error", message=str(e), error_code="VALIDATION_STREAM_ERROR")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/export/validation/download/{cache_key}")
async def download_validation_zip(cache_key: str):
    """Download a previously generated validation ZIP by cache key."""
    zip_bytes = file_cache.get_zip(cache_key)
    if not zip_bytes:
        raise HTTPException(
            status_code=404,
            detail={"message": "Report expired or not found. Please generate again.", "error_code": "CACHE_MISS"},
        )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=ValidationReports.zip"},
    )
