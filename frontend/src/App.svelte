<script lang="ts">
  import { onMount } from "svelte";
  import type { SummaryResponse, UsageResponse, FilterState, TimeRange, TrendResponse, CacheRatioResponse } from "./types";
  import { fetchSummary, fetchUsage, fetchAgents, fetchModels, fetchTrend, fetchCacheRatio, createEventSource } from "./api/client";
  import TimeRangeTabs from "./components/TimeRangeTabs.svelte";
  import StatCard from "./components/StatCard.svelte";
  import ComparisonChart from "./components/ComparisonChart.svelte";
  import TrendLine from "./components/TrendLine.svelte";
  import AgentPie from "./components/AgentPie.svelte";
  import ModelBar from "./components/ModelBar.svelte";
  import UsageTable from "./components/UsageTable.svelte";
  import FilterBar from "./components/FilterBar.svelte";
  import ModelPricing from "./components/ModelPricing.svelte";
  import CacheRatioChart from "./components/CacheRatioChart.svelte";

  let summary: SummaryResponse | null = $state(null);
  let agentBreakdown: SummaryResponse["breakdown"] = $state([]);
  let modelBreakdown: SummaryResponse["breakdown"] = $state([]);
  let trendByAgent: TrendResponse | null = $state(null);
  let trendByModel: TrendResponse | null = $state(null);
  let cacheByAgent: CacheRatioResponse | null = $state(null);
  let cacheByModel: CacheRatioResponse | null = $state(null);
  let cacheByAgentModel: CacheRatioResponse | null = $state(null);
  let usage: UsageResponse | null = $state(null);
  let agents: string[] = $state([]);
  let models: string[] = $state([]);
  let loading = $state(true);
  let error = $state("");
  let currentPage = $state(1);
  let pageSize = $state(50);
  let sseConnected = $state(true);

  let filter: FilterState = $state({
    range: "today",
    agents: [],
    models: [],
  });

  function localDateStr(d: Date): string {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function computeFromTo(range: TimeRange): { from?: string; to?: string } {
    if (range === "custom") return {};
    const now = new Date();
    const to = localDateStr(now);
    let from: string;
    switch (range) {
      case "today":
        from = to;
        break;
      case "7d": {
        const d = new Date(now);
        d.setDate(d.getDate() - 7);
        from = localDateStr(d);
        break;
      }
      case "30d": {
        const d = new Date(now);
        d.setDate(d.getDate() - 30);
        from = localDateStr(d);
        break;
      }
      default:
        from = to;
    }
    return { from, to };
  }

  function buildParams(): Record<string, string> {
    const p: Record<string, string> = { range: filter.range };
    const { from, to } = computeFromTo(filter.range);
    if (filter.range === "custom" && filter.from) {
      p.from = filter.from;
    } else if (from) {
      p.from = from;
    }
    if (filter.range === "custom" && filter.to) {
      p.to = filter.to;
    } else if (to) {
      p.to = to;
    }
    if (filter.agents.length > 0) p.agent = filter.agents.join(",");
    if (filter.models.length > 0) p.model = filter.models.join(",");
    return p;
  }

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
    loading = true;
    error = "";
    if (page !== undefined) currentPage = page;
    try {
      const params = buildParams();
      const [agentSum, modelSum, trendAgent, trendModel, usg, cacheAgent, cacheModel, cacheAM] = await Promise.all([
        fetchSummary({ ...params, group_by: "agent" }),
        fetchSummary({ ...params, group_by: "model" }),
        fetchTrend({ ...params, group_by: "agent", granularity: computeGranularity() }),
        fetchTrend({ ...params, group_by: "model", granularity: computeGranularity() }),
        fetchUsage({ ...params, page: String(currentPage), limit: String(pageSize) }),
        fetchCacheRatio({ ...params, view: "by_agent" }),
        fetchCacheRatio({ ...params, view: "by_model" }),
        fetchCacheRatio({ ...params, view: "by_agent_model" }),
      ]);
      summary = agentSum;
      agentBreakdown = agentSum.breakdown;
      modelBreakdown = modelSum.breakdown;
      trendByAgent = trendAgent;
      trendByModel = trendModel;
      cacheByAgent = cacheAgent;
      cacheByModel = cacheModel;
      cacheByAgentModel = cacheAM;
      usage = usg;
    } catch (e: any) {
      error = e.message || "数据加载失败";
    } finally {
      loading = false;
    }
  }

  async function loadMeta() {
    try {
      const [a, m] = await Promise.all([fetchAgents(), fetchModels()]);
      agents = a;
      models = m;
    } catch {
      // metadata is optional
    }
  }

  function handleRangeChange(range: TimeRange, from?: string, to?: string) {
    filter = { ...filter, range, from, to };
    currentPage = 1;
    loadData(1);
  }

  function handleFilterChange(agents: string[], models: string[]) {
    filter = { ...filter, agents, models };
    currentPage = 1;
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

  async function handleExport() {
    try {
      const params = buildParams();
      const res = await fetch(`/api/usage?${new URLSearchParams({ ...params, limit: "99999" })}`);
      if (!res.ok) throw new Error("导出失败");
      const data = await res.json();

      const header = "时间,Agent,模型,输入Token,输出Token,缓存Token,费用(CNY)";
      const rows = data.items.map((r: any) =>
        [
          `"${r.timestamp}"`,
          `"${r.agent}"`,
          `"${r.model}"`,
          r.input_tokens,
          r.output_tokens,
          r.cache_read_tokens + r.cache_write_tokens,
          (r.cost_usd * 7.25).toFixed(4),
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

  onMount(() => {
    loadData();
    loadMeta();

    const es = createEventSource(() => {
      loadData();
      sseConnected = true;
    });

    es.onerror = () => {
      sseConnected = false;
    };

    return () => es.close();
  });
</script>

<main class="min-h-screen bg-[var(--bg)] text-[var(--text)]" style="padding-bottom: 2rem;">
  <!-- Header -->
  <header class="header-bar">
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
      {#if loading && summary}
        <span class="text-xs text-[var(--text-3)] animate-pulse ml-2">刷新中...</span>
      {/if}
    </div>
    <TimeRangeTabs current={filter.range} onchange={handleRangeChange} />
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
    <div class="px-6 pt-2 pb-6 space-y-6">
      <!-- Agent Filter Tags -->
      <FilterBar
        {agents}
        {models}
        selectedAgents={filter.agents}
        selectedModels={filter.models}
        onchange={handleFilterChange}
      />

      <!-- Stat Cards -->
      <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
        <StatCard title="总 Token" value={summary.total_tokens} unit=""
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>' />
        <StatCard title="输入 Token" value={summary.input_tokens} unit=""
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--cyan)" stroke-width="2"><path d="M12 19V5M5 12l7-7 7 7"/></svg>' />
        <StatCard title="输出 Token" value={summary.output_tokens} unit=""
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2"><path d="M12 5v14M5 12l7 7 7-7"/></svg>' />
        <StatCard title="缓存 Token" value={summary.cache_tokens} unit=""
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--amber)" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M3 9h18"/></svg>' />
        <StatCard title="总费用" value={summary.cost_usd * 7.25} unit="¥" prefix={true}
          icon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>' />
        <StatCard title="请求次数" value={summary.call_count} unit="次"
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

      <!-- Pie + Model Bar -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <AgentPie breakdown={agentBreakdown} />
        <ModelBar breakdown={modelBreakdown} />
      </div>

      <!-- Usage Table -->
      {#if usage}
        <UsageTable
          items={usage.items}
          total={usage.total}
          page={usage.page}
          {pageSize}
          onPageChange={handlePageChange}
          onPageSizeChange={handlePageSizeChange}
          onExport={handleExport}
        />
      {/if}

      <!-- Model Pricing (collapsible) -->
      <ModelPricing />
    </div>
  {/if}
</main>

<style>
  .header-bar {
    border-bottom: 1px solid var(--border);
    padding: 14px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    background: var(--card);
    border-bottom: 1px solid var(--border);
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
</style>
