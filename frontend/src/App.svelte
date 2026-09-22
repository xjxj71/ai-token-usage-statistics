<script lang="ts">
  import { onMount } from "svelte";
  import type { SummaryResponse, SummaryTotals, UsageResponse, FilterState, TimeRange, TrendResponse, CacheRatioResponse, SessionsResponse, TokenRecord } from "./types";
  import { fetchSummary, fetchUsage, fetchAgents, fetchModels, fetchTrend, fetchCacheRatio, createEventSource, fetchConfig, fetchProjects, fetchSessions, refreshExchangeRate, fetchWithTimeout } from "./api/client";
  import { buildParams } from "./api/params";
  import { csvEscape } from "./utils/csv";
  import TimeRangeTabs from "./components/TimeRangeTabs.svelte";
  import StatCard from "./components/StatCard.svelte";
  import ComparisonChart from "./components/ComparisonChart.svelte";
  import TrendLine from "./components/TrendLine.svelte";
  import AgentPie from "./components/AgentPie.svelte";
  import ModelBar from "./components/ModelBar.svelte";
  import ProjectBar from "./components/ProjectBar.svelte";
  import UsageTable from "./components/UsageTable.svelte";
  import SessionTable from "./components/SessionTable.svelte";
  import FilterBar from "./components/FilterBar.svelte";
  import ModelPricing from "./components/ModelPricing.svelte";
  import CacheRatioChart from "./components/CacheRatioChart.svelte";
  import PlanQuotaCard from "./components/PlanQuotaCard.svelte";
  import ReportCard from "./components/ReportCard.svelte";
  import DataManagement from "./components/DataManagement.svelte";

  let summary: SummaryResponse | null = $state(null);
  let agentBreakdown: SummaryResponse["breakdown"] = $state([]);
  let modelBreakdown: SummaryResponse["breakdown"] = $state([]);
  let projectBreakdown: SummaryResponse["breakdown"] = $state([]);
  let trendByAgent: TrendResponse | null = $state(null);
  let trendByModel: TrendResponse | null = $state(null);
  let cacheByAgent: CacheRatioResponse | null = $state(null);
  let cacheByModel: CacheRatioResponse | null = $state(null);
  let cacheByAgentModel: CacheRatioResponse | null = $state(null);
  let usage: UsageResponse | null = $state(null);
  let sessions: SessionsResponse | null = $state(null);
  let agents: string[] = $state([]);
  let models: string[] = $state([]);
  let projects: string[] = $state([]);
  let loading = $state(true);
  let error = $state("");
  let currentPage = $state(1);
  let pageSize = $state(50);
  let sessionPage = $state(1);
  let sessionPageSize = $state(20);
  let sseConnected = $state(false);
  let loadSeq = 0;
  let usdToCnyRate = $state(7.25); // Default, will be updated from config
  let rateSource = $state("");
  let rateRefreshing = $state(false);
  let rateError = $state("");

  let filter: FilterState = $state({
    range: "today",
    agents: [],
    models: [],
    projects: [],
  });

  function computeGranularity(): string {
    if (filter.range === "today") return "hour";
    if (filter.range === "custom" && filter.from && filter.to) {
      const from = new Date(filter.from);
      const to = new Date(filter.to);
      const diffDays = (to.getTime() - from.getTime()) / (1000 * 60 * 60 * 24);
      if (diffDays <= 1) return "hour";
    }
    return "day";
  }

  async function loadData(page?: number) {
    const seq = ++loadSeq;
    loading = true;
    error = "";
    if (page !== undefined) currentPage = page;
    try {
      const params = buildParams(filter);
      const [agentSum, modelSum, projectSum, trendAgent, trendModel, usg, sess, cacheAgent, cacheModel, cacheAM] = await Promise.all([
        fetchSummary({ ...params, group_by: "agent", compare: "true" }),
        fetchSummary({ ...params, group_by: "model" }),
        fetchSummary({ ...params, group_by: "project" }),
        fetchTrend({ ...params, group_by: "agent", granularity: computeGranularity() }),
        fetchTrend({ ...params, group_by: "model", granularity: computeGranularity() }),
        fetchUsage({ ...params, page: String(currentPage), limit: String(pageSize) }),
        fetchSessions({ ...params, page: String(sessionPage), limit: String(sessionPageSize) }),
        fetchCacheRatio({ ...params, view: "by_agent" }),
        fetchCacheRatio({ ...params, view: "by_model" }),
        fetchCacheRatio({ ...params, view: "by_agent_model" }),
      ]);
      if (seq !== loadSeq) return;
      summary = agentSum;
      agentBreakdown = agentSum.breakdown;
      modelBreakdown = modelSum.breakdown;
      projectBreakdown = projectSum.breakdown;
      trendByAgent = trendAgent;
      trendByModel = trendModel;
      cacheByAgent = cacheAgent;
      cacheByModel = cacheModel;
      cacheByAgentModel = cacheAM;
      usage = usg;
      sessions = sess;
    } catch (e: any) {
      if (seq !== loadSeq) return;
      error = e.message || "数据加载失败";
    } finally {
      if (seq === loadSeq) loading = false;
    }
  }

  async function loadMeta() {
    try {
      const [a, m, p] = await Promise.all([fetchAgents(), fetchModels(), fetchProjects()]);
      agents = a;
      models = m;
      projects = p;
    } catch {
      // metadata is optional
    }
  }

  function handleRangeChange(range: TimeRange, from?: string, to?: string) {
    filter = { ...filter, range, from, to };
    currentPage = 1;
    sessionPage = 1;
    loadData(1);
  }

  function handleFilterChange(agents: string[], models: string[], projects: string[]) {
    filter = { ...filter, agents, models, projects };
    currentPage = 1;
    sessionPage = 1;
    loadData(1);
  }

  function handlePageChange(page: number) {
    loadData(page);
  }

  function handlePageSizeChange(size: number) {
    pageSize = size;
    currentPage = 1;
    loadData(1);
  }

  function handleSessionPageChange(page: number) {
    sessionPage = page;
    loadData();
  }

  function handleSessionPageSizeChange(size: number) {
    sessionPageSize = size;
    sessionPage = 1;
    loadData();
  }

  function delta(cur: number, prev: number | undefined | null): number | undefined {
    // Previous period had no usage → a ratio would be meaningless; hide the badge.
    if (prev === undefined || prev === null || prev === 0) return undefined;
    return Math.round(((cur - prev) / prev) * 1000) / 10;
  }

  function totalsDelta(key: keyof SummaryTotals): number | undefined {
    if (!summary?.previous) return undefined;
    return delta(summary[key] as number, summary.previous![key] as number);
  }

  async function loadSessionDetail(agent: string, sessionId: string): Promise<TokenRecord[]> {
    const params = buildParams(filter);
    const data = await fetchUsage({
      ...params,
      agent,
      session_id: sessionId,
      page: "1",
      limit: "200",
    });
    // /api/usage returns newest-first; show the session chronologically
    return [...data.items].reverse();
  }

  async function handleExport() {
    try {
      const params = buildParams(filter);
      const res = await fetchWithTimeout(`/api/usage?${new URLSearchParams({ ...params, limit: "99999" })}`);
      if (!res.ok) throw new Error("导出失败");
      const data = await res.json();

      const header = "时间,Agent,模型,项目,输入Token,输出Token,思考Token,缓存Token,费用(CNY)";
      const rows = data.items.map((r: any) =>
        [
          csvEscape(r.timestamp),
          csvEscape(r.agent),
          csvEscape(r.model),
          csvEscape(r.project ?? ""),
          r.input_tokens,
          r.output_tokens,
          r.reasoning_tokens ?? 0,
          r.cache_read_tokens + r.cache_write_tokens,
          (r.cost_usd * usdToCnyRate).toFixed(4),
        ].join(",")
      );
      const csv = "\uFEFF" + header + "\n" + rows.join("\n");

      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `token-export-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      console.warn("导出失败:", e);
    }
  }

  async function loadConfig() {
    try {
      const config = await fetchConfig();
      usdToCnyRate = config.usd_to_cny_rate;
      rateSource = config.rate_source;
    } catch {
      // Use default rate if config fetch fails
    }
  }

  async function handleRateRefresh() {
    rateRefreshing = true;
    rateError = "";
    try {
      const config = await refreshExchangeRate();
      usdToCnyRate = config.usd_to_cny_rate;
      rateSource = config.rate_source;
    } catch (e: any) {
      rateError = e.message || "刷新汇率失败";
    } finally {
      rateRefreshing = false;
    }
  }

  onMount(() => {
    loadData();
    loadMeta();
    loadConfig();

    const es = createEventSource(() => {
      loadData();
      // New agents/models appear in the DB while the page is open —
      // refresh the filter lists too, not just the data.
      loadMeta();
      sseConnected = true;
    }, () => {
      sseConnected = false;
    });

    return () => es.close();
  });
</script>

<main class="min-h-screen bg-[var(--bg)] text-[var(--text)]" style="padding-bottom: 2rem;">
  <!-- Header -->
  <header class="header-bar">
    <div class="header-inner">
      <div class="flex items-center gap-3">
      <div class="flex items-center gap-2.5">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--cyan)" stroke-width="2">
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
        </svg>
        <h1 class="text-lg font-bold">AI Token 用量统计</h1>
      </div>
      <div class="flex items-center gap-1.5 ml-2">
        <div class="sse-dot {sseConnected ? 'connected' : 'disconnected'}"></div>
        <span class="text-[11px] text-[var(--text-3)]">{sseConnected ? '实时连接' : '连接断开'}</span>
      </div>
      <div class="flex items-center gap-1.5 ml-3" title={rateSource === "live" ? "汇率来自实时行情" : "使用配置的静态汇率"}>
        <span class="text-[11px] text-[var(--text-3)]">1 USD = ¥{usdToCnyRate.toFixed(2)}</span>
        <span class="rate-tag {rateSource === 'live' ? 'live' : ''}">{rateSource === "live" ? "实时" : "静态"}</span>
        <button class="rate-refresh" onclick={handleRateRefresh} disabled={rateRefreshing} title="刷新汇率">
          {#if rateRefreshing}
            <svg class="animate-spin" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--cyan)" stroke-width="2"><path d="M21 12a9 9 0 11-6.219-8.56"/></svg>
          {:else}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 11-2.64-6.36M21 3v6h-6"/></svg>
          {/if}
        </button>
        {#if rateError}
          <span class="text-[11px] text-[var(--red)]">{rateError}</span>
        {/if}
      </div>
      {#if loading && summary}
        <span class="text-xs text-[var(--text-3)] animate-pulse ml-2">刷新中...</span>
      {/if}
    </div>
      <TimeRangeTabs current={filter.range} onchange={handleRangeChange} />
    </div>
  </header>

  {#if error}
    <div class="mx-6 mt-4 p-3 bg-red-900/30 border border-red-800 rounded-lg text-red-300 text-sm">
      {error}
    </div>
  {/if}

  {#if loading && !summary}
    <div class="flex flex-col items-center justify-center h-64 text-[var(--text-3)] gap-3">
      <svg class="animate-spin h-8 w-8" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span>加载中...</span>
    </div>
  {:else if summary}
    <div class="px-6 pt-2 pb-6 space-y-6 mx-auto w-full max-w-[1800px]">
      <!-- Plan Quota Monitor -->
      <PlanQuotaCard />

      <!-- Usage Report (collapsible) -->
      <ReportCard {filter} {usdToCnyRate} />

      <!-- Agent Filter Tags -->
      <FilterBar
        {agents}
        {models}
        {projects}
        selectedAgents={filter.agents}
        selectedModels={filter.models}
        selectedProjects={filter.projects}
        onchange={handleFilterChange}
      />

      <!-- Stat Cards: 8 列仅在 ≥1536px（1080p/2160p 桌面）启用；720p(1280) 及以下保持 4 列，避免涨幅标签折行 -->
      <div class="grid grid-cols-2 md:grid-cols-4 2xl:grid-cols-8 gap-4">
        <StatCard title="总 Token" value={summary.total_tokens} unit="" trend={totalsDelta("total_tokens")}
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>' />
        <StatCard title="输入 Token" value={summary.input_tokens} unit="" trend={totalsDelta("input_tokens")}
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--cyan)" stroke-width="2"><path d="M12 19V5M5 12l7-7 7 7"/></svg>' />
        <StatCard title="输出 Token" value={summary.output_tokens} unit="" trend={totalsDelta("output_tokens")}
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2"><path d="M12 5v14M5 12l7 7 7-7"/></svg>' />
        <StatCard title="思考 Token" value={summary.reasoning_tokens} unit="" trend={totalsDelta("reasoning_tokens")}
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--pink)" stroke-width="2"><path d="M9 18h6M10 22h4M12 2a7 7 0 00-4 12.7c.6.5 1 1.4 1 2.3h6c0-.9.4-1.8 1-2.3A7 7 0 0012 2z"/></svg>' />
        <StatCard title="缓存 Token" value={summary.cache_tokens} unit="" trend={totalsDelta("cache_tokens")}
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--amber)" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M3 9h18"/></svg>' />
        <StatCard title="总费用" value={summary.cost_usd * usdToCnyRate} unit="¥" prefix={true} goodWhenDown={true} trend={totalsDelta("cost_usd")}
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>' />
        <StatCard title="请求次数" value={summary.call_count} unit="次" trend={totalsDelta("call_count")}
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--purple)" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>' />
        <StatCard title="缓存命中率" value={cacheByAgent ? cacheByAgent.overall_cache_ratio * 100 : 0} unit="%"
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="M12 6v6l4 2"/></svg>' />
      </div>

      <!-- Trend Charts -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <TrendLine data={trendByAgent} title="按 Agent 的 Token 用量趋势" />
        <TrendLine data={trendByModel} title="按模型的 Token 用量趋势" />
      </div>

      <!-- Stacked Bar -->
      <ComparisonChart breakdown={agentBreakdown} />

      <!-- Cache Ratio Analysis -->
      <CacheRatioChart
        byAgent={cacheByAgent?.items ?? []}
        byModel={cacheByModel?.items ?? []}
        byAgentModel={cacheByAgentModel?.items ?? []}
      />

      <!-- Pie + Model Bar + Project Bar (full width) -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <AgentPie breakdown={agentBreakdown} />
        <ModelBar breakdown={modelBreakdown} />
        <div class="lg:col-span-2">
          <ProjectBar breakdown={projectBreakdown} />
        </div>
      </div>

      <!-- Session Table (drill-down) -->
      {#if sessions}
        <SessionTable
          items={sessions.items}
          total={sessions.total}
          page={sessions.page}
          pageSize={sessionPageSize}
          {usdToCnyRate}
          loadDetail={loadSessionDetail}
          onPageChange={handleSessionPageChange}
          onPageSizeChange={handleSessionPageSizeChange}
        />
      {/if}

      <!-- Usage Table -->
      {#if usage}
        <UsageTable
          items={usage.items}
          total={usage.total}
          page={usage.page}
          {pageSize}
          {usdToCnyRate}
          onPageChange={handlePageChange}
          onPageSizeChange={handlePageSizeChange}
          onExport={handleExport}
        />
      {/if}

      <!-- Model Pricing (collapsible) -->
      <ModelPricing {usdToCnyRate} />

      <!-- Data Management (collapsible) -->
      <DataManagement />
    </div>
  {/if}
</main>

<style>
  .header-bar {
    border-bottom: 1px solid var(--border);
    padding: 14px 24px;
    background: var(--card);
  }
  /* 4K/超宽屏下头部内容与主体内容一致限宽居中 */
  .header-inner {
    max-width: 1800px;
    margin: 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
  }
  .sse-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    animation: pulse-dot 2s infinite;
  }
  .sse-dot.connected {
    background: var(--green);
  }
  .sse-dot.disconnected {
    background: var(--red);
    animation: none;
  }
  @keyframes pulse-dot {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  .rate-tag {
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 9999px;
    border: 1px solid var(--border);
    color: var(--text-3);
  }
  .rate-tag.live {
    border-color: rgba(34, 211, 238, 0.4);
    color: var(--cyan);
  }
  .rate-refresh {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    transition: all 0.2s;
  }
  .rate-refresh:hover:not(:disabled) {
    border-color: var(--cyan);
    color: var(--cyan);
  }
  .rate-refresh:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
