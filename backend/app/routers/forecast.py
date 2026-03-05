import io

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response

from app.schemas.responses import ForecastResponse
from app.schemas.requests import PDFExportRequest
from app.services.file_parser import parse_upload
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


@router.post("/forecast", response_model=ForecastResponse)
async def run_forecast(
    file: UploadFile = File(...),
    date_column: str = Form(...),
    target_column: str = Form(...),
    preference: str = Form(...),
):
    with log_stage(logger, "full_pipeline"):
        # L1: Parse file
        df, file_hash = await parse_upload(file)

        # L3: Validate
        validate_data(df, date_column, target_column, file_hash=file_hash)

        # L4: Prepare
        prep_result = prepare_data(df, date_column, target_column, file_hash=file_hash)
        prepared_df = prep_result["df"]
        freq = prep_result["freq"]
        seasonal_period = prep_result["seasonal_period"]
        forecast_horizon = prep_result["forecast_horizon"]

        # L5: Model
        model_result = run_models(
            prepared_df, freq, seasonal_period, forecast_horizon, file_hash=file_hash
        )

        # L6: Evaluate
        metrics = evaluate_models(
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
            file_hash=file_hash,
        )

        # Build forecast data for frontend
        forecasts = model_result["forecasts"]
        sel_model = decision["selected_model"]
        pred_col = [c for c in forecasts.columns if sel_model in c and "lo" not in c and "hi" not in c][0]
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

        return ForecastResponse(
            selected_model=decision["selected_model"],
            mae_value=decision["selected_metrics"]["mae"],
            forecast_horizon=forecast_horizon,
            chart1_base64=charts["chart1_base64"],
            chart2_base64=charts["chart2_base64"],
            summary1=decision["summary1"],
            summary2=decision["summary2"],
            forecast_data=forecast_data,
            metrics={
                "AutoETS": metrics["AutoETS"],
                "AutoARIMA": metrics["AutoARIMA"],
                "Moving Average": metrics["Moving Average"],
                "Linear Trend": metrics["Linear Trend"],
            },
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
