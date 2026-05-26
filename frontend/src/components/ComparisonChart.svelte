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
        backgroundColor: "#1f2937",
        borderColor: "#374151",
        textStyle: { color: "#e5e7eb" },
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
        data: agents,
        textStyle: { color: "#9ca3af" },
        top: 0,
      },
      grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
      xAxis: {
        type: "category",
        data: data.map((d) => `${d.agent} / ${d.model}`),
        axisLabel: { color: "#9ca3af", rotate: 30 },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#9ca3af" },
        splitLine: { lineStyle: { color: "#374151" } },
      },
      series: [
        {
          name: "输入 Token",
          type: "bar",
          stack: "tokens",
          data: data.map((d) => d.input_tokens),
          itemStyle: { color: "#4A90D9" },
        },
        {
          name: "输出 Token",
          type: "bar",
          stack: "tokens",
          data: data.map((d) => d.output_tokens),
          itemStyle: { color: "#50C878" },
        },
        {
          name: "缓存 Token",
          type: "bar",
          stack: "tokens",
          data: data.map((d) => d.cache_read_tokens + d.cache_write_tokens),
          itemStyle: { color: "#F5A623" },
        },
      ],
    };
  }

  $effect(() => {
    if (!chartEl || !breakdown) return;
    if (!chart) {
      chart = echarts.init(chartEl, "dark");
    }
    chart.setOption(buildOption(breakdown));
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
  <h3 class="text-sm text-gray-400 mb-2">Token 用量对比</h3>
  <div bind:this={chartEl} class="w-full h-80"></div>
</div>
