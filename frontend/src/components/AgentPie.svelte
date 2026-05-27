<script lang="ts">
  import { onMount } from "svelte";
  import * as echarts from "echarts";
  import type { BreakdownItem } from "../types";

  interface Props {
    breakdown: BreakdownItem[];
  }

  let { breakdown }: Props = $props();

  let chartEl: HTMLDivElement | undefined = $state();
  let chart: any = null;

  const COLORS = ["#6366F1", "#8B5CF6", "#10B981", "#F59E0B", "#EC4899", "#22D3EE"];

  function fmt(n: number): string {
    if (n >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + " 万";
    return n.toLocaleString();
  }

  function buildOption(data: BreakdownItem[]) {
    const pieData = data.map((d) => ({
      name: d.agent || "未知",
      value: d.input_tokens + d.output_tokens + d.cache_read_tokens + d.cache_write_tokens,
    }));

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        backgroundColor: "#1E293B",
        borderColor: "#334155",
        textStyle: { color: "#F8FAFC", fontSize: 12 },
        formatter: (params: any) => {
          const val = params.value as number;
          return `<b>${params.name}</b><br/>`
            + `总 Token: <b>${fmt(val)}</b><br/>`
            + `占比: <b>${params.percent}%</b>`;
        },
      },
      legend: {
        orient: "horizontal",
        bottom: 0,
        textStyle: { color: "#94A3B8", fontSize: 11 },
      },
      series: [
        {
          name: "Agent Token 总消耗",
          type: "pie",
          radius: ["45%", "72%"],
          center: ["50%", "45%"],
          avoidLabelOverlap: true,
          itemStyle: {
            borderRadius: 6,
            borderColor: "#1E293B",
            borderWidth: 2,
          },
          label: {
            show: true,
            color: "#94A3B8",
            fontSize: 11,
            formatter: (params: any) => {
              return `${params.name}\n${fmt(params.value)} (${params.percent}%)`;
            },
          },
          emphasis: {
            label: { show: true, fontSize: 14, fontWeight: "bold" },
          },
          data: pieData,
          color: COLORS,
        },
      ],
    };
  }

  $effect(() => {
    if (!chartEl) return;
    if (!chart) {
      chart = echarts.init(chartEl, "dark");
    }
    if (!breakdown?.length) {
      chart.clear();
      return;
    }
    chart.setOption(buildOption(breakdown), true);
  });

  onMount(() => {
    const handleResize = () => chart?.resize();
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart?.dispose();
    };
  });
</script>

<div class="chart-card">
  <h3 class="chart-title">Agent 占比（环形图）</h3>
  <div bind:this={chartEl} class="chart-body" style="height:320px;"></div>
</div>

<style>
  .chart-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
  }
  .chart-title {
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 12px;
  }
  .chart-body {
    width: 100%;
  }
</style>
