"use client";

import { Loader2 } from "lucide-react";

export default function LoadingState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-4">
      <Loader2 className="w-10 h-10 text-white animate-spin" />
      <div className="text-center">
        <p className="text-lg font-medium">Analyzing your data...</p>
        <p className="text-sm text-muted-foreground mt-1">
          Running models and comparing results. This may take a few seconds.
        </p>
      </div>
    </div>
  );
}
