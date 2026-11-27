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

  function formatTokens(n: number): string {
    if (n >= 1e8) return (n / 1e8).toFixed(1) + "亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + "万";
    return n.toLocaleString();
  }

  function truncate(name: string, max = 18): string {
    return name.length > max ? name.slice(0, max) + "..." : name;
  }

  /** 条目少时压缩图高，避免单根柱子显得空旷；containLabel 会自动容纳较长的类目标签 */
  function getChartHeight(): string {
    const rows = [...new Set((breakdown ?? []).map((d) => d.project || "未知"))].length;
    return `${Math.max(240, rows * 48 + 60)}px`;
  }

  function buildOption(data: BreakdownItem[], P: ChartPalette) {
    const sorted = [...data].sort((a, b) => {
      const totalA = a.input_tokens + a.output_tokens + a.cache_read_tokens + a.cache_write_tokens;
      const totalB = b.input_tokens + b.output_tokens + b.cache_read_tokens + b.cache_write_tokens;
      return totalB - totalA;
    });

    const projectNames = sorted.map((d) => d.project || "未知");
    const totals = sorted.map((d) => d.input_tokens + d.output_tokens + d.cache_read_tokens + d.cache_write_tokens);

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
          const fullName = projectNames[params[0].dataIndex] || params[0].axisValue;
          return `<b>${escapeHtml(fullName)}</b><br/>合计: <b>${formatTokens(params[0].value)}</b>`;
        },
      },
      grid: { left: "4%", right: "12%", bottom: "4%", top: "4%", containLabel: true },
      xAxis: {
        type: "value",
        splitLine: { lineStyle: { color: P.split } },
        axisLabel: {
          color: P.text3,
          fontSize: 11,
          formatter: (v: number) => {
            if (v >= 1e4) return (v / 1e4) + "万";
            return String(v);
          },
        },
      },
      yAxis: {
        type: "category",
        data: projectNames.map((n) => truncate(n)).reverse(),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: P.text2, fontSize: 12 },
      },
      series: [
        {
          type: "bar",
          data: totals.reverse(),
          barWidth: "50%",
          barMaxWidth: 28,
          itemStyle: {
            borderRadius: [0, 6, 6, 0],
            color: {
              type: "linear" as const,
              x: 0, y: 0, x2: 1, y2: 0,
              colorStops: [
                { offset: 0, color: P.projectFrom },
                { offset: 1, color: P.projectTo },
              ],
            },
          },
          label: {
            show: true,
            position: "right",
            color: P.text2,
            fontSize: 11,
            formatter: (p: any) => formatTokens(p.value),
          },
        },
      ],
    };
  }

  let lastData: unknown = null;
  let lastTheme = "";
  $effect(() => {
    if (!chartEl) return;
    void uiState.view; // keep-alive：视图显示时补初始化/重绘
    if (chartEl.clientWidth === 0) return; // 隐藏视图不初始化
    const P = chartPalette();
    if (!chart) {
      chart = echarts.init(chartEl);
      lastData = null;
    }
    if (!breakdown?.length) {
      chart.clear();
      lastData = null;
      return;
    }
    if (lastData !== breakdown || lastTheme !== themeState.current) {
      chart.setOption(buildOption(breakdown, P), true);
      lastData = breakdown;
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
  <h3 class="chart-title">项目消耗分布</h3>
  {#if !breakdown?.length}
    <div class="empty-hint">当前范围内没有带项目信息的记录（仅 claude-code / openclaude / zcode / codex / qoder 提供工作目录数据）</div>
  {/if}
  <div bind:this={chartEl} class="chart-body" style="height:{getChartHeight()}"></div>
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
  .empty-hint {
    font-size: 12px;
    color: var(--text-3);
    margin-bottom: 8px;
  }
</style>
