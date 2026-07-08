import type { SummaryResponse, UsageResponse, ModelInfo, TrendResponse, CacheRatioResponse, QuotaResponse, ProviderInfo } from "../types";

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
  return (await res.json()) as SummaryResponse;
}

export async function fetchUsage(params: Record<string, string>): Promise<UsageResponse> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetchWithTimeout(`${BASE}/usage${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`使用记录请求失败: ${res.status}`);
  return (await res.json()) as UsageResponse;
}

export async function fetchModels(): Promise<string[]> {
  const res = await fetchWithTimeout(`${BASE}/models`);
  if (!res.ok) throw new Error(`模型列表请求失败: ${res.status}`);
  const data = (await res.json()) as ModelInfo[];
  return data.map(m => m.model);
}

export async function fetchAgents(): Promise<string[]> {
  const res = await fetchWithTimeout(`${BASE}/agents`);
  if (!res.ok) throw new Error(`Agent 列表请求失败: ${res.status}`);
  return (await res.json()) as string[];
}

export function createEventSource(
  onMessage: (data: unknown) => void,
  onError?: () => void,
): EventSource {
  const es = new EventSource(`${BASE}/stream`);

  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  const DEBOUNCE_MS = 3000;

  es.addEventListener("message", (event: MessageEvent) => {
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
  });

  es.addEventListener("error", () => {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    onError?.();
  });

  return es;
}

export async function fetchTrend(params: Record<string, string>): Promise<TrendResponse> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetchWithTimeout(`${BASE}/trend${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`趋势数据请求失败: ${res.status}`);
  return (await res.json()) as TrendResponse;
}

export async function fetchCacheRatio(params: Record<string, string>): Promise<CacheRatioResponse> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetchWithTimeout(`${BASE}/cache-ratio${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`缓存率数据请求失败: ${res.status}`);
  return (await res.json()) as CacheRatioResponse;
}

export async function fetchQuota(): Promise<QuotaResponse> {
  const res = await fetchWithTimeout(`${BASE}/quota`);
  if (!res.ok) throw new Error(`套餐余量请求失败: ${res.status}`);
  return (await res.json()) as QuotaResponse;
}

export async function refreshQuota(): Promise<QuotaResponse> {
  const res = await fetchWithTimeout(`${BASE}/quota/refresh`, { method: "POST" });
  if (!res.ok) throw new Error(`刷新套餐余量失败: ${res.status}`);
  return (await res.json()) as QuotaResponse;
}

export async function fetchProviders(): Promise<ProviderInfo[]> {
  const res = await fetchWithTimeout(`${BASE}/quota/providers`);
  if (!res.ok) throw new Error(`Provider 列表请求失败: ${res.status}`);
  return (await res.json()) as ProviderInfo[];
}

export async function updateProviderConfig(
  provider: string,
  config: Partial<{ enabled: boolean; plan_type: string; session_token: string }>,
): Promise<{ status: string }> {
  const res = await fetchWithTimeout(`${BASE}/quota/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, ...config }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "更新配置失败");
  }
  return (await res.json()) as { status: string };
}
