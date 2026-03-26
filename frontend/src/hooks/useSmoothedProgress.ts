"use client";

import { useState, useEffect, useRef } from "react";

export function useSmoothedProgress(target: number): number {
  const [display, setDisplay] = useState(0);
  const ref = useRef(0);

  useEffect(() => {
    if (target < ref.current) {
      ref.current = target;
      setDisplay(target);
      return;
    }
    let raf: number;
    const animate = () => {
      const diff = target - ref.current;
      if (Math.abs(diff) < 0.5) {
        ref.current = target;
        setDisplay(target);
        return;
      }
      ref.current = Math.min(target, ref.current + diff * 0.08);
      setDisplay(Math.round(ref.current));
      raf = requestAnimationFrame(animate);
    };
    raf = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(raf);
  }, [target]);

  return display;
}
