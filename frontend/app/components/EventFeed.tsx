"use client";

interface Event {
  type: string;
  tracking_number?: string;
  event_type?: string;
  facility_code?: string;
  description?: string;
  timestamp?: string;
  [key: string]: unknown;
}

interface EventFeedProps {
  events: Event[];
  connected: boolean;
}

const EVENT_COLORS: Record<string, string> = {
  shipment_event: "text-zinc-400",
  disruption_detected: "text-amber-400",
  interventions_ready: "text-blue-400",
  intervention_executed: "text-emerald-400",
  scenario_event: "text-purple-400",
};

const EVENT_ICONS: Record<string, string> = {
  departure_scan: "↗",
  arrival_scan: "↙",
  in_transit: "→",
  out_for_delivery: "🚚",
  delivered: "✓",
  reroute: "↺",
  weather_hold: "⚠",
  disruption_detected: "🔴",
  interventions_ready: "📋",
  intervention_executed: "✅",
  scenario_event: "▶",
};

export default function EventFeed({ events, connected }: EventFeedProps) {
  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-4 py-2 border-b border-zinc-800">
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">
          Live Event Feed
        </h3>
        <div className="flex items-center gap-1.5">
          <span
            className={`h-2 w-2 rounded-full ${
              connected ? "bg-emerald-400 animate-pulse" : "bg-red-400"
            }`}
          />
          <span className="text-xs text-zinc-500">
            {connected ? "Connected" : "Disconnected"}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {events.length === 0 ? (
          <div className="text-center text-zinc-600 text-sm py-8">
            Waiting for events...
          </div>
        ) : (
          events.map((event, i) => {
            const color = EVENT_COLORS[event.type] || "text-zinc-500";
            const icon =
              EVENT_ICONS[event.event_type as string] ||
              EVENT_ICONS[event.type] ||
              "•";

            return (
              <div
                key={`${event.timestamp}-${i}`}
                className={`flex items-start gap-2 rounded px-2 py-1 text-xs font-mono ${color} hover:bg-zinc-800/50`}
              >
                <span className="shrink-0 w-4 text-center">{icon}</span>
                <span className="flex-1 truncate">
                  {event.tracking_number && (
                    <span className="text-zinc-400 mr-1">
                      {event.tracking_number}
                    </span>
                  )}
                  {String(event.description ||
                    event.event_type ||
                    (event as Record<string, unknown>).event ||
                    event.type || "")}
                </span>
                {event.facility_code && (
                  <span className="shrink-0 text-zinc-600">
                    {event.facility_code as string}
                  </span>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
