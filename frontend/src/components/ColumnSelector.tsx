"use client";

import { useState, useMemo, useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";

const FREQ_ORDER = ["D", "W", "MS", "QS", "YS"] as const;

const FREQ_LABELS: Record<string, string> = {
  D: "Daily",
  W: "Weekly",
  MS: "Monthly",
  QS: "Quarterly",
  YS: "Yearly",
};

// Base presets per frequency — extended dynamically up to 50% of data
const BASE_PRESETS: Record<string, number[]> = {
  D: [7, 14, 21, 30, 60, 90, 120, 180, 365],
  W: [2, 4, 8, 12, 26, 52],
  MS: [1, 2, 3, 6, 9, 12, 18, 24, 36],
  QS: [1, 2, 3, 4, 6, 8],
  YS: [1, 2, 3, 5],
};

const HORIZON_BOUNDS: Record<string, [number, number]> = {
  D: [7, 365],
  W: [2, 52],
  MS: [2, 36],
  QS: [1, 8],
  YS: [1, 5],
};

const FREQ_UNITS: Record<string, [string, string]> = {
  D: ["Day", "Days"],
  W: ["Week", "Weeks"],
  MS: ["Month", "Months"],
  QS: ["Quarter", "Quarters"],
  YS: ["Year", "Years"],
};

const APPROX_DAYS: Record<string, number> = {
  D: 1,
  W: 7,
  MS: 30,
  QS: 91,
  YS: 365,
};

function estimateRowCount(
  rawRows: number,
  detectedFreq: string | null,
  selectedFreq: string
): number {
  if (!detectedFreq || detectedFreq === selectedFreq) return rawRows;
  const detectedDays = APPROX_DAYS[detectedFreq] || 1;
  const selectedDays = APPROX_DAYS[selectedFreq] || 1;
  return Math.ceil((rawRows * detectedDays) / selectedDays);
}

interface ColumnSelectorProps {
  dateColumns: string[];
  numericColumns: string[];
  rowCount: number;
  frequencyMap: Record<string, string>;
  periodCountMap: Record<string, number>;
  onConfirm: (
    dateColumn: string,
    targetColumn: string,
    preference: string,
    frequency: string,
    numPredictions: number,
  ) => void;
  isLoading: boolean;
}

export default function ColumnSelector({
  dateColumns,
  numericColumns,
  rowCount,
  frequencyMap,
  periodCountMap,
  onConfirm,
  isLoading,
}: ColumnSelectorProps) {
  const [dateColumn, setDateColumn] = useState("");
  const [targetColumn, setTargetColumn] = useState("");
  const [preference, setPreference] = useState("");
  const [frequency, setFrequency] = useState("");
  const [numPredictions, setNumPredictions] = useState("");

  // Detected frequency for the selected date column
  const detectedFreq = dateColumn ? frequencyMap[dateColumn] ?? null : null;

  // Valid frequencies: detected + all coarser
  const validFrequencies = useMemo(() => {
    if (!detectedFreq) return [];
    const idx = FREQ_ORDER.indexOf(detectedFreq as typeof FREQ_ORDER[number]);
    if (idx === -1) return [];
    return FREQ_ORDER.slice(idx);
  }, [detectedFreq]);

  // Auto-set frequency when date column changes
  useEffect(() => {
    if (detectedFreq) {
      setFrequency(detectedFreq);
    } else {
      setFrequency("");
    }
  }, [detectedFreq]);

  // Unique periods for the selected date column (not raw row count)
  const detectedPeriods = dateColumn ? periodCountMap[dateColumn] ?? rowCount : rowCount;

  // Effective row count after potential aggregation
  const effectiveRows = useMemo(() => {
    if (!frequency || !detectedFreq) return detectedPeriods;
    return estimateRowCount(detectedPeriods, detectedFreq, frequency);
  }, [frequency, detectedPeriods, detectedFreq]);

  // Smart prediction presets filtered by effective data size
  const predictionOptions = useMemo(() => {
    if (!frequency) return [];
    const presets = BASE_PRESETS[frequency] || [];
    const maxHorizon = Math.ceil(effectiveRows / 2);  // 50% cap, rounded up
    return presets.filter((p) => p <= maxHorizon);
  }, [frequency, effectiveRows]);

  // Default horizon (mirrors backend 20% rule)
  const defaultHorizon = useMemo(() => {
    if (!frequency) return null;
    const [minH, maxH] = HORIZON_BOUNDS[frequency] || [2, 12];
    return Math.max(minH, Math.min(maxH, Math.floor(effectiveRows * 0.25)));
  }, [frequency, effectiveRows]);

  // Auto-set predictions when frequency or options change
  useEffect(() => {
    if (predictionOptions.length === 0) {
      setNumPredictions("");
      return;
    }
    // Pick the preset closest to the default horizon
    const target = defaultHorizon ?? predictionOptions[0];
    const closest = predictionOptions.reduce((a, b) =>
      Math.abs(a - target) <= Math.abs(b - target) ? a : b
    );
    setNumPredictions(String(closest));
  }, [predictionOptions, defaultHorizon]);

  const canSubmit =
    dateColumn && targetColumn && preference && frequency && numPredictions && !isLoading;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span className="inline-block w-2 h-2 rounded-full bg-white" />
        {rowCount.toLocaleString()} rows detected
      </div>

      <div className="space-y-4">
        {/* 2x2 grid: date+freq, target+predictions */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Row 1, Col 1: Date Column */}
          <div className="space-y-2">
            <Label htmlFor="date-col">Please confirm the date column.</Label>
            <Select value={dateColumn} onValueChange={setDateColumn}>
              <SelectTrigger id="date-col" className="bg-black border-white/20">
                <SelectValue placeholder="Select date column" />
              </SelectTrigger>
              <SelectContent>
                {dateColumns.map((col) => (
                  <SelectItem key={col} value={col}>
                    {col}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Row 1, Col 2: Frequency */}
          <div className="space-y-2">
            <Label htmlFor="freq">Data frequency</Label>
            <Select
              value={frequency}
              onValueChange={setFrequency}
              disabled={!dateColumn}
            >
              <SelectTrigger id="freq" className="bg-black border-white/20">
                <SelectValue placeholder="Select frequency" />
              </SelectTrigger>
              <SelectContent>
                {validFrequencies.map((f) => (
                  <SelectItem key={f} value={f}>
                    {FREQ_LABELS[f]}
                    {f === detectedFreq ? " (detected)" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Row 2, Col 1: Target Column */}
          <div className="space-y-2">
            <Label htmlFor="target-col">Please select the field to forecast.</Label>
            <Select value={targetColumn} onValueChange={setTargetColumn}>
              <SelectTrigger id="target-col" className="bg-black border-white/20">
                <SelectValue placeholder="Select target column" />
              </SelectTrigger>
              <SelectContent>
                {numericColumns.map((col) => (
                  <SelectItem key={col} value={col}>
                    {col}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Row 2, Col 2: Number of Predictions */}
          <div className="space-y-2">
            <Label htmlFor="num-pred">Number of predictions</Label>
            <Select
              value={numPredictions}
              onValueChange={setNumPredictions}
              disabled={!frequency}
            >
              <SelectTrigger id="num-pred" className="bg-black border-white/20">
                <SelectValue placeholder="Select periods" />
              </SelectTrigger>
              <SelectContent>
                {predictionOptions.length > 0 ? (
                  predictionOptions.map((n) => {
                    const [singular, plural] = FREQ_UNITS[frequency] ?? ["Period", "Periods"];
                    const unit = n === 1 ? singular : plural;
                    return (
                      <SelectItem key={n} value={String(n)}>
                        {n} {unit}
                        {n === defaultHorizon ? " (recommended)" : ""}
                      </SelectItem>
                    );
                  })
                ) : (
                  <SelectItem value="__empty" disabled>
                    Not enough data for this frequency
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Preference toggle — full width */}
        <div className="space-y-2">
          <Label>Please confirm your preferred forecasting approach.</Label>
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => setPreference("conservative")}
              className={`p-4 rounded-lg border text-left transition-all ${
                preference === "conservative"
                  ? "border-white bg-white/10"
                  : "border-white/20 bg-black hover:border-white/40"
              }`}
            >
              <p className="font-medium text-sm">Avoids Overestimation (Under-forecast)</p>
            </button>
            <button
              type="button"
              onClick={() => setPreference("capacity-buffered")}
              className={`p-4 rounded-lg border text-left transition-all ${
                preference === "capacity-buffered"
                  ? "border-white bg-white/10"
                  : "border-white/20 bg-black hover:border-white/40"
              }`}
            >
              <p className="font-medium text-sm">Avoids Stockouts (Over-forecast)</p>
            </button>
          </div>
        </div>
      </div>

      <Button
        onClick={() =>
          onConfirm(dateColumn, targetColumn, preference, frequency, parseInt(numPredictions))
        }
        disabled={!canSubmit}
        className="w-full bg-white text-black hover:bg-white/90 font-bold border-0"
      >
        {isLoading ? "Analyzing..." : "Generate Forecast"}
      </Button>
    </div>
  );
}
