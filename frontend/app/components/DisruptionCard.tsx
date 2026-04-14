"use client";

import { useState, useEffect } from "react";
import { api, formatCents, formatNumber } from "../lib/api";
import QueryBadge from "./QueryBadge";

interface Disruption {
  disruption_id: number;
  status: string;
  affected_facility: string;
  affected_shipment_count: number;
  critical_shipment_count: number;
  estimated_cost_cents: number;
  estimated_delay_hours: number;
  risk_score: number;
  ai_explanation: string | null;
  detected_at: string;
  weather_event_name?: string;
  weather_type?: string;
  weather_severity?: string;
  affected_region?: string;
  wind_speed_knots?: number;
  precipitation_inches?: number;
  temperature_f?: number;
  weather_start?: string;
  weather_end?: string;
}

interface DisruptionCardProps {
  disruption: Disruption;
}

const severity_colors: Record<string, string> = {
  watch: "border-yellow-500/30 bg-yellow-500/5",
  warning: "border-amber-500/40 bg-amber-500/5",
  emergency: "border-red-500/50 bg-red-500/10",
};

const severity_badges: Record<string, string> = {
  watch: "bg-yellow-500/20 text-yellow-400",
  warning: "bg-amber-500/20 text-amber-400",
  emergency: "bg-red-500/20 text-red-400",
};

export default function DisruptionCard({ disruption }: DisruptionCardProps) {
  const [explanation, setExplanation] = useState("");
  const [loading, setLoading] = useState(false);
  const [queryMs, setQueryMs] = useState(0);
  const [hasLoadedExplanation, setHasLoadedExplanation] = useState(false);

  const severity = disruption.weather_severity || "warning";
  const borderColor = severity_colors[severity] || severity_colors.warning;

  // Auto-load AI explanation when component mounts
  useEffect(() => {
    loadExplanation();
  }, [disruption.disruption_id]);

  async function loadExplanation() {
    if (loading || hasLoadedExplanation) {
      return;
    }

    setLoading(true);
    setQueryMs(0);
    try {
      console.log(`[DisruptionCard] Loading explanation for disruption ${disruption.disruption_id}`);
      const startedAt = performance.now();
      const response = await api.explainDisruption(disruption.disruption_id);
      console.log(`[DisruptionCard] Got response:`, response);
      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("Streaming response unavailable");
      }

      const decoder = new TextDecoder();
      let fullText = "";
      let chunkCount = 0;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunkCount++;
        const chunk = decoder.decode(value);
        const lines = chunk.split("\n");
        for (const line of lines) {
          if (line.startsWith("data: ") && line !== "data: [DONE]") {
            fullText += line.slice(6);
            setExplanation(fullText);
          }
        }
      }
      console.log(`[DisruptionCard] Loaded ${chunkCount} chunks, ${fullText.length} chars`);
      setQueryMs(Math.round(performance.now() - startedAt));
      setHasLoadedExplanation(true);
    } catch (err) {
      console.error(`[DisruptionCard] Error loading explanation:`, err);
      setExplanation(
        `Disruption detected: ${disruption.weather_event_name || "Unknown event"} affecting ${disruption.affected_facility}. ` +
          `${formatNumber(disruption.affected_shipment_count)} shipments at risk ` +
          `(${formatNumber(disruption.critical_shipment_count)} critical/healthcare). ` +
          `Estimated impact: ${formatCents(disruption.estimated_cost_cents)}.`
      );
      setHasLoadedExplanation(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={`rounded-xl border ${borderColor} p-5`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-semibold uppercase ${
                severity_badges[severity] || severity_badges.warning
              }`}
            >
              {severity}
            </span>
            {disruption.status === "mitigating" && (
              <span className="rounded-full bg-emerald-500/20 text-emerald-400 px-2 py-0.5 text-xs font-semibold">
                AUTO-RESOLVED
              </span>
            )}
            <span className="text-xs text-zinc-500">
              {new Date(disruption.detected_at).toLocaleTimeString()}
            </span>
          </div>
          <h2 className="text-lg font-bold text-white">
            {disruption.weather_event_name || "Disruption Detected"}
          </h2>
          <p className="text-sm text-zinc-400">
            {disruption.affected_region || disruption.affected_facility}
          </p>
        </div>
        <div className="text-right">
          <div className="text-3xl font-bold text-white font-mono">
            {disruption.risk_score?.toFixed(0)}
          </div>
          <div className="text-xs text-zinc-500 uppercase">Risk Score</div>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <div className="rounded-lg bg-zinc-800/50 p-3">
          <div className="text-xl font-bold text-white font-mono">
            {formatNumber(disruption.affected_shipment_count)}
          </div>
          <div className="text-xs text-zinc-500">Shipments at Risk</div>
        </div>
        <div className="rounded-lg bg-zinc-800/50 p-3">
          <div className="text-xl font-bold text-red-400 font-mono">
            {formatNumber(disruption.critical_shipment_count)}
          </div>
          <div className="text-xs text-zinc-500">Critical/Healthcare</div>
        </div>
        <div className="rounded-lg bg-zinc-800/50 p-3">
          <div className="text-xl font-bold text-amber-400 font-mono">
            {disruption.estimated_delay_hours?.toFixed(1) || "4-6"}h
          </div>
          <div className="text-xs text-zinc-500">Est. Delay</div>
        </div>
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
          <div className="text-xl font-bold text-red-400 font-mono">
            {formatCents(disruption.estimated_cost_cents)}
          </div>
          <div className="text-xs text-red-400/70">Estimated Exposure</div>
        </div>
      </div>

      {/* Weather details */}
      {disruption.wind_speed_knots && (
        <div className="flex gap-4 mb-4 text-xs text-zinc-500">
          <span>Wind: {disruption.wind_speed_knots} knots</span>
          {disruption.precipitation_inches && (
            <span>Precip: {disruption.precipitation_inches}&quot;</span>
          )}
          {disruption.temperature_f && (
            <span>Temp: {disruption.temperature_f}°F</span>
          )}
          {disruption.weather_start && (
            <span>
              Window: {new Date(disruption.weather_start).toLocaleTimeString()} -{" "}
              {disruption.weather_end
                ? new Date(disruption.weather_end).toLocaleTimeString()
                : "TBD"}
            </span>
          )}
        </div>
      )}

      {/* AI Explanation */}
      <div className="rounded-lg bg-zinc-900 border border-zinc-800 p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-zinc-300">
            AI Risk Analysis
          </h3>
          {queryMs > 0 && <QueryBadge queryMs={queryMs} />}
        </div>
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <span className="animate-spin">{"\u25CC"}</span>
            Analyzing disruption...
          </div>
        ) : !hasLoadedExplanation ? (
          <button
            type="button"
            onClick={loadExplanation}
            className="rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-300 transition-colors hover:border-zinc-500 hover:text-white"
          >
            Load AI analysis
          </button>
        ) : (
          <div className="text-sm text-zinc-300 whitespace-pre-wrap leading-relaxed">
            {explanation}
          </div>
        )}
      </div>
    </div>
  );
}
