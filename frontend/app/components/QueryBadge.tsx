"use client";

interface QueryBadgeProps {
  queryMs: number;
  detail?: string;
}

export default function QueryBadge({ queryMs, detail }: QueryBadgeProps) {
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs text-emerald-400 font-mono">
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
      {detail && <span className="text-emerald-400/70">{detail}</span>}
      <span className="font-semibold">{queryMs.toFixed(0)}ms</span>
    </div>
  );
}
