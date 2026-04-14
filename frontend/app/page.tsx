"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api, formatNumber } from "./lib/api";
import { useWebSocket } from "./hooks/useWebSocket";
import EventFeed from "./components/EventFeed";
import DisruptionCard from "./components/DisruptionCard";
import InterventionPanel from "./components/InterventionPanel";
import MetricsBar from "./components/MetricsBar";
import NLQuery from "./components/NLQuery";
import QueryBadge from "./components/QueryBadge";

interface HealthData {
  network_health: {
    total_in_transit: number;
    at_risk_count: number;
    active_disruptions: number;
    priority_breakdown?: Record<string, { total: number; at_risk: number }>;
  };
  active_disruptions: number;
  query_ms: number;
}

interface MetricsData {
  total_savings_cents: number;
  total_shipments_rerouted: number;
  total_interventions_completed: number;
  active_disruptions: number;
  events_per_minute: number;
  query_ms?: number;
}

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

function getDisruptionKey(disruption: Disruption): string {
  return [
    disruption.weather_event_name || "unknown-event",
    disruption.affected_region || disruption.affected_facility || "unknown-location",
  ]
    .join("::")
    .toLowerCase();
}

function dedupeDisruptions(disruptions: Disruption[]): Disruption[] {
  const unique = new Map<string, Disruption>();

  for (const disruption of disruptions) {
    const key = getDisruptionKey(disruption);
    const existing = unique.get(key);

    if (!existing || disruption.risk_score > existing.risk_score) {
      unique.set(key, disruption);
    }
  }

  return Array.from(unique.values()).sort((a, b) => b.risk_score - a.risk_score);
}

type AuditEntry = {
  action_type: string;
  description: string;
  created_at?: string;
};

type InterventionOption = {
  intervention_id: number;
  option_label: string;
  option_description: string;
  action_type: string;
  estimated_cost_cents: number;
  estimated_savings_cents: number;
  affected_shipment_count: number;
  shipments_saved_count: number;
  customer_notifications_count: number;
  status: string;
  selected_by?: string;
};

type SavingsReport = {
  penalties_avoided_cents: number;
  shipments_rerouted: number;
  customer_notifications_sent: number;
  response_time_seconds: number | null;
  healthcare_shipments_protected: number;
};

type InterventionBundle = {
  interventions: InterventionOption[];
  savings_report: SavingsReport | null;
};

export default function NerveDashboard() {
  const { connected, events: wsEvents, lastEvent } = useWebSocket();
  const [health, setHealth] = useState<HealthData | null>(null);
  const [metrics, setMetrics] = useState<MetricsData | null>(null);
  const [disruptions, setDisruptions] = useState<Disruption[]>([]);
  const [interventionsByDisruption, setInterventionsByDisruption] = useState<
    Record<number, InterventionBundle>
  >({});
  const [showQuery, setShowQuery] = useState(false);
  const lastRefreshAt = useRef(0);
  const refreshInFlight = useRef(false);

  const refreshData = useCallback(async () => {
    if (refreshInFlight.current) {
      return;
    }

    refreshInFlight.current = true;
    try {
      console.log('[NERVE] Fetching data...');
      const [healthResult, disruptionResult, metricsResult] = await Promise.allSettled([
        api.healthPulse(),
        api.disruptions(),
        api.metrics(),
      ]);

      console.log('[NERVE] Results:', {
        health: healthResult.status,
        disruptions: disruptionResult.status,
        metrics: metricsResult.status
      });

      if (healthResult.status === "fulfilled") {
        console.log('[NERVE] Health data:', healthResult.value);
        setHealth(healthResult.value);
      } else {
        console.error('[NERVE] Health failed:', healthResult.reason);
      }

      if (metricsResult.status === "fulfilled") {
        console.log('[NERVE] Metrics data:', metricsResult.value);
        setMetrics(metricsResult.value);
      } else {
        console.error('[NERVE] Metrics failed:', metricsResult.reason);
      }

      if (disruptionResult.status === "fulfilled") {
        console.log('[NERVE] Disruptions count:', disruptionResult.value.disruptions?.length);
        setDisruptions(dedupeDisruptions(disruptionResult.value.disruptions || []));
        setInterventionsByDisruption(
          disruptionResult.value.interventions_by_disruption || {}
        );
      } else {
        console.error('[NERVE] Disruptions failed:', disruptionResult.reason);
      }

      lastRefreshAt.current = Date.now();
    } catch (err) {
      console.error('[NERVE] Refresh error:', err);
    } finally {
      refreshInFlight.current = false;
    }
  }, []);

  useEffect(() => {
    refreshData();
    const interval = setInterval(refreshData, 5000);
    return () => clearInterval(interval);
  }, [refreshData]);

  useEffect(() => {
    const lastWs = lastEvent;
    if (
      lastWs?.type === "disruption_detected" ||
      lastWs?.type === "intervention_executed"
    ) {
      if (Date.now() - lastRefreshAt.current < 1500) {
        return;
      }
      refreshData();
    }
  }, [lastEvent, refreshData]);

  const networkStatus =
    (health?.active_disruptions || 0) > 0
      ? "DISRUPTION ACTIVE"
      : "ALL CLEAR";

  const statusColor =
    (health?.active_disruptions || 0) > 0
      ? "text-amber-400"
      : "text-emerald-400";

  const statusDot =
    (health?.active_disruptions || 0) > 0
      ? "bg-amber-400"
      : "bg-emerald-400";

  return (
    <div className="h-screen flex flex-col bg-zinc-950">
      {/* Top bar */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-zinc-800 bg-zinc-900/50">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-bold text-white tracking-tight">
            NERVE
          </h1>
          <span className="text-xs text-zinc-500 hidden sm:inline">
            Network Event Response &amp; Visibility Engine
          </span>
          <span className="rounded-full bg-purple-500/20 text-purple-400 px-2 py-0.5 text-xs font-semibold">
            AUTONOMOUS
          </span>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${statusDot} ${
                (health?.active_disruptions || 0) > 0 ? "animate-pulse" : ""
              }`}
            />
            <span className={`text-xs font-semibold ${statusColor}`}>
              {networkStatus}
            </span>
          </div>

          {health && (
            <div className="hidden md:flex items-center gap-3 text-xs text-zinc-500">
              <span>
                {formatNumber(health.network_health?.total_in_transit || 0)} in
                transit
              </span>
              <span>
                {formatNumber(health.network_health?.at_risk_count || 0)} at
                risk
              </span>
            </div>
          )}

          {health && <QueryBadge queryMs={health.query_ms} detail="health pulse" />}

          <button
            onClick={() => setShowQuery(!showQuery)}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              showQuery
                ? "bg-blue-600 text-white"
                : "bg-zinc-800 text-zinc-400 hover:text-white"
            }`}
          >
            Ask NERVE
          </button>
        </div>
      </header>

      {showQuery && (
        <div className="border-b border-zinc-800 p-4 bg-zinc-900/30">
          <NLQuery />
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        <div className="w-80 border-r border-zinc-800 flex flex-col">
          <EventFeed
            events={wsEvents.map((e) => ({
              type: e.type as string,
              tracking_number: e.tracking_number as string | undefined,
              event_type: e.event_type as string | undefined,
              facility_code: e.facility_code as string | undefined,
              description: e.description as string | undefined,
              timestamp: e.timestamp as string | undefined,
              event: (e as Record<string, unknown>).event as string | undefined,
            }))}
            connected={connected}
          />
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <MetricsBar metrics={metrics} />

          {disruptions.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <div className="text-6xl mb-4 opacity-20">{"\u25C9"}</div>
              <h2 className="text-xl font-semibold text-zinc-400 mb-2">
                Network Operating Normally
              </h2>
              <p className="text-sm text-zinc-600 max-w-md">
                The autonomous engine is monitoring shipments. Disruptions will
                appear here when weather events affect the network.
              </p>
            </div>
          )}

          <div className="space-y-6">
            {disruptions.map((disruption) => (
              <div key={disruption.disruption_id}>
                <DisruptionCard disruption={disruption} />
                <div className="mt-4">
                  <InterventionPanel
                    options={
                      interventionsByDisruption[disruption.disruption_id]
                        ?.interventions || []
                    }
                    savingsReport={
                      interventionsByDisruption[disruption.disruption_id]
                        ?.savings_report || null
                    }
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {disruptions.length > 0 && (
          <div className="w-72 border-l border-zinc-800 p-4 overflow-y-auto">
            <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider mb-3">
              Audit Trail
            </h3>
            {disruptions.slice(0, 15).map((d) => (
              <div key={d.disruption_id} className="mb-4">
                <div className="text-xs text-zinc-500 mb-2 font-semibold">
                  {d.weather_event_name || `Disruption #${d.disruption_id}`}
                </div>
                <AuditTrail disruptionId={d.disruption_id} detectedAt={d.detected_at} />
              </div>
            ))}
          </div>
        )}
      </div>

      <footer className="flex items-center justify-between px-6 py-2 border-t border-zinc-800 bg-zinc-900/50 text-xs text-zinc-600">
        <span>NERVE v0.2.0 {"\u00b7"} Autonomous Engine {"\u00b7"} Powered by SingleStore + Claude AI</span>
        <span>
          WS: {connected ? "\u25CF" : "\u25CB"} {"\u00b7"} Events: {wsEvents.length}
        </span>
      </footer>
    </div>
  );
}

function AuditTrail({ disruptionId, detectedAt }: { disruptionId: number; detectedAt: string }) {
  // Audit trail loading disabled for performance - just show empty state
  const [trail] = useState<AuditEntry[]>([]);
  const [loading] = useState(false);

  return (
    <div className="space-y-2">
      {trail.map((entry, i) => (
        <div key={i} className="flex items-start gap-2">
          <div className="mt-1.5 h-2 w-2 rounded-full bg-emerald-400 shrink-0" />
          <div>
            <div className="text-xs text-zinc-300">{entry.description}</div>
            {entry.created_at && (
              <div className="text-xs text-zinc-600">
                {new Date(entry.created_at).toLocaleTimeString()}
              </div>
            )}
          </div>
        </div>
      ))}
      {trail.length === 0 && (
        <div className="text-xs text-zinc-600">Awaiting actions...</div>
      )}
    </div>
  );
}
