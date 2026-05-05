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

  const COLORS = ["#4A90D9", "#50C878", "#FF6B6B", "#F5A623", "#9B59B6", "#1ABC9C"];

  function buildOption(data: BreakdownItem[]) {
    const byAgent = new Map<string, number>();
    for (const d of data) {
      byAgent.set(d.agent, (byAgent.get(d.agent) || 0) + d.input_tokens + d.output_tokens + (d.cache_read_tokens || 0) + (d.cache_write_tokens || 0));
    }

    const pieData = [...byAgent.entries()].map(([name, value]) => ({ name, value }));

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        backgroundColor: "#1f2937",
        borderColor: "#374151",
        textStyle: { color: "#e5e7eb" },
      },
      legend: {
        orient: "vertical",
        right: "5%",
        top: "center",
        textStyle: { color: "#9ca3af" },
      },
      series: [
        {
          type: "pie",
          radius: ["40%", "70%"],
          center: ["35%", "50%"],
          avoidLabelOverlap: false,
          itemStyle: { borderRadius: 6, borderColor: "#1f2937", borderWidth: 2 },
          label: { show: false },
          emphasis: { label: { show: true, fontSize: 14, fontWeight: "bold" } },
          data: pieData,
          color: COLORS,
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
  <h3 class="text-sm text-gray-400 mb-2">Agent 分布</h3>
  <div bind:this={chartEl} class="w-full h-64"></div>
</div>
