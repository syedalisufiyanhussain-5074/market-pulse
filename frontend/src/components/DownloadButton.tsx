"use client";

import { useState } from "react";
import { Download, FileSpreadsheet, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { exportPDF, exportExcel, type ForecastResponse } from "@/lib/api";

interface DownloadButtonProps {
  data: ForecastResponse;
  timingMs?: { dataProcessing: number | null; predictionGeneration: number | null };
  appVersion?: string;
}

function generateFilename(ext: string, appVersion: string): string {
  const now = new Date();
  const date = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}`;
  const key = `mp_reports_${date}`;
  const count = parseInt(localStorage.getItem(key) ?? "0", 10) + 1;
  localStorage.setItem(key, String(count));
  return `MarketPulse_${date}_V${appVersion}_Report_${count}.${ext}`;
}

export default function DownloadButton({ data, timingMs, appVersion = "1.3" }: DownloadButtonProps) {
  const [isExportingPDF, setIsExportingPDF] = useState(false);
  const [isExportingExcel, setIsExportingExcel] = useState(false);

  const handleDownloadPDF = async () => {
    setIsExportingPDF(true);
    try {
      const blob = await exportPDF(data, timingMs);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = generateFilename("pdf", appVersion);
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error("PDF export failed:", error);
    } finally {
      setIsExportingPDF(false);
    }
  };

  const handleDownloadExcel = async () => {
    setIsExportingExcel(true);
    try {
      const blob = await exportExcel(data);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = generateFilename("xlsx", appVersion);
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Excel export failed:", error);
    } finally {
      setIsExportingExcel(false);
    }
  };

  return (
    <div className="flex gap-2">
      <Button
        onClick={handleDownloadExcel}
        disabled={isExportingExcel}
        className="bg-white text-black hover:bg-white/90 font-bold border-0 px-4 py-2 text-sm"
      >
        {isExportingExcel ? (
          <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        ) : (
          <FileSpreadsheet className="w-4 h-4 mr-2" />
        )}
        {isExportingExcel ? "Generating..." : "Download Excel"}
      </Button>
      <Button
        onClick={handleDownloadPDF}
        disabled={isExportingPDF}
        className="bg-white text-black hover:bg-white/90 font-bold border-0 px-4 py-2 text-sm"
      >
        {isExportingPDF ? (
          <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        ) : (
          <Download className="w-4 h-4 mr-2" />
        )}
        {isExportingPDF ? "Generating..." : "Download PDF"}
      </Button>
    </div>
  );
}
