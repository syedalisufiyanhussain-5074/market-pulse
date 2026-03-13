import io

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.schemas.responses import ForecastResponse
from app.schemas.requests import PDFExportRequest, ExcelExportRequest
from app.services.excel_export import generate_excel
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
    with log_stage(logger, "prediction_generation"):
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

        # Build forecast data for frontend
        forecasts = model_result["forecasts"]
        sel_model = decision["selected_model"]
        pred_col_matches = [c for c in forecasts.columns if sel_model in c and "lo" not in c and "hi" not in c]
        if not pred_col_matches:
            raise HTTPException(status_code=500, detail="Internal error: forecast column not found")
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

        # Build historical data for Excel export
        historical_data = [
            {"date": row["ds"].isoformat(), "value": round(float(row["y"]), 2)}
            for _, row in prepared_df.iterrows()
        ]

        return ForecastResponse(
            selected_model=decision["selected_model"],
            mae_value=decision["selected_metrics"]["mae"],
            forecast_horizon=forecast_horizon,
            chart1_base64=charts["chart1_base64"],
            chart2_base64=charts["chart2_base64"],
            summary1=decision["summary1"],
            summary2=decision["summary2"],
            forecast_data=forecast_data,
            historical_data=historical_data,
            frequency=freq,
            metrics={
                "AutoETS": metrics["AutoETS"],
                "AutoARIMA": metrics["AutoARIMA"],
                "Moving Average (Excel)": metrics["Moving Average (Excel)"],
                "ETS (Excel)": metrics["ETS (Excel)"],
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
