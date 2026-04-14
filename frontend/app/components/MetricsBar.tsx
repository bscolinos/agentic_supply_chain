"use client";

import { useEffect, useRef, useState } from "react";
import { formatCents, formatNumber } from "../lib/api";

interface Metrics {
  total_savings_cents: number;
  total_shipments_rerouted: number;
  total_interventions_completed: number;
  active_disruptions: number;
  events_per_minute: number;
}

function useAnimatedValue(target: number, duration = 800): number {
  const [display, setDisplay] = useState(0);
  const prev = useRef(0);
  const raf = useRef<number>(0);

  useEffect(() => {
    // Subscribe to animation frames, updating display via callback
    let cancelled = false;
    const start = prev.current;
    const diff = target - start;
    if (diff === 0) {
      prev.current = target;
      return;
    }

    const startTime = performance.now();
    const animate = (now: number) => {
      if (cancelled) return;
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const val = Math.round(start + diff * eased);
      setDisplay(val);
      if (progress < 1) {
        raf.current = requestAnimationFrame(animate);
      } else {
        prev.current = target;
      }
    };
    raf.current = requestAnimationFrame(animate);

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf.current);
    };
  }, [target, duration]);

  return display;
}

interface MetricsBarProps {
  metrics: Metrics | null;
}

export default function MetricsBar({ metrics }: MetricsBarProps) {
  const savings = useAnimatedValue(metrics?.total_savings_cents ?? 0);
  const rerouted = useAnimatedValue(metrics?.total_shipments_rerouted ?? 0);
  const activeDisruptions = metrics?.active_disruptions ?? 0;
  const epm = useAnimatedValue(metrics?.events_per_minute ?? 0);

  return (
    <div className="grid grid-cols-4 gap-4 mb-6">
      {/* Total Money Saved */}
      <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
        <div className="text-xs text-emerald-400/70 uppercase tracking-wider mb-1">
          Total Money Saved
        </div>
        <div className="text-3xl font-bold text-emerald-400 font-mono tabular-nums">
          {formatCents(savings)}
        </div>
      </div>

      {/* Shipments Rerouted */}
      <div className="rounded-xl border border-zinc-700 bg-zinc-800/50 p-4">
        <div className="text-xs text-zinc-400 uppercase tracking-wider mb-1">
          Shipments Rerouted
        </div>
        <div className="text-3xl font-bold text-white font-mono tabular-nums">
          {formatNumber(rerouted)}
        </div>
      </div>

      {/* Active Disruptions */}
      <div
        className={`rounded-xl border p-4 ${
          activeDisruptions > 0
            ? "border-amber-500/30 bg-amber-500/5"
            : "border-emerald-500/20 bg-emerald-500/5"
        }`}
      >
        <div
          className={`text-xs uppercase tracking-wider mb-1 ${
            activeDisruptions > 0 ? "text-amber-400/70" : "text-emerald-400/70"
          }`}
        >
          Active Disruptions
        </div>
        <div
          className={`text-3xl font-bold font-mono tabular-nums ${
            activeDisruptions > 0 ? "text-amber-400" : "text-emerald-400"
          }`}
        >
          {activeDisruptions}
        </div>
      </div>

      {/* Events/min */}
      <div className="rounded-xl border border-zinc-700 bg-zinc-800/50 p-4">
        <div className="text-xs text-zinc-400 uppercase tracking-wider mb-1">
          Events / min
        </div>
        <div className="text-3xl font-bold text-blue-400 font-mono tabular-nums">
          {formatNumber(epm)}
        </div>
      </div>
    </div>
  );
}
