"use client";

import { useState, useEffect } from "react";
import { Loader2 } from "lucide-react";

interface LoadingStateProps {
  progress: number;
  message: string;
  lastEventTime: number | null;
}

export default function LoadingState({ progress, message, lastEventTime }: LoadingStateProps) {
  const [secondsAgo, setSecondsAgo] = useState(0);

  useEffect(() => {
    if (!lastEventTime) {
      setSecondsAgo(0);
      return;
    }
    const interval = setInterval(() => {
      setSecondsAgo(Math.floor((Date.now() - lastEventTime) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [lastEventTime]);

  return (
    <div className="flex flex-col items-center justify-center py-16 gap-6">
      <Loader2 className="w-10 h-10 text-white animate-spin" />
      <div className="w-full max-w-xs">
        <div className="h-2 bg-white/10 rounded-full overflow-hidden">
          <div
            className="h-full bg-emerald-500 rounded-full transition-all duration-300 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="flex justify-between mt-2">
          <p className="text-sm text-white/70">{message}</p>
          <p className="text-sm text-white/70">{progress}%</p>
        </div>
        {secondsAgo > 2 && (
          <p className="text-xs text-white/30 text-center mt-1">Updated {secondsAgo}s ago</p>
        )}
      </div>
    </div>
  );
}
