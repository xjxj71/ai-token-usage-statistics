<script lang="ts">
  import { onMount } from "svelte";
  import * as echarts from "echarts";
  import type { TrendResponse } from "../types";
  import { escapeHtml } from "../utils/escape";
  import { chartPalette, type ChartPalette } from "../theme.svelte.ts";
  import { themeState } from "../theme.svelte.ts";
  import { uiState } from "../ui.svelte.ts";
  import { tilt } from "../motion";

  interface Props {
    data: TrendResponse | null;
    title: string;
  }

  let { data, title }: Props = $props();

  let chartEl: HTMLDivElement | undefined = $state();
  let chart: any = null;

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

  function buildOption(d: TrendResponse, P: ChartPalette) {
    const series = d.series
      .filter((s) => s.name !== "总计")
      .map((s, i) => ({
        name: s.name,
        type: "line",
        data: s.data,
        smooth: true,
        symbol: "circle",
        symbolSize: 5,
        lineStyle: { width: 2, color: P.series[i % P.series.length] },
        itemStyle: { color: P.series[i % P.series.length] },
        areaStyle: {
          color: {
            type: "linear" as const,
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: P.series[i % P.series.length] + "40" },
              { offset: 1, color: P.series[i % P.series.length] + "05" },
            ],
          },
        },
      }));

    const hourly = isHourly(d.dates);
    const xLabels = d.dates.map((raw) => fmtAxisLabel(raw));

    return {
      backgroundColor: "transparent",
      animationDuration: 900,
      animationEasing: "cubicOut",
      animationDurationUpdate: 700,
      animationEasingUpdate: "cubicInOut",
      tooltip: {
        trigger: "axis",
        backgroundColor: P.tooltipBg,
        borderColor: P.tooltipBorder,
        textStyle: { color: P.tooltipText, fontSize: 12 },
        formatter: (params: any[]) => {
          const raw = d.dates[params[0].dataIndex];
          const label = hourly ? `${raw.slice(0, 10)} ${raw.slice(11)}:00` : raw;
          let html = `<b>${escapeHtml(label)}</b><br/>`;
          let total = 0;
          for (const p of params) {
            total += p.value;
            html += `${p.marker} ${escapeHtml(p.seriesName)}: <b>${fmt(p.value)}</b><br/>`;
          }
          html += `<b>总计: ${fmt(total)}</b>`;
          return html;
        },
      },
      legend: {
        data: d.series.filter((s) => s.name !== "总计").map((s) => s.name),
        textStyle: { color: P.text2, fontSize: 11 },
        top: 0,
        right: 0,
      },
      grid: { left: "3%", right: "4%", bottom: "3%", top: "14%", containLabel: true },
      xAxis: {
        type: "category",
        data: xLabels,
        axisLine: { lineStyle: { color: P.axis } },
        axisTick: { show: false },
        axisLabel: { color: P.text3, fontSize: 11 },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: P.text3,
          fontSize: 11,
          formatter: (v: number) => {
            if (v >= 1e8) return (v / 1e8).toFixed(1) + "亿";
            if (v >= 1e4) return (v / 1e4).toFixed(0) + "万";
            return String(v);
          },
        },
        splitLine: { lineStyle: { color: P.split } },
      },
      series,
    };
  }

  let lastDataKey = "";
  let lastTheme = "";
  $effect(() => {
    if (!chartEl) return;
    void uiState.view; // keep-alive：视图显示时补初始化/重绘
    if (chartEl.clientWidth === 0) return; // 隐藏视图不初始化
    if (!chart) {
      chart = echarts.init(chartEl);
      lastDataKey = "";
    }
    if (!data) {
      chart.clear();
      lastDataKey = "";
      return;
    }
    // SSE 每次刷新都换新对象引用；内容相同时跳过重建，避免无谓的
    // notMerge 全量重绘 + 900ms 入场动画重放，也省掉一次 chartPalette()
    const dataKey = JSON.stringify(data);
    if (dataKey !== lastDataKey || lastTheme !== themeState.current) {
      chart.setOption(buildOption(data, chartPalette()), true);
      lastDataKey = dataKey;
      lastTheme = themeState.current;
    } else {
      chart.resize();
    }
  });

  onMount(() => {
    const handleResize = () => chart?.resize();
    window.addEventListener("resize", handleResize);
    // 侧栏折叠/容器尺寸变化时自适应（window resize 不触发的场景）
    const ro = new ResizeObserver(() => chart?.resize());
    if (chartEl) ro.observe(chartEl);
    return () => {
      window.removeEventListener("resize", handleResize);
      ro.disconnect();
      chart?.dispose();
    };
  });
</script>

<div class="chart-card" use:tilt={{ max: 1.5 }}>
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
