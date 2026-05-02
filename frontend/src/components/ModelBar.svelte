<script lang="ts">
  import { onMount } from "svelte";
  import type { BreakdownItem } from "../types";

  interface Props {
    breakdown: BreakdownItem[];
  }

  let { breakdown }: Props = $props();

  let chartEl: HTMLDivElement | undefined = $state();
  let chart: any = null;

  const COLORS = ["#4A90D9", "#50C878", "#FF6B6B", "#F5A623", "#9B59B6", "#1ABC9C"];

  function buildOption(data: BreakdownItem[]) {
    const byModel = new Map<string, { input: number; output: number }>();
    for (const d of data) {
      const existing = byModel.get(d.model) || { input: 0, output: 0 };
      byModel.set(d.model, {
        input: existing.input + d.input_tokens,
        output: existing.output + d.output_tokens,
      });
    }

    const models = [...byModel.keys()];

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "#1f2937",
        borderColor: "#374151",
        textStyle: { color: "#e5e7eb" },
      },
      legend: {
        textStyle: { color: "#9ca3af" },
        top: 0,
      },
      grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
      xAxis: {
        type: "category",
        data: models,
        axisLabel: { color: "#9ca3af", rotate: 30 },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#9ca3af" },
        splitLine: { lineStyle: { color: "#374151" } },
      },
      series: [
        {
          name: "Input",
          type: "bar",
          stack: "tokens",
          data: models.map((m) => byModel.get(m)?.input || 0),
          itemStyle: { color: COLORS[0] },
        },
        {
          name: "Output",
          type: "bar",
          stack: "tokens",
          data: models.map((m) => byModel.get(m)?.output || 0),
          itemStyle: { color: COLORS[1] },
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
  <h3 class="text-sm text-gray-400 mb-2">Model Distribution</h3>
  <div bind:this={chartEl} class="w-full h-64"></div>
</div>
