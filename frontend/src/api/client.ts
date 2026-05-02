import type { SummaryResponse, UsageResponse, ModelInfo } from "../types";

const BASE = "/api";

export async function fetchSummary(params: Record<string, string>): Promise<SummaryResponse> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${BASE}/summary?${qs}`);
  if (!res.ok) throw new Error(`Summary fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchUsage(params: Record<string, string>): Promise<UsageResponse> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${BASE}/usage?${qs}`);
  if (!res.ok) throw new Error(`Usage fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchModels(): Promise<ModelInfo[]> {
  const res = await fetch(`${BASE}/models`);
  if (!res.ok) throw new Error(`Models fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchAgents(): Promise<string[]> {
  const res = await fetch(`${BASE}/agents`);
  if (!res.ok) throw new Error(`Agents fetch failed: ${res.status}`);
  return res.json();
}

export function createEventSource(onMessage: (data: unknown) => void): EventSource {
  const es = new EventSource(`${BASE}/stream`);
  es.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data));
    } catch {
      // ignore parse errors
    }
  };
  return es;
}
