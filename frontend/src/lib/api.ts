const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class AppError extends Error {
  constructor(message: string, public errorCode?: string) {
    super(message);
  }
}

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
  historical_data: { date: string; value: number }[];
  frequency: string;
  metrics: Record<string, { mae: number; smape: number; mfe: number }>;
}

function extractError(detail: unknown, fallback: string): AppError {
  if (typeof detail === "object" && detail !== null) {
    const d = detail as Record<string, string>;
    return new AppError(d.message || fallback, d.error_code);
  }
  return new AppError(typeof detail === "string" ? detail : fallback);
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
    throw extractError(error.detail, "Upload failed");
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

  const controller = new AbortController();
  // Render free tier has ~30s hard limit; 90s is a client-side safety net
  const timeoutId = setTimeout(() => controller.abort(), 90_000);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/forecast`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new AppError("Request timed out. The dataset may be too large — try fewer rows or coarser time granularity.");
    }
    throw err;
  }
  clearTimeout(timeoutId);

  if (!res.ok) {
    const error = await res.json();
    throw extractError(error.detail, "Forecast failed");
  }

  return res.json();
}

export async function runForecastStream(
  file: File,
  dateColumn: string,
  targetColumn: string,
  preference: string,
  onProgress: (progress: number, message: string) => void,
): Promise<ForecastResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("date_column", dateColumn);
  formData.append("target_column", targetColumn);
  formData.append("preference", preference);

  const controller = new AbortController();
  // Render free tier has ~30s hard limit; 90s is a client-side safety net
  const timeoutId = setTimeout(() => controller.abort(), 90_000);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/forecast/stream`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new AppError("Request timed out. The dataset may be too large — try fewer rows or coarser time granularity.");
    }
    throw err;
  }
  clearTimeout(timeoutId);

  if (!res.body) {
    throw new AppError("Stream not supported by browser", "STREAM_ERROR");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const events = buffer.split("\n\n");
    buffer = events.pop()!;

    for (const raw of events) {
      const eventMatch = raw.match(/^event: (.+)$/m);
      const dataMatch = raw.match(/^data: (.+)$/m);
      if (!eventMatch || !dataMatch) continue;

      const type = eventMatch[1];
      const data = JSON.parse(dataMatch[1]);

      if (type === "progress") {
        onProgress(data.progress, data.message);
      } else if (type === "complete") {
        return data as ForecastResponse;
      } else if (type === "error") {
        throw new AppError(data.message || "Forecast failed", data.error_code);
      }
    }
  }

  throw new AppError("Stream ended without result", "STREAM_ERROR");
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

export async function exportExcel(data: ForecastResponse): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/export/excel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      selected_model: data.selected_model,
      forecast_data: data.forecast_data,
      historical_data: data.historical_data,
      frequency: data.frequency,
    }),
  });

  if (!res.ok) {
    throw new Error("Excel export failed");
  }

  return res.blob();
}
