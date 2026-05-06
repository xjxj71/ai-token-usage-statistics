<script lang="ts">
  import { onMount } from "svelte";
  import type { SummaryResponse, UsageResponse, FilterState, TimeRange } from "./types";
  import { fetchSummary, fetchUsage, fetchAgents, fetchModels, createEventSource } from "./api/client";
  import TimeRangeTabs from "./components/TimeRangeTabs.svelte";
  import StatCard from "./components/StatCard.svelte";
  import TrendChart from "./components/TrendChart.svelte";
  import AgentPie from "./components/AgentPie.svelte";
  import ModelBar from "./components/ModelBar.svelte";
  import UsageTable from "./components/UsageTable.svelte";
  import FilterBar from "./components/FilterBar.svelte";

  let summary: SummaryResponse | null = $state(null);
  let agentBreakdown: SummaryResponse["breakdown"] = $state([]);
  let modelBreakdown: SummaryResponse["breakdown"] = $state([]);
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

  function computeFromTo(range: TimeRange): { from?: string; to?: string } {
    if (range === "custom") return {};
    const now = new Date();
    const to = now.toISOString().slice(0, 10);
    let from: string;
    switch (range) {
      case "today":
        from = to;
        break;
      case "7d": {
        const d = new Date(now);
        d.setDate(d.getDate() - 7);
        from = d.toISOString().slice(0, 10);
        break;
      }
      case "30d": {
        const d = new Date(now);
        d.setDate(d.getDate() - 30);
        from = d.toISOString().slice(0, 10);
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

  async function loadData(page?: number) {
    loading = true;
    error = "";
    if (page !== undefined) currentPage = page;
    try {
      const params = buildParams();
      const [agentSum, modelSum, usg] = await Promise.all([
        fetchSummary({ ...params, group_by: "agent" }),
        fetchSummary({ ...params, group_by: "model" }),
        fetchUsage({ ...params, page: String(currentPage), limit: String(PAGE_SIZE) }),
      ]);
      summary = agentSum;
      agentBreakdown = agentSum.breakdown;
      modelBreakdown = modelSum.breakdown;
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

      <!-- Agent Token 用量对比 -->
      <TrendChart breakdown={agentBreakdown} />

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
        />
      {/if}
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
