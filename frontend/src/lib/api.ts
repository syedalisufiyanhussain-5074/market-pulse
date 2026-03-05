const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface UploadResponse {
  date_columns: string[];
  numeric_columns: string[];
  preview: Record<string, unknown>[];
  file_hash: string;
  row_count: number;
}

export interface ForecastResponse {
  selected_model: string;
  mae_value: number;
  forecast_horizon: number;
  chart1_base64: string;
  chart2_base64: string;
  summary1: string;
  summary2: string;
  forecast_data: { date: string; value: number; lower_bound?: number; upper_bound?: number }[];
  metrics: Record<string, { mae: number; smape: number; mfe: number }>;
}

export async function uploadFile(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/api/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "Upload failed");
  }

  return res.json();
}

export async function runForecast(
  file: File,
  dateColumn: string,
  targetColumn: string,
  preference: string
): Promise<ForecastResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("date_column", dateColumn);
  formData.append("target_column", targetColumn);
  formData.append("preference", preference);

  const res = await fetch(`${API_BASE}/api/forecast`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "Forecast failed");
  }

  return res.json();
}

export async function exportPDF(data: ForecastResponse): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/export/pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      selected_model: data.selected_model,
      mae_value: data.mae_value,
      forecast_horizon: data.forecast_horizon,
      summary1: data.summary1,
      summary2: data.summary2,
      chart1_base64: data.chart1_base64,
      chart2_base64: data.chart2_base64,
      forecast_data: data.forecast_data,
      metrics: data.metrics,
    }),
  });

  if (!res.ok) {
    throw new Error("PDF export failed");
  }

  return res.blob();
}
