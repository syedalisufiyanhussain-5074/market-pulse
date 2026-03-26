"use client";

import { useCallback } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";
import { Upload, FileSpreadsheet } from "lucide-react";

interface FileUploaderProps {
  onFileSelect: (file: File) => void;
  onError?: (message: string) => void;
  isLoading: boolean;
}

const ACCEPTED_TYPES = {
  "text/csv": [".csv"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
};

export default function FileUploader({ onFileSelect, onError, isLoading }: FileUploaderProps) {
  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      if (acceptedFiles.length > 0) {
        onFileSelect(acceptedFiles[0]);
      }
    },
    [onFileSelect]
  );

  const onDropRejected = useCallback(
    (rejections: FileRejection[]) => {
      const code = rejections[0]?.errors[0]?.code;
      if (code === "file-too-large") {
        onError?.("This file is too large (over 10 MB). Try reducing the file size or trimming unused columns before uploading.");
      } else if (code === "file-invalid-type") {
        onError?.("Unsupported file type. Please upload a .csv or .xlsx file.");
      } else {
        onError?.("File could not be uploaded. Please try again.");
      }
    },
    [onError]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected,
    accept: ACCEPTED_TYPES,
    maxFiles: 1,
    maxSize: 10 * 1024 * 1024, // 10MB
    disabled: isLoading,
  });

  return (
    <div
      {...getRootProps()}
      className={`
        border-2 border-dashed rounded-xl p-12 text-center cursor-pointer
        transition-all duration-200
        ${isDragActive
          ? "border-white bg-white/5"
          : "border-white/20 hover:border-white/50 hover:bg-white/5"
        }
        ${isLoading ? "opacity-50 cursor-not-allowed" : ""}
      `}
    >
      <input {...getInputProps()} />
      <div className="flex flex-col items-center gap-4">
        {isDragActive ? (
          <FileSpreadsheet className="w-12 h-12 text-white animate-bounce" />
        ) : (
          <Upload className="w-12 h-12 text-muted-foreground" />
        )}
        <div>
          <p className="text-lg font-medium text-foreground">
            {isDragActive ? "Drop your file here" : "Drop your CSV or Excel file here"}
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            or click to browse. Supports .csv and .xlsx files up to 10MB and 100,000 rows.
          </p>
        </div>
      </div>
    </div>
  );
}
