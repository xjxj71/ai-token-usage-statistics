<script lang="ts">
  import { onMount } from "svelte";
  import type { SummaryResponse, UsageResponse, FilterState, TimeRange, TrendResponse } from "./types";
  import { fetchSummary, fetchUsage, fetchAgents, fetchModels, fetchTrend, createEventSource } from "./api/client";
  import TimeRangeTabs from "./components/TimeRangeTabs.svelte";
  import StatCard from "./components/StatCard.svelte";
  import ComparisonChart from "./components/ComparisonChart.svelte";
  import TrendLine from "./components/TrendLine.svelte";
  import AgentPie from "./components/AgentPie.svelte";
  import ModelBar from "./components/ModelBar.svelte";
  import UsageTable from "./components/UsageTable.svelte";
  import FilterBar from "./components/FilterBar.svelte";
  import ModelPricing from "./components/ModelPricing.svelte";

  let summary: SummaryResponse | null = $state(null);
  let agentBreakdown: SummaryResponse["breakdown"] = $state([]);
  let modelBreakdown: SummaryResponse["breakdown"] = $state([]);
  let trendByAgent: TrendResponse | null = $state(null);
  let trendByModel: TrendResponse | null = $state(null);
  let usage: UsageResponse | null = $state(null);
  let agents: string[] = $state([]);
  let models: string[] = $state([]);
  let loading = $state(true);
  let error = $state("");
  let currentPage = $state(1);
  const PAGE_SIZE = 50;

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
      const [agentSum, modelSum, trendAgent, trendModel, usg] = await Promise.all([
        fetchSummary({ ...params, group_by: "agent" }),
        fetchSummary({ ...params, group_by: "model" }),
        fetchTrend({ ...params, group_by: "agent", granularity: computeGranularity() }),
        fetchTrend({ ...params, group_by: "model", granularity: computeGranularity() }),
        fetchUsage({ ...params, page: String(currentPage), limit: String(PAGE_SIZE) }),
      ]);
      summary = agentSum;
      agentBreakdown = agentSum.breakdown;
      modelBreakdown = modelSum.breakdown;
      trendByAgent = trendAgent;
      trendByModel = trendModel;
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

  async function handleExport() {
    try {
      const params = buildParams();
      const res = await fetch(`/api/usage?${new URLSearchParams({ ...params, limit: "99999" })}`);
      if (!res.ok) throw new Error("导出失败");
      const data = await res.json();

      const header = "时间,Agent,模型,输入Token,输出Token,缓存Token,费用(USD)";
      const rows = data.items.map((r: any) =>
        [
          `"${r.timestamp}"`,
          `"${r.agent}"`,
          `"${r.model}"`,
          r.input_tokens,
          r.output_tokens,
          r.cache_read_tokens + r.cache_write_tokens,
          r.cost_usd.toFixed(6),
        ].join(",")
      );
      const csv = "\uFEFF" + header + "\n" + rows.join("\n");

      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;charset=utf-8" });
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
    });

    return () => es.close();
  });
</script>

<main class="min-h-screen bg-gray-900 text-white" style="padding-bottom: 5.5rem;">
  <header class="border-b border-gray-800 px-6 py-4 flex items-center justify-between relative">
    <h1 class="text-xl font-bold">AI Token 用量统计</h1>
    <TimeRangeTabs current={filter.range} onchange={handleRangeChange} />
    {#if loading && summary}
      <span class="absolute top-1 right-6 text-xs text-gray-400 animate-pulse">刷新中...</span>
    {/if}
  </header>

  {#if error}
    <div class="mx-6 mt-4 p-3 bg-red-900/50 border border-red-700 rounded text-red-300 text-sm">
      {error}
    </div>
  {/if}

  {#if loading && !summary}
    <div class="flex flex-col items-center justify-center h-64 text-gray-500 gap-3">
      <svg class="animate-spin h-8 w-8 text-gray-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span>加载中...</span>
    </div>
  {:else if summary}
    <div class="p-6 space-y-6">
      <!-- 统计卡片：6个 -->
      <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard title="总 Token" value={summary.total_tokens} unit="" />
        <StatCard title="输入 Token" value={summary.input_tokens} unit="" />
        <StatCard title="输出 Token" value={summary.output_tokens} unit="" />
        <StatCard title="缓存 Token" value={summary.cache_tokens} unit="" />
        <StatCard title="总费用" value={summary.cost_usd} unit="$" prefix={true} />
        <StatCard title="请求次数" value={summary.call_count} unit="次" />
      </div>

      <!-- Token 用量趋势折线图：按 Agent + 按 Model -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <TrendLine data={trendByAgent} title="按 Agent 的 Token 用量趋势" />
        <TrendLine data={trendByModel} title="按模型的 Token 用量趋势" />
      </div>

      <!-- Agent Token 用量对比 -->
      <ComparisonChart breakdown={agentBreakdown} />

      <!-- Agent饼图 + 模型条形图 -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <AgentPie breakdown={agentBreakdown} />
        <ModelBar breakdown={modelBreakdown} />
      </div>

      <!-- 最近使用记录 -->
      {#if usage}
        <UsageTable
          items={usage.items}
          total={usage.total}
          page={usage.page}
          pageSize={PAGE_SIZE}
          onPageChange={handlePageChange}
          onExport={handleExport}
        />
      {/if}

      <!-- 模型费用定价 -->
      <ModelPricing />
    </div>
  {/if}

  <FilterBar
    {agents}
    {models}
    selectedAgents={filter.agents}
    selectedModels={filter.models}
    onchange={handleFilterChange}
  />
</main>
