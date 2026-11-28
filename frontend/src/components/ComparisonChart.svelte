<script lang="ts">
  import { onMount } from "svelte";
  import * as echarts from "echarts";
  import type { BreakdownItem } from "../types";
  import { escapeHtml } from "../utils/escape";
  import { chartPalette, type ChartPalette } from "../theme.svelte.ts";
  import { themeState } from "../theme.svelte.ts";
  import { uiState } from "../ui.svelte.ts";
  import { tilt } from "../motion";

  interface Props {
    breakdown: BreakdownItem[];
  }

  let { breakdown }: Props = $props();

  let chartEl: HTMLDivElement | undefined = $state();
  let chart: any = null;

  function fmt(n: number): string {
    if (n >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + " 万";
    return n.toLocaleString();
  }

  // Y 轴刻度与趋势图一致使用中文单位，避免同屏出现 150,000,000 这类原始数字
  function fmtAxis(v: number): string {
    if (v >= 1e8) return (v / 1e8).toFixed(1) + "亿";
    if (v >= 1e4) return (v / 1e4).toFixed(0) + "万";
    return String(v);
  }

  function buildOption(data: BreakdownItem[], P: ChartPalette) {
    const agents = [...new Set(data.map((d) => d.agent))];

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
        axisPointer: { type: "shadow" },
        formatter: (params: any[]) => {
          let html = `<b>${escapeHtml(params[0].axisValue)}</b><br/>`;
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
        data: ["输入 Token", "输出 Token", "缓存 Token"],
        textStyle: { color: P.text2, fontSize: 11 },
        top: 0,
        right: 0,
      },
      grid: { left: "3%", right: "4%", bottom: "3%", top: "14%", containLabel: true },
      xAxis: {
        type: "category",
        data: data.map((d) => d.model ? `${d.agent} / ${d.model}` : d.agent),
        axisLine: { lineStyle: { color: P.axis } },
        axisTick: { show: false },
        // 类目少时水平展示，多时才旋转避让
        axisLabel: { color: P.text3, fontSize: 11, rotate: data.length > 6 ? 30 : 0, hideOverlap: true },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: P.text3, fontSize: 11, formatter: fmtAxis },
        splitLine: { lineStyle: { color: P.split } },
      },
      series: [
        {
          name: "输入 Token",
          type: "bar",
          stack: "tokens",
          data: data.map((d) => d.input_tokens),
          itemStyle: { color: P.stackInput, borderRadius: [0, 0, 0, 0] },
          barWidth: "40%",
          barMaxWidth: 48,
        },
        {
          name: "输出 Token",
          type: "bar",
          stack: "tokens",
          data: data.map((d) => d.output_tokens),
          itemStyle: { color: P.stackOutput },
        },
        {
          name: "缓存 Token",
          type: "bar",
          stack: "tokens",
          data: data.map((d) => d.cache_read_tokens + d.cache_write_tokens),
          itemStyle: { color: P.stackCache, borderRadius: [4, 4, 0, 0] },
        },
      ],
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
    if (!breakdown?.length) {
      chart.clear();
      lastDataKey = "";
      return;
    }
    // 内容相同的 SSE 刷新跳过重建（避免 notMerge 全量重绘 + 动画重放）
    const dataKey = JSON.stringify(breakdown);
    if (dataKey !== lastDataKey || lastTheme !== themeState.current) {
      chart.setOption(buildOption(breakdown, chartPalette()), true);
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
