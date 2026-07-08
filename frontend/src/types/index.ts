export interface TokenRecord {
  id: number;
  timestamp: string;
  agent: string;
  model: string;
  session_id: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number;
}

export interface SummaryResponse {
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cache_tokens: number;
  cost_usd: number;
  call_count: number;
  breakdown: BreakdownItem[];
}

export interface BreakdownItem {
  agent: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number;
  call_count: number;
}

export interface UsageResponse {
  items: TokenRecord[];
  total: number;
  page: number;
}

export interface ModelInfo {
  model: string;
  input_price: number;
  output_price: number;
  cache_read_price: number;
  cache_write_price: number;
}

export type TimeRange = "today" | "7d" | "30d" | "custom";

export interface FilterState {
  range: TimeRange;
  from?: string;
  to?: string;
  agents: string[];
  models: string[];
}

export interface TrendPoint {
  date: string;
  name: string;
  total_tokens: number;
}

export interface TrendSeries {
  name: string;
  data: number[];
}

export interface TrendResponse {
  dates: string[];
  series: TrendSeries[];
}

export interface CacheRatioItem {
  agent: string;
  model: string;
  total_tokens: number;
  cache_read_tokens: number;
  cache_ratio: number;
}

export interface CacheRatioResponse {
  overall_cache_ratio: number;
  items: CacheRatioItem[];
}

// ── Quota Monitoring ──────────────────────────────────────

export interface QuotaWindow {
  used: number;
  total: number;
  remaining: number;
  ratio: number;
  unit: string;
  reset_at: string | null;
}

export interface ModelMultiplier {
  model: string;
  peak: number;
  off_peak: number;
  peak_hours: string;
}

export interface QuotaSnapshot {
  provider: string;
  display_name: string;
  plan_name: string;
  plan_type: string;
  main_window: QuotaWindow | null;
  extra_windows: QuotaWindow[];
  balance: number | null;
  free_balance: number | null;
  model_multipliers: ModelMultiplier[];
  expires_at: string | null;
  auto_renew: boolean | null;
  fetched_at: string;
  source: string; // "api" | "estimate" | "error"
  error: string | null;
}

export interface QuotaResponse {
  items: QuotaSnapshot[];
  total: number;
}

export interface ProviderInfo {
  provider_id: string;
  display_name: string;
  enabled: boolean;
  has_credential: boolean;
  plan_type: string;
}
