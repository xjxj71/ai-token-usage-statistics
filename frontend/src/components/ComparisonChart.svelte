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

  const COLORS = ["#6366F1", "#22D3EE", "#F59E0B"];

  function fmt(n: number): string {
    if (n >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + " 万";
    return n.toLocaleString();
  }

  function buildOption(data: BreakdownItem[]) {
    const agents = [...new Set(data.map((d) => d.agent))];

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "#1E293B",
        borderColor: "#334155",
        textStyle: { color: "#F8FAFC", fontSize: 12 },
        axisPointer: { type: "shadow" },
        formatter: (params: any[]) => {
          let html = `<b>${params[0].axisValue}</b><br/>`;
          let total = 0;
          for (const p of params) {
            total += p.value;
            html += `${p.marker} ${p.seriesName}: <b>${fmt(p.value)}</b><br/>`;
          }
          html += `<b>总计: ${fmt(total)}</b>`;
          return html;
        },
      },
      legend: {
        data: ["输入 Token", "输出 Token", "缓存 Token"],
        textStyle: { color: "#94A3B8", fontSize: 11 },
        top: 0,
        right: 0,
      },
      grid: { left: "3%", right: "4%", bottom: "3%", top: "14%", containLabel: true },
      xAxis: {
        type: "category",
        data: data.map((d) => `${d.agent} / ${d.model}`),
        axisLine: { lineStyle: { color: "#334155" } },
        axisTick: { show: false },
        axisLabel: { color: "#64748B", fontSize: 11, rotate: 30 },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#64748B", fontSize: 11 },
        splitLine: { lineStyle: { color: "rgba(51,65,85,.5)" } },
      },
      series: [
        {
          name: "输入 Token",
          type: "bar",
          stack: "tokens",
          data: data.map((d) => d.input_tokens),
          itemStyle: { color: COLORS[0], borderRadius: [0, 0, 0, 0] },
          barWidth: "40%",
        },
        {
          name: "输出 Token",
          type: "bar",
          stack: "tokens",
          data: data.map((d) => d.output_tokens),
          itemStyle: { color: COLORS[1] },
        },
        {
          name: "缓存 Token",
          type: "bar",
          stack: "tokens",
          data: data.map((d) => d.cache_read_tokens + d.cache_write_tokens),
          itemStyle: { color: COLORS[2], borderRadius: [4, 4, 0, 0] },
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
  <h3 class="chart-title">Agent Token 对比（堆叠柱状图）</h3>
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
