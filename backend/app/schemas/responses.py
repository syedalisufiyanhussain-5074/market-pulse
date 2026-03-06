from pydantic import BaseModel


class UploadResponse(BaseModel):
    date_columns: list[str]
    numeric_columns: list[str]
    preview: list[dict]
    file_hash: str
    row_count: int


class ForecastResponse(BaseModel):
    selected_model: str
    mae_value: float
    forecast_horizon: int
    chart1_base64: str
    chart2_base64: str
    summary1: str
    summary2: str
    forecast_data: list[dict]
    historical_data: list[dict]
    frequency: str
    metrics: dict
