"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { exportPDF, type ForecastResponse } from "@/lib/api";

interface DownloadButtonProps {
  data: ForecastResponse;
}

export default function DownloadButton({ data }: DownloadButtonProps) {
  const [isExporting, setIsExporting] = useState(false);

  const handleDownload = async () => {
    setIsExporting(true);
    try {
      const blob = await exportPDF(data);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "market-pulse-report.pdf";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error("PDF export failed:", error);
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <Button
      onClick={handleDownload}
      disabled={isExporting}
      className="bg-white text-black hover:bg-white/90 font-bold border-0"
    >
      {isExporting ? (
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
      ) : (
        <Download className="w-4 h-4 mr-2" />
      )}
      {isExporting ? "Generating PDF..." : "Download Report"}
    </Button>
  );
}
