"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { createWebSocket } from "../lib/api";

interface WSEvent {
  type: string;
  [key: string]: unknown;
}

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<WSEvent | null>(null);
  const [events, setEvents] = useState<WSEvent[]>([]);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const connectRef = useRef<() => void>(() => {});

  const connect = useCallback(() => {
    try {
      const ws = createWebSocket();

      ws.onopen = () => {
        setConnected(true);
      };

      ws.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data) as WSEvent;
          setLastEvent(event);
          setEvents((prev) => [event, ...prev].slice(0, 100));
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        setConnected(false);
        // Reconnect after 2 seconds
        reconnectTimer.current = setTimeout(() => connectRef.current(), 2000);
      };

      ws.onerror = () => {
        ws.close();
      };

      wsRef.current = ws;
    } catch {
      // Connection failed, retry
      reconnectTimer.current = setTimeout(() => connectRef.current(), 2000);
    }
  }, []);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  const send = useCallback((data: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  return { connected, lastEvent, events, send };
}
