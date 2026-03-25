"use client";

import { useState } from "react";
import { Download, FileSpreadsheet, FlaskConical, ClipboardCheck, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { exportPDF, exportExcel, exportIndependentValidation, exportManualValidation, type ForecastResponse } from "@/lib/api";

interface DownloadButtonProps {
  data: ForecastResponse;
  timingMs?: { dataProcessing: number | null; predictionGeneration: number | null };
  appVersion?: string;
  reportNumber?: number | null;
}

function generateFilename(ext: string, appVersion: string, reportNumber: number, suffix?: string): string {
  const now = new Date();
  const date = `${String(now.getDate()).padStart(2, "0")}${String(now.getMonth() + 1).padStart(2, "0")}${now.getFullYear()}`;
  const sfx = suffix ? `_${suffix}` : "";
  return `MarketPulse_${date}_V${appVersion}${sfx}_${reportNumber}.${ext}`;
}

export default function DownloadButton({ data, timingMs, appVersion = "1.5", reportNumber }: DownloadButtonProps) {
  const [isExportingPDF, setIsExportingPDF] = useState(false);
  const [isExportingExcel, setIsExportingExcel] = useState(false);
  const [isExportingIndVal, setIsExportingIndVal] = useState(false);
  const [isExportingManVal, setIsExportingManVal] = useState(false);

  const handleDownload = async (
    exportFn: () => Promise<Blob>,
    filename: string,
    setLoading: (v: boolean) => void,
    label: string,
  ) => {
    setLoading(true);
    try {
      const blob = await exportFn();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error(`${label} export failed:`, error);
    } finally {
      setLoading(false);
    }
  };

  const rn = reportNumber ?? 1;

  return (
    <div className="grid grid-cols-2 gap-2 w-full max-w-[420px]">
      {[
        { label: "Download Excel", loadingLabel: "Generating...", icon: FileSpreadsheet, loading: isExportingExcel, setLoading: setIsExportingExcel, fn: () => exportExcel(data), ext: "xlsx", suffix: "Report", tag: "Excel" },
        { label: "Download PDF", loadingLabel: "Generating...", icon: Download, loading: isExportingPDF, setLoading: setIsExportingPDF, fn: () => exportPDF(data, timingMs), ext: "pdf", suffix: "Report", tag: "PDF" },
        { label: "Independent Validation", loadingLabel: "Generating...", icon: FlaskConical, loading: isExportingIndVal, setLoading: setIsExportingIndVal, fn: () => exportIndependentValidation(data), ext: "xlsx", suffix: "IndependentValidation", tag: "Independent Validation" },
        { label: "Manual Validation", loadingLabel: "Generating...", icon: ClipboardCheck, loading: isExportingManVal, setLoading: setIsExportingManVal, fn: () => exportManualValidation(data), ext: "xlsx", suffix: "ManualValidation", tag: "Manual Validation" },
      ].map(({ label, loadingLabel, icon: Icon, loading, setLoading, fn, ext, suffix, tag }) => (
        <Button
          key={label}
          onClick={() => handleDownload(fn, generateFilename(ext, appVersion, rn, suffix), setLoading, tag)}
          disabled={loading}
          className="bg-white text-black hover:bg-white/90 font-semibold border-0 px-3 py-1.5 text-[13px] w-full justify-center whitespace-nowrap"
        >
          {loading ? (
            <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
          ) : (
            <Icon className="w-3.5 h-3.5 mr-1.5" />
          )}
          {loading ? loadingLabel : label}
        </Button>
      ))}
    </div>
  );
}
