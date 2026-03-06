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
        <span className="inline-block w-2 h-2 rounded-full bg-white" />
        {rowCount.toLocaleString()} rows detected
      </div>

      <div className="space-y-4">
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
              <p className="font-medium text-sm">Avoids Overestimation</p>
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
              <p className="font-medium text-sm">Avoids Stockouts</p>
            </button>
          </div>
        </div>
      </div>

      <Button
        onClick={() => onConfirm(dateColumn, targetColumn, preference)}
        disabled={!canSubmit}
        className="w-full bg-white text-black hover:bg-white/90 font-bold border-0"
      >
        {isLoading ? "Analyzing..." : "Generate Forecast"}
      </Button>
    </div>
  );
}
