import type { SummaryResponse, UsageResponse, ModelInfo, TrendResponse } from "../types";

const BASE = "/api";
const FETCH_TIMEOUT_MS = 15_000;

async function fetchWithTimeout(url: string, options: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`请求超时 (${FETCH_TIMEOUT_MS / 1000}s)`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function fetchSummary(params: Record<string, string>): Promise<SummaryResponse> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetchWithTimeout(`${BASE}/summary${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`汇总数据请求失败: ${res.status}`);
  return res.json();
}

export async function fetchUsage(params: Record<string, string>): Promise<UsageResponse> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetchWithTimeout(`${BASE}/usage${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`使用记录请求失败: ${res.status}`);
  return res.json();
}

export async function fetchModels(): Promise<string[]> {
  const res = await fetchWithTimeout(`${BASE}/models`);
  if (!res.ok) throw new Error(`模型列表请求失败: ${res.status}`);
  const data: ModelInfo[] = await res.json();
  return data.map((m) => m.model);
}

export async function fetchAgents(): Promise<string[]> {
  const res = await fetchWithTimeout(`${BASE}/agents`);
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
    } catch (e: unknown) {
      console.warn("SSE parse error:", e);
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

export async function fetchTrend(params: Record<string, string>): Promise<TrendResponse> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetchWithTimeout(`${BASE}/trend${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`趋势数据请求失败: ${res.status}`);
  return res.json();
}
