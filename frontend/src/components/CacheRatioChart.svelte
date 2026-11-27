<script lang="ts">
  import { onMount } from "svelte";
  import * as echarts from "echarts";
  import type { CacheRatioItem } from "../types";
  import { escapeHtml } from "../utils/escape";
  import { chartPalette, type ChartPalette } from "../theme.svelte.ts";
  import { themeState } from "../theme.svelte.ts";
  import { uiState } from "../ui.svelte.ts";
  import { tilt } from "../motion";

  interface Props {
    byAgent: CacheRatioItem[];
    byModel: CacheRatioItem[];
    byAgentModel: CacheRatioItem[];
  }

  let { byAgent, byModel, byAgentModel }: Props = $props();

  let chartEl: HTMLDivElement | undefined = $state();
  let chart: any = null;
  let activeTab: "agent" | "model" | "agent_model" = $state("agent");

  function fmtTokens(n: number): string {
    if (n >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + " 万";
    return n.toLocaleString();
  }

  function ratioColor(ratio: number): string {
    // Red (0%) → Amber (50%) → Green (100%)
    if (ratio < 0.5) {
      const t = ratio / 0.5;
      const r = Math.round(239 + (245 - 239) * t);
      const g = Math.round(68 + (158 - 68) * t);
      const b = Math.round(68 + (11 - 68) * t);
      return `rgb(${r},${g},${b})`;
    } else {
      const t = (ratio - 0.5) / 0.5;
      const r = Math.round(245 + (34 - 245) * t);
      const g = Math.round(158 + (197 - 158) * t);
      const b = Math.round(11 + (94 - 11) * t);
      return `rgb(${r},${g},${b})`;
    }
  }

  /**
   * Sort ASCENDING so ECharts renders the lowest ratio at the bottom
   * and the highest at the top — no in-place reverse() needed, keeping
   * the sorted array and the display indices in sync for tooltips.
   */
  function buildAgentOption(data: CacheRatioItem[], P: ChartPalette) {
    const sorted = [...data].sort((a, b) => a.cache_ratio - b.cache_ratio);
    const names = sorted.map((d) => d.agent || "未知");
    const ratios = sorted.map((d) => Math.round(d.cache_ratio * 1000) / 10);

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
          const p = params[0];
          const item = sorted[p.dataIndex];
          return `<b>${escapeHtml(item.agent || "未知")}</b><br/>`
            + `缓存命中率: <b>${ratios[p.dataIndex]}%</b><br/>`
            + `总 Token: <b>${fmtTokens(item.total_tokens)}</b><br/>`
            + `缓存 Token: <b>${fmtTokens(item.cache_read_tokens)}</b>`;
        },
      },
      grid: { left: "3%", right: "15%", bottom: "3%", top: "3%", containLabel: true },
      xAxis: {
        type: "value",
        max: 100,
        axisLabel: { color: P.text3, fontSize: 11, formatter: (v: number) => `${v}%` },
        splitLine: { lineStyle: { color: P.split } },
      },
      yAxis: {
        type: "category",
        data: names,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: P.text2, fontSize: 12 },
      },
      series: [{
        type: "bar",
        data: sorted.map((d, i) => ({
          value: ratios[i],
          itemStyle: {
            color: ratioColor(d.cache_ratio),
            borderRadius: [0, 6, 6, 0],
          },
        })),
        barWidth: "55%",
        barMaxWidth: 36,
        label: {
          show: true,
          position: "right",
          color: P.text2,
          fontSize: 12,
          formatter: (p: any) => `${p.value}%`,
        },
      }],
    };
  }

  function buildModelOption(data: CacheRatioItem[], P: ChartPalette) {
    const sorted = [...data].sort((a, b) => a.cache_ratio - b.cache_ratio);
    const names = sorted.map((d) => d.model || "未知");
    const ratios = sorted.map((d) => Math.round(d.cache_ratio * 1000) / 10);

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
          const p = params[0];
          const item = sorted[p.dataIndex];
          return `<b>${escapeHtml(item.model || "未知")}</b><br/>`
            + `缓存命中率: <b>${ratios[p.dataIndex]}%</b><br/>`
            + `总 Token: <b>${fmtTokens(item.total_tokens)}</b><br/>`
            + `缓存 Token: <b>${fmtTokens(item.cache_read_tokens)}</b>`;
        },
      },
      grid: { left: "3%", right: "15%", bottom: "3%", top: "3%", containLabel: true },
      xAxis: {
        type: "value",
        max: 100,
        axisLabel: { color: P.text3, fontSize: 11, formatter: (v: number) => `${v}%` },
        splitLine: { lineStyle: { color: P.split } },
      },
      yAxis: {
        type: "category",
        data: names,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: P.text2, fontSize: 11, width: 140, overflow: "truncate" },
      },
      series: [{
        type: "bar",
        data: sorted.map((d, i) => ({
          value: ratios[i],
          itemStyle: {
            color: ratioColor(d.cache_ratio),
            borderRadius: [0, 6, 6, 0],
          },
        })),
        barWidth: "55%",
        barMaxWidth: 36,
        label: {
          show: true,
          position: "right",
          color: P.text2,
          fontSize: 11,
          formatter: (p: any) => `${p.value}%`,
        },
      }],
    };
  }

  function buildAgentModelOption(data: CacheRatioItem[], P: ChartPalette) {
    // Group by agent (ascending by name for consistent order)
    const agentGroups = new Map<string, CacheRatioItem[]>();
    for (const item of data) {
      const key = item.agent || "未知";
      if (!agentGroups.has(key)) agentGroups.set(key, []);
      agentGroups.get(key)!.push(item);
    }

    const agents = [...agentGroups.keys()].sort();
    // Collect unique models across all agents
    const allModels = [...new Set(data.map((d) => d.model || "未知"))].sort();
    const MODEL_COLORS = P.series;

    const series = allModels.map((modelName, mi) => ({
      name: modelName,
      type: "bar" as const,
      stack: "cache",
      data: agents.map((agentName) => {
        const item = agentGroups.get(agentName)?.find((d) => (d.model || "未知") === modelName);
        return item ? Math.round(item.cache_ratio * 1000) / 10 : 0;
      }),
      barWidth: "50%",
      barMaxWidth: 36,
      itemStyle: {
        color: MODEL_COLORS[mi % MODEL_COLORS.length],
        borderRadius: mi === allModels.length - 1 ? [0, 4, 4, 0] : [0, 0, 0, 0],
      },
      label: {
        show: allModels.length <= 5,
        position: "insideRight" as const,
        color: "#F8FAFC",
        fontSize: 10,
        formatter: (p: any) => p.value > 0 ? `${p.value}%` : "",
      },
    }));

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
          const agentName = params[0].axisValue;
          let html = `<b>${escapeHtml(agentName)}</b><br/>`;
          for (const p of params) {
            if (p.value > 0) {
              const items = agentGroups.get(agentName) || [];
              const item = items.find((d) => (d.model || "未知") === p.seriesName);
              html += `${p.marker} ${escapeHtml(p.seriesName)}: <b>${p.value}%</b>`;
              if (item) html += ` (${fmtTokens(item.cache_read_tokens)} / ${fmtTokens(item.total_tokens)})`;
              html += "<br/>";
            }
          }
          return html;
        },
      },
      legend: {
        data: allModels,
        textStyle: { color: P.text2, fontSize: 11 },
        top: 0,
        right: 0,
        type: "scroll",
      },
      grid: { left: "3%", right: "4%", bottom: "3%", top: "14%", containLabel: true },
      xAxis: {
        type: "value",
        axisLabel: { color: P.text3, fontSize: 11, formatter: (v: number) => `${v}%` },
        splitLine: { lineStyle: { color: P.split } },
      },
      yAxis: {
        type: "category",
        data: agents,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: P.text2, fontSize: 12 },
      },
      series,
    };
  }

  function getCurrentData(): CacheRatioItem[] {
    switch (activeTab) {
      case "agent": return byAgent;
      case "model": return byModel;
      case "agent_model": return byAgentModel;
    }
  }

  function getCurrentOption(P: ChartPalette) {
    switch (activeTab) {
      case "agent": return buildAgentOption(byAgent, P);
      case "model": return buildModelOption(byModel, P);
      case "agent_model": return buildAgentModelOption(byAgentModel, P);
    }
  }

  /** Dynamic chart height: more items → taller chart */
  function getChartHeight(): string {
    const data = getCurrentData();
    if (!data?.length) return "320px";
    if (activeTab === "agent_model") {
      // Agent×model: need room for legend + grouped rows
      const agents = new Set(data.map(d => d.agent || "未知")).size;
      return `${Math.max(320, agents * 60 + 80)}px`;
    }
    // One row per item, min 320px
    return `${Math.max(320, data.length * 44 + 60)}px`;
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
    const data = getCurrentData();
    if (!data?.length) {
      chart.clear();
      lastData = null;
      return;
    }
    if (lastData !== data || lastTheme !== themeState.current) {
      chart.setOption(getCurrentOption(P), true);
      lastData = data;
      lastTheme = themeState.current;
    }
    chart.resize();
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
  <div class="flex items-center justify-between mb-3">
    <h3 class="chart-title mb-0">缓存率分析</h3>
    <div class="tab-group">
      <button class="tab-btn" class:active={activeTab === "agent"} onclick={() => activeTab = "agent"}>按 Agent</button>
      <button class="tab-btn" class:active={activeTab === "model"} onclick={() => activeTab = "model"}>按模型</button>
      <button class="tab-btn" class:active={activeTab === "agent_model"} onclick={() => activeTab = "agent_model"}>Agent × 模型</button>
    </div>
  </div>
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
  }
  .chart-body {
    width: 100%;
  }
  .tab-group {
    display: flex;
    gap: 2px;
    background: rgba(var(--border-rgb), 0.3);
    border-radius: 8px;
    padding: 2px;
  }
  .tab-btn {
    padding: 5px 12px;
    font-size: 12px;
    color: var(--text-3, #94A3B8);
    background: transparent;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
  }
  .tab-btn:hover {
    color: var(--text);
    background: rgba(var(--primary-rgb), 0.1);
  }
  .tab-btn.active {
    color: var(--on-primary);
    background: var(--primary);
    font-weight: 500;
  }
</style>
