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
