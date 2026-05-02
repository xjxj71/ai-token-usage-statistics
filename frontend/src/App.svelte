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
  let usage: UsageResponse | null = $state(null);
  let agents: string[] = $state([]);
  let models: string[] = $state([]);
  let loading = $state(true);
  let error = $state("");

  let filter: FilterState = $state({
    range: "today",
    agents: [],
    models: [],
  });

  function buildParams(): Record<string, string> {
    const p: Record<string, string> = { range: filter.range };
    if (filter.range === "custom" && filter.from) p.from = filter.from;
    if (filter.range === "custom" && filter.to) p.to = filter.to;
    if (filter.agents.length > 0) p.agent = filter.agents.join(",");
    if (filter.models.length > 0) p.model = filter.models.join(",");
    return p;
  }

  async function loadData() {
    loading = true;
    error = "";
    try {
      const params = buildParams();
      const [sum, usg] = await Promise.all([
        fetchSummary(params),
        fetchUsage({ ...params, page: "1", limit: "50" }),
      ]);
      summary = sum;
      usage = usg;
    } catch (e: any) {
      error = e.message || "Failed to load data";
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
    loadData();
  }

  function handleFilterChange(agents: string[], models: string[]) {
    filter = { ...filter, agents, models };
    loadData();
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

<main class="min-h-screen bg-gray-900 text-white">
  <header class="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
    <h1 class="text-xl font-bold">AI Token Usage Statistics</h1>
    <TimeRangeTabs current={filter.range} onchange={handleRangeChange} />
  </header>

  {#if error}
    <div class="mx-6 mt-4 p-3 bg-red-900/50 border border-red-700 rounded text-red-300 text-sm">
      {error}
    </div>
  {/if}

  {#if loading && !summary}
    <div class="flex items-center justify-center h-64 text-gray-500">Loading...</div>
  {:else if summary}
    <div class="p-6 space-y-6">
      <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard title="Total Tokens" value={summary.total_tokens} unit="" />
        <StatCard title="Input Tokens" value={summary.input_tokens} unit="" />
        <StatCard title="Output Tokens" value={summary.output_tokens} unit="" />
        <StatCard title="Cache Tokens" value={summary.cache_tokens} unit="" />
        <StatCard title="Total Cost" value={summary.cost_usd} unit="$" prefix={true} />
        <StatCard title="Call Count" value={summary.call_count} unit="calls" />
      </div>

      <TrendChart breakdown={summary.breakdown} />

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <AgentPie breakdown={summary.breakdown} />
        <ModelBar breakdown={summary.breakdown} />
      </div>

      {#if usage}
        <UsageTable items={usage.items} total={usage.total} page={usage.page} />
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
