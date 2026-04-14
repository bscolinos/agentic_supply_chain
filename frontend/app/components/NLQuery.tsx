"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { api } from "../lib/api";

type AnalystResult = {
  sql: {
    command: string;
    confidence_score: number | null;
    tables_used: string[];
  } | null;
  data: {
    columns: string[];
    rows: unknown[][];
    row_count: number;
  } | null;
  chart: unknown;
  text: string | null;
  error: string | null;
};

type Message =
  | { role: "user"; content: string }
  | { role: "assistant"; results: AnalystResult[]; error?: string };

const example_prompts = [
  "How many healthcare shipments are at risk?",
  "What has our largest disruption been?",
  "What's the total cost of active disruptions?",
  "Which facilities are most affected?",
];

export default function NLQuery() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setLoading(true);

    try {
      const response = await api.query(trimmed);
      const results: AnalystResult[] = response.results ?? [];
      setMessages((prev) => [
        ...prev,
        { role: "assistant", results },
      ]);
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Request failed";
      setMessages((prev) => [
        ...prev,
        { role: "assistant", results: [], error: detail },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }, [loading]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  }

  function clearChat() {
    setMessages([]);
    inputRef.current?.focus();
  }

  return (
    <div className="flex flex-col h-96 rounded-xl border border-zinc-800 bg-zinc-900/50 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-zinc-800 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-zinc-300 uppercase tracking-wider">
            Ask NERVE
          </span>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clearChat}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            New conversation
          </button>
        )}
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <p className="text-sm text-zinc-500">
              Ask anything about your logistics network
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              {example_prompts.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => send(prompt)}
                  className="text-xs text-zinc-500 hover:text-zinc-200 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 rounded-lg px-3 py-1.5 transition-colors"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) =>
          msg.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-sm rounded-lg bg-blue-600 px-3 py-2 text-sm text-white">
                {msg.content}
              </div>
            </div>
          ) : (
            <div key={i} className="space-y-2">
              {msg.error ? (
                <div className="text-sm text-red-400 bg-red-500/10 rounded-lg px-3 py-2">
                  {msg.error}
                </div>
              ) : msg.results.length === 0 ? (
                <div className="text-sm text-zinc-500 px-1">No results returned.</div>
              ) : (
                msg.results.map((result, j) => (
                  <ResultBlock key={j} result={result} />
                ))
              )}
            </div>
          )
        )}

        {loading && (
          <div className="flex gap-1 items-center pl-1">
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-500 animate-pulse" />
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-500 animate-pulse [animation-delay:150ms]" />
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-500 animate-pulse [animation-delay:300ms]" />
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="border-t border-zinc-800 p-3 flex gap-2 shrink-0">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about shipments, disruptions, weather..."
          disabled={loading}
          className="flex-1 rounded-lg bg-zinc-800 border border-zinc-700 px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500 disabled:opacity-50"
        />
        <button
          onClick={() => send(input)}
          disabled={loading || !input.trim()}
          className="rounded-lg bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 px-4 py-2 text-sm font-semibold text-white transition-colors"
        >
          Send
        </button>
      </div>
    </div>
  );
}

function ResultBlock({ result }: { result: AnalystResult }) {
  if (result.error) {
    return (
      <div className="text-sm text-red-400 bg-red-500/10 rounded-lg px-3 py-2">
        {result.error}
      </div>
    );
  }

  const hasContent = result.text || result.sql || (result.data && result.data.rows.length > 0);

  if (!hasContent) {
    return (
      <div className="text-xs text-zinc-500 px-1">No data returned for this query.</div>
    );
  }

  return (
    <div className="space-y-2">
      {result.text && (
        <div className="text-sm text-zinc-300 bg-zinc-800/50 rounded-lg px-3 py-2 leading-relaxed">
          {result.text}
        </div>
      )}

      {result.sql && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-zinc-500 uppercase tracking-wider">SQL</span>
            {result.sql.confidence_score != null && (
              <span className="text-xs text-zinc-600">
                {Math.round(result.sql.confidence_score * 100)}% confidence
              </span>
            )}
          </div>
          <pre className="text-xs text-zinc-400 bg-zinc-800 rounded-lg p-2 overflow-x-auto whitespace-pre-wrap">
            {result.sql.command}
          </pre>
        </div>
      )}

      {result.data && result.data.rows.length > 0 && (
        <div className="overflow-x-auto max-h-48 overflow-y-auto rounded-lg border border-zinc-800">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-zinc-800 bg-zinc-800/50 sticky top-0">
                {result.data.columns.map((col) => (
                  <th
                    key={col}
                    className="text-left text-zinc-500 py-1.5 px-2 font-medium whitespace-nowrap"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.data.rows.slice(0, 20).map((row, i) => (
                <tr key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                  {(row as unknown[]).map((val, j) => (
                    <td key={j} className="text-zinc-300 py-1.5 px-2 font-mono whitespace-nowrap">
                      {val === null ? "\u2014" : String(val)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {result.data.row_count > 20 && (
            <div className="text-xs text-zinc-500 text-center py-1.5 bg-zinc-800/30">
              Showing 20 of {result.data.row_count} rows
            </div>
          )}
        </div>
      )}

      {result.data && result.data.rows.length === 0 && !result.text && (
        <div className="text-xs text-zinc-500 text-center py-2">No rows returned.</div>
      )}
    </div>
  );
}
