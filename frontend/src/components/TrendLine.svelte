<script lang="ts">
  import { onMount } from "svelte";
  import * as echarts from "echarts";
  import type { TrendResponse } from "../types";

  interface Props {
    data: TrendResponse | null;
    title: string;
  }

  let { data, title }: Props = $props();

  let chartEl: HTMLDivElement | undefined = $state();
  let chart: any = null;

  const COLORS = [
    "#6366F1", "#22D3EE", "#10B981", "#F59E0B", "#EF4444",
    "#8B5CF6", "#EC4899", "#3B82F6", "#14B8A6", "#F97316",
  ];

  function fmt(n: number): string {
    if (n >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + " 万";
    return n.toLocaleString();
  }

  function isHourly(dates: string[]): boolean {
    return dates.length > 0 && dates[0].includes("T");
  }

  function fmtAxisLabel(raw: string): string {
    if (raw.includes("T")) {
      const hh = raw.split("T")[1];
      return `${hh}:00`;
    }
    return raw.slice(5);
  }

  function buildOption(d: TrendResponse) {
    const series = d.series
      .filter((s) => s.name !== "总计")
      .map((s, i) => ({
        name: s.name,
        type: "line",
        data: s.data,
        smooth: true,
        symbol: "circle",
        symbolSize: 5,
        lineStyle: { width: 2, color: COLORS[i % COLORS.length] },
        itemStyle: { color: COLORS[i % COLORS.length] },
        areaStyle: {
          color: {
            type: "linear" as const,
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: COLORS[i % COLORS.length] + "40" },
              { offset: 1, color: COLORS[i % COLORS.length] + "05" },
            ],
          },
        },
      }));

    const hourly = isHourly(d.dates);
    const xLabels = d.dates.map((raw) => fmtAxisLabel(raw));

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "#1E293B",
        borderColor: "#334155",
        textStyle: { color: "#F8FAFC", fontSize: 12 },
        formatter: (params: any[]) => {
          const raw = d.dates[params[0].dataIndex];
          const label = hourly ? `${raw.slice(0, 10)} ${raw.slice(11)}:00` : raw;
          let html = `<b>${label}</b><br/>`;
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
        data: d.series.filter((s) => s.name !== "总计").map((s) => s.name),
        textStyle: { color: "#94A3B8", fontSize: 11 },
        top: 0,
        right: 0,
      },
      grid: { left: "3%", right: "4%", bottom: "3%", top: "14%", containLabel: true },
      xAxis: {
        type: "category",
        data: xLabels,
        axisLine: { lineStyle: { color: "#334155" } },
        axisTick: { show: false },
        axisLabel: { color: "#64748B", fontSize: 11 },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: "#64748B",
          fontSize: 11,
          formatter: (v: number) => {
            if (v >= 1e8) return (v / 1e8).toFixed(1) + "亿";
            if (v >= 1e4) return (v / 1e4).toFixed(0) + "万";
            return String(v);
          },
        },
        splitLine: { lineStyle: { color: "rgba(51,65,85,.5)" } },
      },
      series,
    };
  }

  $effect(() => {
    if (!chartEl) return;
    if (!chart) {
      chart = echarts.init(chartEl, "dark");
    }
    if (!data) {
      chart.clear();
      return;
    }
    chart.setOption(buildOption(data), true);
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
  <h3 class="chart-title">{title}</h3>
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
