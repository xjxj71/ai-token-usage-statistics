import type { SummaryResponse, UsageResponse, ModelInfo, TrendResponse, CacheRatioResponse, QuotaResponse, ProviderInfo, SessionsResponse, ReportResponse } from "../types";

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

export async function fetchSessions(params: Record<string, string>): Promise<SessionsResponse> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetchWithTimeout(`${BASE}/sessions${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`会话列表请求失败: ${res.status}`);
  return (await res.json()) as SessionsResponse;
}

export async function fetchReport(params: Record<string, string>): Promise<ReportResponse> {
  const qs = new URLSearchParams(params).toString();
  const res = await fetchWithTimeout(`${BASE}/report${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`报告请求失败: ${res.status}`);
  return (await res.json()) as ReportResponse;
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

export async function fetchProjects(): Promise<string[]> {
  const res = await fetchWithTimeout(`${BASE}/projects`);
  if (!res.ok) throw new Error(`项目列表请求失败: ${res.status}`);
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

export interface ConfigResponse {
  usd_to_cny_rate: number;
  rate_source: string;
  rate_updated_at: string | null;
}

export async function fetchConfig(): Promise<ConfigResponse> {
  const res = await fetchWithTimeout(`${BASE}/config`);
  if (!res.ok) throw new Error(`配置请求失败: ${res.status}`);
  return (await res.json()) as ConfigResponse;
}

export async function refreshExchangeRate(): Promise<ConfigResponse> {
  const res = await fetchWithTimeout(`${BASE}/config/exchange-rate/refresh`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "刷新汇率失败");
  }
  return (await res.json()) as ConfigResponse;
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

// ── Data management (retention / backups) ────────────────────

export interface DataSettings {
  retention_days: number;
  backup_keep: number;
  auto_backup: boolean;
}

export interface BackupInfo {
  name: string;
  size_bytes: number;
  created_at: string;
}

async function parseErr(res: Response, fallback: string): Promise<Error> {
  const err = await res.json().catch(() => ({ detail: res.statusText }));
  return new Error(err.detail || fallback);
}

export async function fetchDataSettings(): Promise<DataSettings> {
  const res = await fetchWithTimeout(`${BASE}/config/data`);
  if (!res.ok) throw await parseErr(res, "数据管理配置请求失败");
  return (await res.json()) as DataSettings;
}

export async function updateDataSettings(
  settings: Partial<DataSettings>,
): Promise<{ status: string; settings: DataSettings }> {
  const res = await fetchWithTimeout(`${BASE}/config/data`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!res.ok) throw await parseErr(res, "保存设置失败");
  return (await res.json()) as { status: string; settings: DataSettings };
}

export async function createBackup(): Promise<BackupInfo> {
  const res = await fetchWithTimeout(`${BASE}/backup`, { method: "POST" });
  if (!res.ok) throw await parseErr(res, "备份失败");
  return (await res.json()).backup;
}

export async function fetchBackups(): Promise<BackupInfo[]> {
  const res = await fetchWithTimeout(`${BASE}/backups`);
  if (!res.ok) throw await parseErr(res, "备份列表请求失败");
  return (await res.json()).items;
}

export async function deleteBackup(name: string): Promise<void> {
  const res = await fetchWithTimeout(`${BASE}/backups/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw await parseErr(res, "删除备份失败");
}

export interface CleanupResult {
  retention_days?: number;
  cutoff?: string;
  archived_rows?: number;
  deleted_rows?: number;
  disabled?: boolean;
}

export async function runCleanup(days?: number): Promise<CleanupResult> {
  const qs = days ? `?days=${days}` : "";
  const res = await fetchWithTimeout(`${BASE}/maintenance/cleanup${qs}`, { method: "POST" });
  if (!res.ok) throw await parseErr(res, "清理失败");
  return (await res.json()).result;
}
