from pydantic import BaseModel
from typing import Literal


class ForecastRequest(BaseModel):
    date_column: str
    target_column: str
    preference: Literal["conservative", "capacity-buffered"]


class PDFExportRequest(BaseModel):
    selected_model: str
    mae_value: float
    forecast_horizon: int
    summary1: str
    summary2: str
    chart1_base64: str
    chart2_base64: str
    forecast_data: list[dict]
    metrics: dict
    forecast_bias: str = "Forecast"
    data_processing_ms: float | None = None
    prediction_generation_ms: float | None = None


class ExcelExportRequest(BaseModel):
    selected_model: str
    forecast_data: list[dict]
    historical_data: list[dict]
    frequency: str
    forecast_bias: str = "Forecast"
    comparison_forecasts: dict[str, list[float]] | None = None


class IndependentValidationRequest(BaseModel):
    historical_data: list[dict]
    forecast_data: list[dict]
    comparison_forecasts: dict[str, list[float]]
    frequency: str
    metrics: dict[str, dict]
    selected_model: str = "AutoETS"


class ManualValidationRequest(BaseModel):
    historical_data: list[dict]
    forecast_data: list[dict]
    comparison_forecasts: dict[str, list[float]]
    frequency: str
    model_params: dict
