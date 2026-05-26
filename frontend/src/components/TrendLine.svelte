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
    "#4A90D9", "#50C878", "#F5A623", "#E87676", "#9B59B6",
    "#1ABC9C", "#E67E22", "#3498DB", "#2ECC71", "#F39C12",
  ];

  function fmt(n: number): string {
    if (n >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + " 万";
    return n.toLocaleString();
  }

  /** Detect if dates are hourly format ("2026-05-26T09") vs daily ("2026-05-26") */
  function isHourly(dates: string[]): boolean {
    return dates.length > 0 && dates[0].includes("T");
  }

  /** Format axis label: hourly → "09:00", daily → "05-20" */
  function fmtAxisLabel(raw: string): string {
    if (raw.includes("T")) {
      // Hourly: "2026-05-26T09" -> "09:00"
      const hh = raw.split("T")[1];
      return `${hh}:00`;
    }
    // Daily: "2026-05-26" → "05-26"
    return raw.slice(5);
  }

  function buildOption(d: TrendResponse) {
    const series = d.series.map((s, i) => ({
      name: s.name,
      type: "line",
      data: s.data,
      smooth: true,
      symbol: "circle",
      symbolSize: 4,
      lineStyle: { width: s.name === "总计" ? 3 : 1.5 },
      itemStyle: { color: COLORS[i % COLORS.length] },
    }));

    const hourly = isHourly(d.dates);
    const xLabels = d.dates.map((raw) => fmtAxisLabel(raw));

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "#1f2937",
        borderColor: "#374151",
        textStyle: { color: "#e5e7eb" },
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
        type: "scroll",
        textStyle: { color: "#9ca3af", fontSize: 11 },
        top: 0,
      },
      grid: { left: "3%", right: "4%", bottom: "8%", top: "18%", containLabel: true },
      xAxis: {
        type: "category",
        data: xLabels,
        boundaryGap: false,
        axisLabel: { color: "#9ca3af", fontSize: 10, rotate: hourly ? 45 : 30 },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: "#9ca3af",
          formatter: (v: number) => fmt(v),
        },
        splitLine: { lineStyle: { color: "#374151" } },
      },
      series,
    };
  }

  $effect(() => {
    if (!chartEl || !data || !data.dates.length) return;
    if (!chart) {
      chart = echarts.init(chartEl, "dark");
    }
    chart.setOption(buildOption(data));
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

<div class="bg-gray-800 rounded-lg p-4 border border-gray-700">
  <h3 class="text-sm text-gray-400 mb-2">{title}</h3>
  {#if !data || !data.dates.length}
    <div class="flex items-center justify-center h-64 text-gray-500 text-sm">
      暂无趋势数据
    </div>
  {:else}
    <div bind:this={chartEl} class="w-full h-72"></div>
  {/if}
</div>