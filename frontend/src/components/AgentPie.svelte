<script lang="ts">
  import { onMount } from "svelte";
  import * as echarts from "echarts";
  import type { BreakdownItem } from "../types";
  import { escapeHtml } from "../utils/escape";
  import { chartPalette, agentColor, type ChartPalette } from "../theme.svelte.ts";
  import { themeState } from "../theme.svelte.ts";
  import { uiState } from "../ui.svelte.ts";
  import { tilt } from "../motion";

  interface Props {
    breakdown: BreakdownItem[];
    /** 窄容器：隐藏外置标签（下方图例已足够），避免截断 */
    compact?: boolean;
  }

  let { breakdown, compact = false }: Props = $props();

  let chartEl: HTMLDivElement | undefined = $state();
  let chart: any = null;

  function fmt(n: number): string {
    if (n >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + " 万";
    return n.toLocaleString();
  }

  function buildOption(data: BreakdownItem[], P: ChartPalette) {
    const pieData = data.map((d, i) => ({
      name: d.agent || "未知",
      value: d.input_tokens + d.output_tokens + d.cache_read_tokens + d.cache_write_tokens,
      itemStyle: { color: agentColor(d.agent || "") || P.series[i % P.series.length] },
    }));

    return {
      backgroundColor: "transparent",
      animationDuration: 900,
      animationEasing: "cubicOut",
      animationDurationUpdate: 700,
      animationEasingUpdate: "cubicInOut",
      tooltip: {
        trigger: "item",
        backgroundColor: P.tooltipBg,
        borderColor: P.tooltipBorder,
        textStyle: { color: P.tooltipText, fontSize: 12 },
        formatter: (params: any) => {
          const val = params.value as number;
          return `<b>${escapeHtml(params.name)}</b><br/>`
            + `总 Token: <b>${fmt(val)}</b><br/>`
            + `占比: <b>${params.percent}%</b>`;
        },
      },
      legend: {
        orient: "horizontal",
        bottom: 0,
        textStyle: { color: P.text2, fontSize: 11 },
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
            borderColor: P.card,
            borderWidth: 2,
          },
          label: {
            show: !compact,
            color: P.text2,
            fontSize: 11,
            formatter: (params: any) => {
              return `${params.name}\n${fmt(params.value)} (${params.percent}%)`;
            },
          },
          emphasis: {
            label: { show: true, fontSize: 14, fontWeight: "bold" },
          },
          data: pieData,
          color: P.series,
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
