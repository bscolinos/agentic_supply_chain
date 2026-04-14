const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

export async function fetchAPI(path: string, options?: RequestInit) {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function postAPI(path: string, body?: unknown) {
  return fetchAPI(path, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });
}

export function streamAPI(path: string): EventSource {
  return new EventSource(`${API_URL}${path}`);
}

export function createWebSocket(): WebSocket {
  return new WebSocket(`${WS_URL}/ws/events`);
}

// API endpoints
export const api = {
  healthPulse: () => fetchAPI("/api/health-pulse"),
  status: () => fetchAPI("/api/status"),
  metrics: () => fetchAPI("/api/metrics"),
  disruptions: () => fetchAPI("/api/disruptions"),
  disruption: (id: number) => fetchAPI(`/api/disruptions/${id}`),
  explainDisruption: (id: number) =>
    fetch(`${API_URL}/api/explain/disruption/${id}`),
  triggerDetection: () => postAPI("/api/disruptions/detect"),
  generateInterventions: (disruptionId: number) =>
    postAPI(`/api/interventions/generate/${disruptionId}`),
  executeIntervention: (interventionId: number) =>
    postAPI(`/api/interventions/execute/${interventionId}`),
  interventionStatus: (disruptionId: number) =>
    fetchAPI(`/api/interventions/status/${disruptionId}`),
  savingsReport: (interventionId: number) =>
    fetchAPI(`/api/interventions/savings/${interventionId}`),
  query: (question: string) => postAPI("/api/query", { question }),
};

export function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}
