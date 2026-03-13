"use client";

import { Loader2 } from "lucide-react";

interface LoadingStateProps {
  progress: number;
  message: string;
}

export default function LoadingState({ progress, message }: LoadingStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-6">
      <Loader2 className="w-10 h-10 text-white animate-spin" />
      <div className="w-full max-w-xs">
        <div className="h-2 bg-white/10 rounded-full overflow-hidden">
          <div
            className="h-full bg-emerald-500 rounded-full transition-all duration-500 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="flex justify-between mt-2">
          <p className="text-sm text-white/70">{message}</p>
          <p className="text-sm text-white/70">{progress}%</p>
        </div>
      </div>
    </div>
  );
}
