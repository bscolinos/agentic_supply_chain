"use client";

import { formatCents, formatNumber } from "../lib/api";

interface InterventionOption {
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
}

interface SavingsReport {
  penalties_avoided_cents: number;
  shipments_rerouted: number;
  customer_notifications_sent: number;
  response_time_seconds: number | null;
  healthcare_shipments_protected: number;
}

interface InterventionPanelProps {
  options: InterventionOption[];
  savingsReport?: SavingsReport | null;
}

const ACTION_COLORS: Record<string, string> = {
  full_reroute: "border-blue-500/30",
  priority_reroute: "border-amber-500/30",
  hold_and_wait: "border-zinc-500/30",
};

const SELECTED_BORDER: Record<string, string> = {
  full_reroute: "border-emerald-500/60 bg-emerald-500/5",
  priority_reroute: "border-emerald-500/60 bg-emerald-500/5",
  hold_and_wait: "border-emerald-500/60 bg-emerald-500/5",
};

export default function InterventionPanel({
  options,
  savingsReport,
}: InterventionPanelProps) {
  if (options.length === 0) {
    return null;
  }

  const completedOption = options.find((o) => o.status === "completed" || o.status === "selected" || o.status === "executing");

  // Show savings report if intervention completed
  if (savingsReport) {
    return (
      <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-xs text-emerald-400/70 uppercase tracking-wider mb-1">
              Intervention Complete
            </div>
            <div className="text-sm text-zinc-400">
              {completedOption?.option_label}
            </div>
          </div>
          <span className="rounded-full bg-purple-500/20 text-purple-400 px-2 py-0.5 text-xs font-semibold">
            Autonomous Engine
          </span>
        </div>

        <div className="text-center mb-6">
          <div className="text-4xl font-bold text-emerald-400 font-mono">
            {formatCents(savingsReport.penalties_avoided_cents)}
          </div>
          <div className="text-sm text-emerald-400/70 mt-1">
            in penalties avoided
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-zinc-900/50 p-3 text-center">
            <div className="text-2xl font-bold text-white font-mono">
              {formatNumber(savingsReport.shipments_rerouted)}
            </div>
            <div className="text-xs text-zinc-500">Shipments Rerouted</div>
          </div>
          <div className="rounded-lg bg-zinc-900/50 p-3 text-center">
            <div className="text-2xl font-bold text-white font-mono">
              {formatNumber(savingsReport.customer_notifications_sent)}
            </div>
            <div className="text-xs text-zinc-500">Customer Notifications</div>
          </div>
          <div className="rounded-lg bg-zinc-900/50 p-3 text-center">
            <div className="text-2xl font-bold text-blue-400 font-mono">
              {savingsReport.response_time_seconds?.toFixed(0) || "\u2014"}s
            </div>
            <div className="text-xs text-zinc-500">Response Time</div>
          </div>
          <div className="rounded-lg bg-zinc-900/50 p-3 text-center">
            <div className="text-2xl font-bold text-red-400 font-mono">
              {formatNumber(savingsReport.healthcare_shipments_protected)}
            </div>
            <div className="text-xs text-zinc-500">Healthcare Protected</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">
          Intervention Options
        </h3>
        {completedOption && (
          <span className="rounded-full bg-purple-500/20 text-purple-400 px-2 py-0.5 text-xs font-semibold">
            Autonomous Engine
          </span>
        )}
      </div>

      {options.map((option) => {
        const isSelected = option.status === "completed" || option.status === "selected" || option.status === "executing";
        const isCancelled = option.status === "cancelled";
        const borderColor = isSelected
          ? SELECTED_BORDER[option.action_type] || SELECTED_BORDER.hold_and_wait
          : ACTION_COLORS[option.action_type] || ACTION_COLORS.hold_and_wait;

        return (
          <div
            key={option.intervention_id}
            className={`rounded-lg border ${borderColor} bg-zinc-900/50 p-4 transition-colors ${
              isCancelled ? "opacity-40" : ""
            }`}
          >
            <div className="flex items-start justify-between mb-2">
              <div>
                <div className="flex items-center gap-2">
                  <h4 className="font-semibold text-white text-sm">
                    {option.option_label}
                  </h4>
                  {isSelected && (
                    <span className="rounded-full bg-emerald-500/20 text-emerald-400 px-2 py-0.5 text-xs font-semibold">
                      SELECTED
                    </span>
                  )}
                </div>
                <p className="text-xs text-zinc-400 mt-1">
                  {option.option_description}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-4 gap-2 text-center">
              <div>
                <div className="text-sm font-bold text-red-400 font-mono">
                  {formatCents(option.estimated_cost_cents)}
                </div>
                <div className="text-xs text-zinc-600">Cost</div>
              </div>
              <div>
                <div className="text-sm font-bold text-emerald-400 font-mono">
                  {formatCents(option.estimated_savings_cents)}
                </div>
                <div className="text-xs text-zinc-600">Savings</div>
              </div>
              <div>
                <div className="text-sm font-bold text-white font-mono">
                  {formatNumber(option.shipments_saved_count)}
                </div>
                <div className="text-xs text-zinc-600">Saved</div>
              </div>
              <div>
                <div className="text-sm font-bold text-blue-400 font-mono">
                  {formatNumber(option.customer_notifications_count)}
                </div>
                <div className="text-xs text-zinc-600">Notified</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
