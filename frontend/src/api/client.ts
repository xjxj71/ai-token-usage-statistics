import type { SummaryResponse, UsageResponse, ModelInfo } from "../types";

const BASE = "/api";

export async function fetchSummary(params: Record<string, string>): Promise<SummaryResponse> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${BASE}/summary${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`汇总数据请求失败: ${res.status}`);
  return res.json();
}

export async function fetchUsage(params: Record<string, string>): Promise<UsageResponse> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${BASE}/usage${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`使用记录请求失败: ${res.status}`);
  return res.json();
}

export async function fetchModels(): Promise<string[]> {
  const res = await fetch(`${BASE}/models`);
  if (!res.ok) throw new Error(`模型列表请求失败: ${res.status}`);
  const data: ModelInfo[] = await res.json();
  return data.map((m) => m.model);
}

export async function fetchAgents(): Promise<string[]> {
  const res = await fetch(`${BASE}/agents`);
  if (!res.ok) throw new Error(`Agent 列表请求失败: ${res.status}`);
  return res.json();
}

export function createEventSource(onMessage: (data: unknown) => void): EventSource {
  const es = new EventSource(`${BASE}/stream`);

  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  const DEBOUNCE_MS = 3000;

  es.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data);
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        onMessage(parsed);
        debounceTimer = null;
      }, DEBOUNCE_MS);
    } catch {
      // ignore parse errors
    }
  };

  es.onerror = () => {
    // SSE connection lost — the browser will auto-reconnect,
    // but we clear any pending debounce to avoid stale calls.
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
  };

  return es;
}
