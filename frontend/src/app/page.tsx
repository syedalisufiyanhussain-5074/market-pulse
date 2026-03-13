"use client";

import { useState } from "react";
import Image from "next/image";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import FileUploader from "@/components/FileUploader";
import ColumnSelector from "@/components/ColumnSelector";
import LoadingState from "@/components/LoadingState";
import ForecastResults from "@/components/ForecastResults";
import DownloadButton from "@/components/DownloadButton";
import { uploadFile, runForecast, type UploadResponse, type ForecastResponse } from "@/lib/api";

type Step = "upload" | "configure" | "loading" | "results";

export default function Home() {
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [uploadData, setUploadData] = useState<UploadResponse | null>(null);
  const [forecastData, setForecastData] = useState<ForecastResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [dataProcessingTimeMs, setDataProcessingTimeMs] = useState<number | null>(null);
  const [predictionGenerationTimeMs, setPredictionGenerationTimeMs] = useState<number | null>(null);

  const handleFileSelect = async (selectedFile: File) => {
    setFile(selectedFile);
    setError(null);
    setIsUploading(true);
    const t0 = performance.now();

    try {
      const data = await uploadFile(selectedFile);
      setUploadData(data);

      if (data.date_columns.length === 0) {
        setError("No date columns detected. Please ensure your file contains a date column.");
        setIsUploading(false);
        return;
      }
      if (data.numeric_columns.length === 0) {
        setError("No numeric columns detected. Please ensure your file contains numeric data.");
        setIsUploading(false);
        return;
      }

      setStep("configure");
      setDataProcessingTimeMs(Math.max(0, Math.round(performance.now() - t0)));
    } catch (err) {
      setDataProcessingTimeMs(Math.max(0, Math.round(performance.now() - t0)));
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  };

  const handleConfirm = async (dateColumn: string, targetColumn: string, preference: string) => {
    if (!file) return;
    setError(null);
    setStep("loading");
    const t0 = performance.now();

    try {
      const data = await runForecast(file, dateColumn, targetColumn, preference);
      setForecastData(data);
      setStep("results");
      setPredictionGenerationTimeMs(Math.max(0, Math.round(performance.now() - t0)));
    } catch (err) {
      setPredictionGenerationTimeMs(Math.max(0, Math.round(performance.now() - t0)));
      setError(err instanceof Error ? err.message : "Forecast failed");
      setStep("configure");
    }
  };

  const handleReset = () => {
    setStep("upload");
    setFile(null);
    setUploadData(null);
    setForecastData(null);
    setError(null);
    setDataProcessingTimeMs(null);
    setPredictionGenerationTimeMs(null);
  };

  // Map internal model names to display names
  const displayModel = (name: string) => {
    const map: Record<string, string> = { AutoETS: "ETS", AutoARIMA: "ARIMA" };
    return map[name] || name;
  };

  return (
    <main className="min-h-screen bg-black">
      {/* Header */}
      <header className="border-b border-white/10">
        <div className="max-w-3xl mx-auto px-6 py-3 flex items-center justify-between">
          <a href="/" className="flex items-center">
            <Image
              src="/logo-horizontal.png"
              alt="Market Pulse"
              width={216}
              height={54}
              priority
            />
          </a>
          {step !== "upload" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleReset}
              className="text-white/60 hover:text-white hover:bg-white/5 border border-white/10"
            >
              <RotateCcw className="w-4 h-4 mr-1" />
              Start Over
            </Button>
          )}
        </div>
      </header>

      {/* Content */}
      <div className="max-w-3xl mx-auto px-6 py-10">
        {/* Error display */}
        {error && (
          <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Step: Upload */}
        {step === "upload" && (
          <div className="space-y-6">
            <div className="text-center space-y-2">
              <h2 className="text-2xl font-bold tracking-tight text-white">
                Upload your dataset
              </h2>
              <p className="text-white/50">
                Get AI-powered demand and price forecasts in seconds.
              </p>
            </div>
            <FileUploader onFileSelect={handleFileSelect} isLoading={isUploading} />
          </div>
        )}

        {/* Step: Configure */}
        {step === "configure" && uploadData && (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-bold tracking-tight text-white">Configure forecast</h2>
              <p className="text-white/50 mt-1">
                Confirm your columns and forecasting preference.
              </p>
            </div>
            <div className="bg-black border border-white/10 rounded-xl p-6">
              <ColumnSelector
                dateColumns={uploadData.date_columns}
                numericColumns={uploadData.numeric_columns}
                rowCount={uploadData.row_count}
                onConfirm={handleConfirm}
                isLoading={false}
              />
            </div>
          </div>
        )}

        {/* Step: Loading */}
        {step === "loading" && <LoadingState />}

        {/* Step: Results */}
        {step === "results" && forecastData && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold tracking-tight text-white">Forecast Results</h2>
                <p className="text-white/50 mt-1">
                  Analysis complete. Review your forecast below.
                </p>
              </div>
              <DownloadButton data={forecastData} />
            </div>
            <ForecastResults
              data={forecastData}
              displayModel={displayModel}
              timingMs={{
                dataProcessing: dataProcessingTimeMs,
                predictionGeneration: predictionGenerationTimeMs,
              }}
            />
          </div>
        )}
      </div>
    </main>
  );
}
