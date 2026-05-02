<script lang="ts">
  import { onMount } from "svelte";
  import type { BreakdownItem } from "../types";

  interface Props {
    breakdown: BreakdownItem[];
  }

  let { breakdown }: Props = $props();

  let chartEl: HTMLDivElement | undefined = $state();
  let chart: any = null;

  const COLORS: Record<string, string> = {
    "claude-code": "#4A90D9",
    hermes: "#50C878",
    openclaw: "#FF6B6B",
  };

  function buildOption(data: BreakdownItem[]) {
    const agents = [...new Set(data.map((d) => d.agent))];

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "#1f2937",
        borderColor: "#374151",
        textStyle: { color: "#e5e7eb" },
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
          name: "Input Tokens",
          type: "bar",
          stack: "tokens",
          data: data.map((d) => d.input_tokens),
          itemStyle: { color: "#4A90D9" },
        },
        {
          name: "Output Tokens",
          type: "bar",
          stack: "tokens",
          data: data.map((d) => d.output_tokens),
          itemStyle: { color: "#50C878" },
        },
        {
          name: "Cache Tokens",
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

    import("echarts").then((echarts) => {
      if (!chart) {
        chart = echarts.init(chartEl!, "dark");
      }
      chart.setOption(buildOption(breakdown));
    });
  });

  onMount(() => {
    return () => chart?.dispose();
  });
</script>

<div class="bg-gray-800 rounded-lg p-4 border border-gray-700">
  <h3 class="text-sm text-gray-400 mb-2">Token Consumption by Agent/Model</h3>
  <div bind:this={chartEl} class="w-full h-80"></div>
</div>
