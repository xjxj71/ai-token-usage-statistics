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

  function formatTokens(n: number): string {
    if (n >= 1e8) return (n / 1e8).toFixed(1) + "亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + "万";
    return n.toLocaleString();
  }

  function truncate(name: string, max = 12): string {
    return name.length > max ? name.slice(0, max) + "..." : name;
  }

  function buildOption(data: BreakdownItem[]) {
    const sorted = [...data].sort((a, b) => {
      const totalA = a.input_tokens + a.output_tokens + a.cache_read_tokens + a.cache_write_tokens;
      const totalB = b.input_tokens + b.output_tokens + b.cache_read_tokens + b.cache_write_tokens;
      return totalB - totalA;
    });

    const modelNames = sorted.map((d) => d.model || "未知");
    const totals = sorted.map((d) => d.input_tokens + d.output_tokens + d.cache_read_tokens + d.cache_write_tokens);

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "#1E293B",
        borderColor: "#334155",
        textStyle: { color: "#F8FAFC", fontSize: 12 },
        axisPointer: { type: "shadow" },
        formatter: (params: any[]) => {
          const fullName = modelNames[params[0].dataIndex] || params[0].axisValue;
          return `<b>${fullName}</b><br/>合计: <b>${formatTokens(params[0].value)}</b>`;
        },
      },
      grid: { left: "4%", right: "12%", bottom: "4%", top: "4%", containLabel: true },
      xAxis: {
        type: "value",
        splitLine: { lineStyle: { color: "rgba(51,65,85,.5)" } },
        axisLabel: {
          color: "#64748B",
          fontSize: 11,
          formatter: (v: number) => {
            if (v >= 1e4) return (v / 1e4) + "万";
            return String(v);
          },
        },
      },
      yAxis: {
        type: "category",
        data: modelNames.map((n) => truncate(n)).reverse(),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: "#94A3B8", fontSize: 12 },
      },
      series: [
        {
          type: "bar",
          data: totals.reverse(),
          barWidth: "50%",
          itemStyle: {
            borderRadius: [0, 6, 6, 0],
            color: {
              type: "linear" as const,
              x: 0, y: 0, x2: 1, y2: 0,
              colorStops: [
                { offset: 0, color: "#6366F1" },
                { offset: 1, color: "#22D3EE" },
              ],
            },
          },
          label: {
            show: true,
            position: "right",
            color: "#94A3B8",
            fontSize: 11,
            formatter: (p: any) => formatTokens(p.value),
          },
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
  <h3 class="chart-title">Model 分布</h3>
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
