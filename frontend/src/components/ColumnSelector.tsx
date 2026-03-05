"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";

interface ColumnSelectorProps {
  dateColumns: string[];
  numericColumns: string[];
  rowCount: number;
  onConfirm: (dateColumn: string, targetColumn: string, preference: string) => void;
  isLoading: boolean;
}

export default function ColumnSelector({
  dateColumns,
  numericColumns,
  rowCount,
  onConfirm,
  isLoading,
}: ColumnSelectorProps) {
  const [dateColumn, setDateColumn] = useState("");
  const [targetColumn, setTargetColumn] = useState("");
  const [preference, setPreference] = useState("");

  const canSubmit = dateColumn && targetColumn && preference && !isLoading;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span className="inline-block w-2 h-2 rounded-full bg-emerald-500" />
        {rowCount.toLocaleString()} rows detected
      </div>

      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="date-col">Please confirm the date column.</Label>
          <Select value={dateColumn} onValueChange={setDateColumn}>
            <SelectTrigger id="date-col" className="bg-card border-border">
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

        <div className="space-y-2">
          <Label htmlFor="target-col">Please select the field to forecast.</Label>
          <Select value={targetColumn} onValueChange={setTargetColumn}>
            <SelectTrigger id="target-col" className="bg-card border-border">
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

        <div className="space-y-2">
          <Label>Please confirm your preferred forecasting approach.</Label>
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => setPreference("conservative")}
              className={`p-4 rounded-lg border text-left transition-all ${
                preference === "conservative"
                  ? "border-emerald-500 bg-emerald-500/10"
                  : "border-border bg-card hover:border-emerald-500/30"
              }`}
            >
              <p className="font-medium text-sm">Conservative</p>
              <p className="text-xs text-muted-foreground mt-1">Avoids overestimation</p>
            </button>
            <button
              type="button"
              onClick={() => setPreference("capacity-buffered")}
              className={`p-4 rounded-lg border text-left transition-all ${
                preference === "capacity-buffered"
                  ? "border-emerald-500 bg-emerald-500/10"
                  : "border-border bg-card hover:border-emerald-500/30"
              }`}
            >
              <p className="font-medium text-sm">Capacity-buffered</p>
              <p className="text-xs text-muted-foreground mt-1">Avoids stockouts</p>
            </button>
          </div>
        </div>
      </div>

      <Button
        onClick={() => onConfirm(dateColumn, targetColumn, preference)}
        disabled={!canSubmit}
        className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-medium"
      >
        {isLoading ? "Analyzing..." : "Generate Forecast"}
      </Button>
    </div>
  );
}
