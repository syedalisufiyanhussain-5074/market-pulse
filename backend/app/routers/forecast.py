import io
import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.schemas.responses import ForecastResponse
from app.schemas.requests import PDFExportRequest, ExcelExportRequest
from app.services.excel_export import generate_excel
from app.services.file_parser import parse_upload, parse_from_bytes
from app.services.validator import validate_data
from app.services.data_prep import prepare_data
from app.services.modeling import run_models
from app.services.evaluation import evaluate_models
from app.services.decision import select_best_model
from app.services.visualization import generate_charts
from app.services.pdf_export import generate_pdf
from app.utils.logger import get_logger, log_stage

logger = get_logger("forecast_router")
router = APIRouter(prefix="/api", tags=["forecast"])


def _build_result(prepared_df, model_result, metrics, decision, charts, forecast_horizon, freq):
    """Build the forecast result dict (shared by both endpoints)."""
    forecasts = model_result["forecasts"]
    sel_model = decision["selected_model"]
    pred_col_matches = [c for c in forecasts.columns if sel_model in c and "lo" not in c and "hi" not in c]
    if not pred_col_matches:
        raise HTTPException(status_code=500, detail={"message": "Internal error: forecast column not found", "error_code": "INTERNAL_ERROR"})
    pred_col = pred_col_matches[0]
    lo_col = [c for c in forecasts.columns if sel_model in c and "lo" in c]
    hi_col = [c for c in forecasts.columns if sel_model in c and "hi" in c]

    forecast_data = []
    for i, row in forecasts.iterrows():
        entry = {
            "date": row["ds"].isoformat(),
            "value": round(float(row[pred_col]), 2),
        }
        if lo_col:
            entry["lower_bound"] = round(float(row[lo_col[0]]), 2)
        if hi_col:
            entry["upper_bound"] = round(float(row[hi_col[0]]), 2)
        forecast_data.append(entry)

    historical_data = [
        {"date": row["ds"].isoformat(), "value": round(float(row["y"]), 2)}
        for _, row in prepared_df.iterrows()
    ]

    return {
        "selected_model": decision["selected_model"],
        "mae_value": decision["selected_metrics"]["mae"],
        "forecast_horizon": forecast_horizon,
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
    }


@router.post("/forecast", response_model=ForecastResponse)
async def run_forecast(
    file: UploadFile = File(...),
    date_column: str = Form(...),
    target_column: str = Form(...),
    preference: str = Form(...),
):
    with log_stage(logger, "prediction_generation"):
        # L1: Parse file
        df, file_hash = await parse_upload(file)

        # L3: Validate (returns pre-parsed columns)
        parsed = validate_data(df, date_column, target_column, file_hash=file_hash)

        # L4: Prepare (uses pre-parsed columns to avoid double parsing)
        prep_result = prepare_data(df, date_column, target_column, file_hash=file_hash, parsed_columns=parsed)
        prepared_df = prep_result["df"]
        freq = prep_result["freq"]
        seasonal_period = prep_result["seasonal_period"]
        forecast_horizon = prep_result["forecast_horizon"]

        # L5: Model
        model_result = run_models(
            prepared_df, freq, seasonal_period, forecast_horizon, file_hash=file_hash
        )

        # L6: Evaluate
        metrics, excel_ets_forecast = evaluate_models(
            model_result["cv_results"],
            prepared_df,
            forecast_horizon,
            file_hash=file_hash,
        )

        # L7: Decide
        decision = select_best_model(metrics, preference, file_hash=file_hash)

        # L8: Visualize
        charts = generate_charts(
            historical_df=prepared_df,
            forecasts=model_result["forecasts"],
            selected_model=decision["selected_model"],
            alternative_model=decision["alternative_model"],
            forecast_horizon=forecast_horizon,
            excel_ets_forecast=excel_ets_forecast,
            file_hash=file_hash,
        )

        result = _build_result(prepared_df, model_result, metrics, decision, charts, forecast_horizon, freq)
        return ForecastResponse(**result)


def _sse(event: str, **data) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/forecast/stream")
async def run_forecast_stream(
    file: UploadFile = File(...),
    date_column: str = Form(...),
    target_column: str = Form(...),
    preference: str = Form(...),
):
    # Read file bytes in async context before entering sync generator
    contents = await file.read()
    filename = file.filename or ""

    def generate():
        try:
            yield _sse("progress", progress=5, message="Reading file...")
            df, file_hash = parse_from_bytes(contents, filename)

            yield _sse("progress", progress=15, message="Validating data...")
            parsed = validate_data(df, date_column, target_column, file_hash=file_hash)

            yield _sse("progress", progress=25, message="Preparing data...")
            prep_result = prepare_data(df, date_column, target_column, file_hash=file_hash, parsed_columns=parsed)
            prepared_df = prep_result["df"]
            freq = prep_result["freq"]
            seasonal_period = prep_result["seasonal_period"]
            forecast_horizon = prep_result["forecast_horizon"]

            yield _sse("progress", progress=40, message="Running ETS model...")
            model_result = run_models(
                prepared_df, freq, seasonal_period, forecast_horizon, file_hash=file_hash
            )

            yield _sse("progress", progress=75, message="Evaluating models...")
            metrics, excel_ets_forecast = evaluate_models(
                model_result["cv_results"],
                prepared_df,
                forecast_horizon,
                file_hash=file_hash,
            )

            yield _sse("progress", progress=85, message="Selecting best model...")
            decision = select_best_model(metrics, preference, file_hash=file_hash)

            yield _sse("progress", progress=92, message="Generating charts...")
            charts = generate_charts(
                historical_df=prepared_df,
                forecasts=model_result["forecasts"],
                selected_model=decision["selected_model"],
                alternative_model=decision["alternative_model"],
                forecast_horizon=forecast_horizon,
                excel_ets_forecast=excel_ets_forecast,
                file_hash=file_hash,
            )

            yield _sse("progress", progress=98, message="Finalizing results...")
            result = _build_result(prepared_df, model_result, metrics, decision, charts, forecast_horizon, freq)
            yield _sse("complete", **result)

        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
            yield _sse("error", **detail)
        except Exception as e:
            yield _sse("error", message=str(e), error_code="INTERNAL_ERROR")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/export/pdf")
async def export_pdf(request: PDFExportRequest):
    pdf_bytes = generate_pdf(
        selected_model=request.selected_model,
        mae_value=request.mae_value,
        forecast_horizon=request.forecast_horizon,
        summary1=request.summary1,
        summary2=request.summary2,
        chart1_base64=request.chart1_base64,
        chart2_base64=request.chart2_base64,
    )

    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=market-pulse-report.pdf"},
    )


@router.post("/export/excel")
async def export_excel(request: ExcelExportRequest):
    excel_bytes = generate_excel(
        selected_model=request.selected_model,
        historical_data=request.historical_data,
        forecast_data=request.forecast_data,
        frequency=request.frequency,
    )

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=market-pulse-forecast.xlsx"},
    )
