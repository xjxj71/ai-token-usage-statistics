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

  const COLORS = ["#5B8FF9", "#5AD8A6", "#F6BD16", "#E86452", "#6DC8EC", "#945FB9"];

  function fmt(n: number): string {
    if (n >= 1e8) return (n / 1e8).toFixed(2) + " 亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + " 万";
    return n.toLocaleString();
  }

  function buildOption(data: BreakdownItem[]) {
    const pieData = data.map((d) => ({
      name: d.agent || "未知",
      value: d.input_tokens + d.output_tokens + d.cache_read_tokens + d.cache_write_tokens,
    }));

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        backgroundColor: "#1f2937",
        borderColor: "#374151",
        textStyle: { color: "#e5e7eb" },
        formatter: (params: any) => {
          const val = params.value as number;
          return `<b>${params.name}</b><br/>`
            + `总 Token: <b>${fmt(val)}</b><br/>`
            + `占比: <b>${params.percent}%</b>`;
        },
      },
      legend: {
        orient: "horizontal",
        bottom: 0,
        textStyle: { color: "#9ca3af" },
      },
      series: [
        {
          name: "Agent Token 总消耗",
          type: "pie",
          radius: ["35%", "65%"],
          center: ["50%", "45%"],
          avoidLabelOverlap: true,
          itemStyle: {
            borderRadius: 6,
            borderColor: "#1f2937",
            borderWidth: 2,
          },
          label: {
            show: true,
            color: "#d1d5db",
            formatter: (params: any) => {
              return `${params.name}\n${fmt(params.value)} (${params.percent}%)`;
            },
          },
          emphasis: {
            label: { show: true, fontSize: 14, fontWeight: "bold" },
          },
          data: pieData,
          color: COLORS,
        },
      ],
    };
  }

  $effect(() => {
    if (!chartEl || !breakdown?.length) return;
    if (!chart) {
      chart = echarts.init(chartEl, "dark");
    }
    chart.setOption(buildOption(breakdown), true);
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
  <h3 class="text-sm text-gray-400 mb-2">Agent Token 总消耗占比</h3>
  <div bind:this={chartEl} class="w-full h-80"></div>
</div>
