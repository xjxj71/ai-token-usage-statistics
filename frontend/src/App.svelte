<script lang="ts">
  import { onMount } from "svelte";
  import { uiState, setView } from "./ui.svelte.ts";
  import { cursorGlow } from "./motion";
  import type { SummaryResponse, UsageResponse, FilterState, TimeRange, TrendResponse, CacheRatioResponse, SessionsResponse, TokenRecord } from "./types";
  import { fetchSummary, fetchUsage, fetchAgents, fetchModels, fetchTrend, fetchCacheRatio, createEventSource, fetchConfig, fetchProjects, fetchSessions, refreshExchangeRate, fetchWithTimeout } from "./api/client";
  import { buildParams } from "./api/params";
  import { csvEscape } from "./utils/csv";
  import TimeRangeTabs from "./components/TimeRangeTabs.svelte";
  import ComparisonChart from "./components/ComparisonChart.svelte";
  import TrendLine from "./components/TrendLine.svelte";
  import UsageTable from "./components/UsageTable.svelte";
  import SessionTable from "./components/SessionTable.svelte";
  import FilterBar from "./components/FilterBar.svelte";
  import ModelPricing from "./components/ModelPricing.svelte";
  import CacheRatioChart from "./components/CacheRatioChart.svelte";
  import PlanQuotaCard from "./components/PlanQuotaCard.svelte";
  import ReportCard from "./components/ReportCard.svelte";
  import DataManagement from "./components/DataManagement.svelte";
  import ThemeSwitcher from "./components/ThemeSwitcher.svelte";
  import Sidebar from "./components/Sidebar.svelte";
  import BentoOverview from "./components/BentoOverview.svelte";
  import LiveMonitor from "./components/LiveMonitor.svelte";

  const view = $derived(uiState.view);
  const VIEW_META: Record<string, { title: string; sub: string }> = {
    overview: { title: "概览", sub: "关键指标一屏全览 · Bento" },
    trends: { title: "趋势分析", sub: "用量趋势 · Agent 对比 · 缓存率" },
    sessions: { title: "会话明细", sub: "按 Agent × 会话聚合 · 点击行展开请求" },
    records: { title: "使用记录", sub: "逐条请求明细 · 可搜索 / 导出" },
    monitor: { title: "实时监控", sub: "SSE 实时推送 · 新记录滑入高亮" },
    pricing: { title: "模型定价", sub: "模型单价维护 · 一键刷新" },
    data: { title: "数据管理", sub: "保留策略 · 清理 · 备份" },
  };
  const FILTER_VIEWS = new Set(["overview", "trends", "sessions", "records"]);

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

  let exporting = $state(false);

  async function handleExport() {
    if (exporting) return;
    exporting = true;
    error = "";
    try {
      const params = buildParams(filter);
      // /api/usage caps limit at 500 — page through the whole result set
      // instead of asking for limit=99999 (which 422s and exports nothing).
      const PAGE = 500;
      const items: TokenRecord[] = [];
      let page = 1;
      let total = Infinity;
      while (items.length < total) {
        const data = await fetchUsage({ ...params, page: String(page), limit: String(PAGE) });
        total = data.total;
        items.push(...data.items);
        if (data.items.length < PAGE) break;
        page += 1;
      }

      const header = "时间,Agent,模型,项目,输入Token,输出Token,思考Token,缓存Token,费用(CNY)";
      const rows = items.map((r) =>
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
      const csv = "﻿" + header + "\n" + rows.join("\n");

      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `token-export-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      error = `导出失败：${e.message || e}`;
    } finally {
      exporting = false;
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

    const es = createEventSource(
      () => {
        loadData();
        // New agents/models appear in the DB while the page is open —
        // refresh the filter lists too, not just the data.
        loadMeta();
      },
      () => {
        sseConnected = false;
      },
      () => {
        sseConnected = true;
      },
    );

    return () => es.close();
  });
</script>

<div class="shell" use:cursorGlow>
  <Sidebar current={view} onNavigate={setView} sseConnected={sseConnected} />

  <div class="shell-main">
    <header class="topbar">
      <div class="topbar-title">
        <h1>{VIEW_META[view].title}</h1>
        <span class="topbar-sub">{VIEW_META[view].sub}</span>
      </div>
      <div class="topbar-right">
        <div class="flex items-center gap-1.5">
          <div class="sse-dot {sseConnected ? 'connected' : 'disconnected'}"></div>
          <span class="text-[11px] text-[var(--text-3)]">{sseConnected ? '实时连接' : '连接断开'}</span>
        </div>
        <div class="flex items-center gap-1.5" title={rateSource === "live" ? "汇率来自实时行情" : "使用配置的静态汇率"}>
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
        <ThemeSwitcher />
        <TimeRangeTabs current={filter.range} onchange={handleRangeChange} />
        {#if loading && summary}
          <span class="text-xs text-[var(--text-3)] animate-pulse">刷新中...</span>
        {/if}
      </div>
    </header>

    {#if error}
      <div class="mx-6 mt-4 p-3 rounded-lg text-sm" style="background: rgba(var(--red-rgb), .1); border: 1px solid rgba(var(--red-rgb), .3); color: var(--red);">
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
      <div class="content">
        <div class:hidden={!FILTER_VIEWS.has(view)}>
          <FilterBar
            {agents}
            {models}
            {projects}
            selectedAgents={filter.agents}
            selectedModels={filter.models}
            selectedProjects={filter.projects}
            onchange={handleFilterChange}
          />
        </div>

        <!-- keep-alive：所有视图常驻 DOM，切换只改 hidden，图表不重建 -->
        <section class="view" class:hidden={view !== "overview"}>
            <BentoOverview
              {summary}
              cacheRatio={cacheByAgent?.overall_cache_ratio ?? 0}
              {agentBreakdown}
              {modelBreakdown}
              {projectBreakdown}
              {trendByAgent}
              usageItems={usage?.items ?? []}
              {usdToCnyRate}
            />
            <PlanQuotaCard />
            <ReportCard {filter} {usdToCnyRate} />
          </section>
        <section class="view" class:hidden={view !== "trends"}>
            <div class="grid2">
              <TrendLine data={trendByAgent} title="按 Agent 的 Token 用量趋势" />
              <TrendLine data={trendByModel} title="按模型的 Token 用量趋势" />
            </div>
            <ComparisonChart breakdown={agentBreakdown} />
            <CacheRatioChart
              byAgent={cacheByAgent?.items ?? []}
              byModel={cacheByModel?.items ?? []}
              byAgentModel={cacheByAgentModel?.items ?? []}
            />
          </section>
        <section class="view" class:hidden={view !== "sessions"}>
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
                filterKey={JSON.stringify(filter)}
              />
            {/if}
          </section>
        <section class="view" class:hidden={view !== "records"}>
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
          </section>
        <section class="view" class:hidden={view !== "monitor"}>
            <LiveMonitor
              items={usage?.items ?? []}
              {summary}
              cacheRatio={cacheByAgent?.overall_cache_ratio ?? 0}
              {agentBreakdown}
              {modelBreakdown}
              {usdToCnyRate}
              {sseConnected}
            />
          </section>
        <section class="view" class:hidden={view !== "pricing"}>
            <ModelPricing {usdToCnyRate} />
          </section>
        <section class="view" class:hidden={view !== "data"}>
          <DataManagement />
        </section>
      </div>
    {/if}
  </div>
</div>

<style>
  .shell {
    display: flex;
    min-height: 100vh;
    background: var(--bg);
    color: var(--text);
  }
  /* 页面级环境光：跟随鼠标的柔和光晕 */
  .shell::before {
    content: '';
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 0;
    background: radial-gradient(600px circle at var(--gx, 50%) var(--gy, 30%), rgba(var(--primary-rgb), 0.05), transparent 60%);
  }
  .hidden { display: none !important; }
  .shell-main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .topbar {
    position: sticky;
    top: 0;
    z-index: 15;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    flex-wrap: wrap;
    padding: 12px 24px;
    border-bottom: 1px solid var(--border);
    background: color-mix(in srgb, var(--card) 88%, transparent);
    backdrop-filter: blur(10px);
  }
  .topbar-title h1 { font-size: 17px; font-weight: 700; }
  .topbar-sub { font-size: 10.5px; color: var(--text-3); }
  .topbar-right { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  .content {
    width: 100%;
    max-width: 1800px;
    margin: 0 auto;
    padding: 16px 24px 40px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .view {
    display: flex;
    flex-direction: column;
    gap: 14px;
    /* display none→flex 时自动重放，keep-alive 切换的入场动效 */
    animation: view-in .34s cubic-bezier(.2, .7, .3, 1);
  }
  @keyframes view-in {
    from { opacity: 0; transform: translateX(20px) scale(.995); filter: blur(3px); }
  }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  @media (max-width: 1100px) { .grid2 { grid-template-columns: 1fr; } }

  .sse-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    animation: pulse-dot 2s infinite;
  }
  .sse-dot.connected { background: var(--green); }
  .sse-dot.disconnected { background: var(--red); animation: none; }
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
    border-color: rgba(var(--cyan-rgb), 0.4);
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