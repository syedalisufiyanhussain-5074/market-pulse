const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function getSessionId(): string {
  const KEY = "mp_session_id";
  let id = sessionStorage.getItem(KEY);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(KEY, id);
  }
  return id;
}

async function ensureServerAwake(): Promise<void> {
  try {
    await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(150_000) });
  } catch { /* server may still be starting, proceed anyway */ }
}

export async function fetchAppVersion(): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(5_000) });
    if (res.ok) {
      const data = await res.json();
      return data.version ?? "1.3";
    }
  } catch { /* fallback */ }
  return "1.3";
}

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
  forecast_bias: string;
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
  await ensureServerAwake();

  const formData = new FormData();
  formData.append("file", file);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 180_000);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/upload`, {
      method: "POST",
      headers: { "X-Session-ID": getSessionId() },
      body: formData,
      signal: controller.signal,
    });
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new AppError("The server is waking up — this can take up to a minute on the first visit. Please try again.");
    }
    throw new AppError("Unable to reach the server. Please check your connection and try again.");
  }
  clearTimeout(timeoutId);

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
  // 120s absolute timeout for non-streaming endpoint
  const timeoutId = setTimeout(() => controller.abort(), 120_000);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/forecast`, {
      method: "POST",
      headers: { "X-Session-ID": getSessionId() },
      body: formData,
      signal: controller.signal,
    });
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new AppError("Request timed out. The dataset may be too large — try fewer rows or coarser time granularity.");
    }
    throw new AppError("Unable to reach the server. Please check your connection and try again.");
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

  // Wake server before heavy request (absorbs cold start)
  onProgress(2, "Waking up the server...");
  await ensureServerAwake();

  // Phase 1: Connection timeout (180s)
  const connectTimeout = setTimeout(() => controller.abort(), 180_000);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/forecast/stream`, {
      method: "POST",
      headers: { "X-Session-ID": getSessionId() },
      body: formData,
      signal: controller.signal,
    });
  } catch (err: unknown) {
    clearTimeout(connectTimeout);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new AppError("The server is waking up — this can take up to a minute on the first visit. Please try again.");
    }
    throw new AppError("Unable to reach the server. Please check your connection and try again.");
  }
  clearTimeout(connectTimeout);

  if (!res.body) {
    throw new AppError("Your browser doesn't support live updates. Please try Chrome, Edge, or Firefox.", "STREAM_ERROR");
  }

  // Phase 2: Idle timeout (45s) — reset on every chunk received
  const IDLE_MS = 45_000;
  let idleTimer = setTimeout(() => controller.abort(), IDLE_MS);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      let readResult: ReadableStreamReadResult<Uint8Array>;
      try {
        readResult = await reader.read();
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") {
          throw new AppError("The server took too long to respond. Please try again — it usually works on the second attempt.");
        }
        throw new AppError("Connection interrupted. Please try again.");
      }

      const { done, value } = readResult;
      if (done) break;

      // Reset idle timer on every chunk
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => controller.abort(), IDLE_MS);

      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";

      for (const raw of parts) {
        const eventMatch = raw.match(/^event: (.+)$/m);
        const dataMatch = raw.match(/^data: (.+)$/m);

        // Heartbeat events have no data — just reset idle timer (already done above)
        if (!eventMatch || !dataMatch) continue;

        const type = eventMatch[1];
        if (type === "heartbeat") continue;

        const data = JSON.parse(dataMatch[1]);

        if (type === "progress") {
          onProgress(data.progress, data.message);
        } else if (type === "complete") {
          clearTimeout(idleTimer);
          return data as ForecastResponse;
        } else if (type === "error") {
          clearTimeout(idleTimer);
          throw new AppError(data.message || "Forecast failed", data.error_code);
        }
      }
    }
  } finally {
    clearTimeout(idleTimer);
  }

  throw new AppError("Something went wrong — no results were received. Please try again.", "STREAM_ERROR");
}

export async function exportPDF(
  data: ForecastResponse,
  timingMs?: { dataProcessing: number | null; predictionGeneration: number | null },
): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/export/pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Session-ID": getSessionId() },
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
      forecast_bias: data.forecast_bias,
      data_processing_ms: timingMs?.dataProcessing ?? null,
      prediction_generation_ms: timingMs?.predictionGeneration ?? null,
    }),
  });

  if (!res.ok) {
    throw new Error("Unable to generate PDF. Please try again.");
  }

  return res.blob();
}

export async function exportExcel(data: ForecastResponse): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/export/excel`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Session-ID": getSessionId() },
    body: JSON.stringify({
      selected_model: data.selected_model,
      forecast_data: data.forecast_data,
      historical_data: data.historical_data,
      frequency: data.frequency,
      forecast_bias: data.forecast_bias,
    }),
  });

  if (!res.ok) {
    throw new Error("Unable to generate Excel file. Please try again.");
  }

  return res.blob();
}
