"use client";

import type { ForecastResponse } from "@/lib/api";

interface ForecastResultsProps {
  data: ForecastResponse;
  displayModel: (name: string) => string;
  timingMs?: {
    dataProcessing: number | null;
    predictionGeneration: number | null;
  };
}

function formatTime(ms: number): string {
  if (ms >= 60_000) {
    const mins = ms / 60_000;
    return `${mins.toFixed(1)} mins`;
  }
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(1)} secs`;
  }
  return `${ms} ms`;
}

export default function ForecastResults({ data, displayModel, timingMs }: ForecastResultsProps) {
  const modelDisplay = displayModel(data.selected_model);

  return (
    <div className="space-y-8">
      {/* Metrics bar */}
      <div className="grid grid-cols-3 gap-4">
        <MetricCard label="Selected Model" value={modelDisplay} />
        <MetricCard
          label="Model Accuracy"
          value={`${data.mae_value.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })} pts (~${data.metrics[data.selected_model]?.smape.toFixed(1) ?? "?"}%)`}
        />
        <MetricCard label="Forecast Window" value={`${data.forecast_horizon} periods`} />
      </div>

      {/* Timing metrics */}
      {timingMs && (timingMs.dataProcessing != null || timingMs.predictionGeneration != null) && (
        <div className="grid grid-cols-3 gap-4">
          <MetricCard
            label="Preparing Data"
            value={timingMs.dataProcessing != null ? formatTime(timingMs.dataProcessing) : "\u2014"}
          />
          <MetricCard
            label="Generating Forecast"
            value={timingMs.predictionGeneration != null ? formatTime(timingMs.predictionGeneration) : "\u2014"}
          />
          <MetricCard
            label="Complete Flow"
            value={
              timingMs.dataProcessing != null && timingMs.predictionGeneration != null
                ? formatTime(timingMs.dataProcessing + timingMs.predictionGeneration)
                : "\u2014"
            }
          />
        </div>
      )}

      {/* Graph 1: Selected Model */}
      <div className="border border-white/10 rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-white/5">
          <h3 className="text-lg font-semibold text-white tracking-tight">
            Forecast &mdash; {modelDisplay}
          </h3>
        </div>
        <div className="p-4">
          <img
            src={`data:image/png;base64,${data.chart1_base64}`}
            alt="Selected model forecast"
            className="w-full rounded-lg"
          />
          <p className="text-sm text-white mt-4 leading-relaxed px-2">
            {data.summary1}
          </p>
        </div>
      </div>

      {/* Graph 2: Model Comparison */}
      <div className="border border-white/10 rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-white/5">
          <h3 className="text-lg font-semibold text-white tracking-tight">
            Model Comparison
          </h3>
        </div>
        <div className="p-4">
          <img
            src={`data:image/png;base64,${data.chart2_base64}`}
            alt="Model comparison"
            className="w-full rounded-lg"
          />
          <p className="text-sm text-white mt-4 leading-relaxed px-2">
            {data.summary2}
          </p>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-white/10 rounded-xl px-5 py-4 bg-black">
      <p className="text-xs text-white uppercase tracking-wider font-medium">{label}</p>
      <p className="text-xl font-semibold text-white mt-1">{value}</p>
    </div>
  );
}
