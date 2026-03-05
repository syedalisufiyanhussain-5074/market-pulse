"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ForecastResponse } from "@/lib/api";

interface ForecastResultsProps {
  data: ForecastResponse;
}

export default function ForecastResults({ data }: ForecastResultsProps) {
  return (
    <div className="space-y-8">
      {/* Metrics bar */}
      <div className="grid grid-cols-3 gap-4">
        <MetricCard label="Selected Model" value={data.selected_model} />
        <MetricCard label="MAE" value={data.mae_value.toFixed(2)} />
        <MetricCard label="Forecast Horizon" value={`${data.forecast_horizon} periods`} />
      </div>

      {/* Graph 1: Selected Model */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-lg">Forecast</CardTitle>
        </CardHeader>
        <CardContent>
          <img
            src={`data:image/png;base64,${data.chart1_base64}`}
            alt="Selected model forecast"
            className="w-full rounded-lg"
          />
          <p className="text-sm text-muted-foreground mt-4 leading-relaxed">
            {data.summary1}
          </p>
        </CardContent>
      </Card>

      {/* Graph 2: Model Comparison */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-lg">Model Comparison</CardTitle>
        </CardHeader>
        <CardContent>
          <img
            src={`data:image/png;base64,${data.chart2_base64}`}
            alt="Model comparison"
            className="w-full rounded-lg"
          />
          <p className="text-sm text-muted-foreground mt-4 leading-relaxed">
            {data.summary2}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-4 pb-4">
        <p className="text-xs text-muted-foreground uppercase tracking-wider">{label}</p>
        <p className="text-xl font-semibold text-emerald-500 mt-1">{value}</p>
      </CardContent>
    </Card>
  );
}
