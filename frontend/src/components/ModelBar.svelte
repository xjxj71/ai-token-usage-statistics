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

  function formatTokens(n: number): string {
    if (n >= 1e8) return (n / 1e8).toFixed(1) + "亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + "万";
    return n.toLocaleString();
  }

  function truncate(name: string, max = 12): string {
    return name.length > max ? name.slice(0, max) + "..." : name;
  }

  function buildOption(data: BreakdownItem[]) {
    // 按 total token 降序排列
    const sorted = [...data].sort((a, b) => {
      const totalA = a.input_tokens + a.output_tokens + a.cache_read_tokens + a.cache_write_tokens;
      const totalB = b.input_tokens + b.output_tokens + b.cache_read_tokens + b.cache_write_tokens;
      return totalB - totalA;
    });

    const modelNames = sorted.map((d) => d.model || "未知");
    const hasLongNames = modelNames.some((n) => n.length > 10);
    const count = modelNames.length;
    // 模型少时不旋转；模型多或有长名称时旋转 45 度
    const rotate = count > 8 || hasLongNames ? 45 : count > 5 ? 25 : 0;
    // 底部留白：旋转时需要更多空间
    const bottomPct = rotate > 0 ? Math.min(15 + count * 1.5, 25) : 8;

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "#1f2937",
        borderColor: "#374151",
        textStyle: { color: "#e5e7eb" },
        axisPointer: { type: "shadow" },
        formatter: (params: any[]) => {
          // tooltip 显示完整模型名
          const fullName = modelNames[params[0].dataIndex] || params[0].axisValue;
          let html = `<b>${fullName}</b><br/>`;
          let total = 0;
          for (const p of params) {
            total += p.value;
            html += `${p.marker} ${p.seriesName}: <b>${formatTokens(p.value)}</b><br/>`;
          }
          html += `合计: <b>${formatTokens(total)}</b>`;
          return html;
        },
      },
      legend: {
        data: ["输入 Token", "输出 Token", "缓存读取", "缓存写入"],
        textStyle: { color: "#9ca3af" },
        top: 0,
      },
      grid: { left: "3%", right: "4%", bottom: `${bottomPct}%`, top: "14%", containLabel: true },
      xAxis: {
        type: "category",
        data: modelNames.map((n) => truncate(n)),
        axisLabel: {
          color: "#9ca3af",
          rotate,
          fontSize: 11,
          interval: 0,
          overflow: "truncate",
          width: 90,
        },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: "#9ca3af",
          formatter: (val: number) => formatTokens(val),
        },
        splitLine: { lineStyle: { color: "#374151" } },
      },
      series: [
        {
          name: "输入 Token",
          type: "bar",
          stack: "tokens",
          data: sorted.map((d) => d.input_tokens),
          itemStyle: { color: "#5B8FF9" },
        },
        {
          name: "输出 Token",
          type: "bar",
          stack: "tokens",
          data: sorted.map((d) => d.output_tokens),
          itemStyle: { color: "#5AD8A6" },
        },
        {
          name: "缓存读取",
          type: "bar",
          stack: "tokens",
          data: sorted.map((d) => d.cache_read_tokens),
          itemStyle: { color: "#F6BD16" },
        },
        {
          name: "缓存写入",
          type: "bar",
          stack: "tokens",
          data: sorted.map((d) => d.cache_write_tokens),
          itemStyle: { color: "#E86452" },
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
  <h3 class="text-sm text-gray-400 mb-2">模型 Token 用量对比</h3>
  <div bind:this={chartEl} class="w-full h-64"></div>
</div>
