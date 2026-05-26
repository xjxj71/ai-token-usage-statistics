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
