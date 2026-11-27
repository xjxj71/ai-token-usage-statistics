<script lang="ts">
  import type { SummaryResponse, SummaryTotals, BreakdownItem, TrendResponse, TokenRecord } from "../types";
  import { countUp, formatNumber } from "../motion";
  import { agentColor } from "../theme.svelte.ts";
  import TrendLine from "./TrendLine.svelte";
  import AgentPie from "./AgentPie.svelte";
  import ModelBar from "./ModelBar.svelte";
  import ProjectBar from "./ProjectBar.svelte";

  interface Props {
    summary: SummaryResponse;
    cacheRatio: number;
    agentBreakdown: BreakdownItem[];
    modelBreakdown: BreakdownItem[];
    projectBreakdown: BreakdownItem[];
    trendByAgent: TrendResponse | null;
    usageItems: TokenRecord[];
    usdToCnyRate: number;
  }

  let { summary, cacheRatio, agentBreakdown, modelBreakdown, projectBreakdown, trendByAgent, usageItems, usdToCnyRate }: Props = $props();

  function delta(cur: number, prev: number | undefined | null): number | undefined {
    if (prev === undefined || prev === null || prev === 0) return undefined;
    return Math.round(((cur - prev) / prev) * 1000) / 10;
  }
  function d(key: keyof SummaryTotals): number | undefined {
    return delta(summary[key], summary.previous?.[key]);
  }

  const cost = $derived(summary.cost_usd * usdToCnyRate);
  const ringC = 2 * Math.PI * 27;
  const ringOffset = $derived(ringC * (1 - Math.min(1, Math.max(0, cacheRatio))));

  // hero 迷你走势：按日汇总各 agent 的 token 趋势
  const sparkValues = $derived.by(() => {
    if (!trendByAgent?.series?.length) return [];
    const n = trendByAgent.dates.length;
    const out = new Array(n).fill(0);
    for (const s of trendByAgent.series) {
      if (s.name === "总计") continue;
      s.data.forEach((v, i) => (out[i] += v));
    }
    return out;
  });
  const sparkPath = $derived.by(() => {
    const v = sparkValues;
    if (v.length < 2) return { line: "", area: "" };
    const max = Math.max(...v), min = Math.min(...v);
    const X = (i: number) => 2 + (i / (v.length - 1)) * 296;
    const Y = (x: number) => 50 - ((x - min) / (max - min || 1)) * 44;
    let line = "";
    v.forEach((x, i) => (line += (i ? " L" : "M") + X(i).toFixed(1) + "," + Y(x).toFixed(1)));
    return { line, area: line + ` L298,54 L2,54 Z` };
  });

  // 实时动态 tile：新记录高亮
  const feedItems = $derived((usageItems ?? []).slice(0, 5));
  let freshKey = $state("");
  let lastTopKey = "";
  $effect(() => {
    const top = feedItems[0];
    if (!top) return;
    const key = top.timestamp + top.agent + top.model;
    if (lastTopKey && key !== lastTopKey) {
      freshKey = key;
      const t = setTimeout(() => (freshKey = ""), 1800);
      return () => clearTimeout(t);
    }
    lastTopKey = key;
  });

  function fmtTime(ts: string): string {
    try {
      const t = new Date(ts);
      return [t.getHours(), t.getMinutes(), t.getSeconds()].map((x) => String(x).padStart(2, "0")).join(":");
    } catch {
      return ts;
    }
  }
</script>

<div class="bento">
  <!-- 费用 hero -->
  <div class="tile b-hero">
    <div class="t-label">总费用 · 当前范围 <span>CNY</span></div>
    <div class="t-hero" use:countUp={{ value: cost, format: (n) => "¥" + n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }), duration: 1000 }}></div>
    {#if d("cost_usd") !== undefined}
      {@const up = (d("cost_usd") ?? 0) > 0}
      <div class="delta" class:good={!up} class:bad={up}>{up ? "↑" : "↓"} {Math.abs(d("cost_usd") ?? 0).toFixed(1)}% <span>较上期 · 下降为好</span></div>
    {/if}
    {#if sparkPath.line}
      <svg class="hero-spark" viewBox="0 0 300 56" preserveAspectRatio="none">
        <path d={sparkPath.area} fill="var(--primary)" opacity=".12"/>
        <path d={sparkPath.line} fill="none" stroke="var(--primary)" stroke-width="1.8" stroke-linecap="round"/>
      </svg>
    {/if}
  </div>

  <!-- 总 Token -->
  <div class="tile b-4">
    <div class="t-label">总 TOKEN</div>
    <div class="t-mid" use:countUp={{ value: summary.total_tokens, format: formatNumber }}></div>
    {#if d("total_tokens") !== undefined}
      {@const up = (d("total_tokens") ?? 0) > 0}
      <div class="delta" class:good={up} class:bad={!up}>{up ? "↑" : "↓"} {Math.abs(d("total_tokens") ?? 0).toFixed(1)}% <span>较上期</span></div>
    {/if}
  </div>

  <!-- 缓存命中率环 -->
  <div class="tile b-4 b-ring">
    <div class="cache-ring">
      <svg width="64" height="64" viewBox="0 0 64 64">
        <circle cx="32" cy="32" r="27" fill="none" stroke="rgba(var(--border-rgb), .6)" stroke-width="6"/>
        <circle cx="32" cy="32" r="27" fill="none" stroke="var(--green)" stroke-width="6" stroke-linecap="round"
          stroke-dasharray={ringC} stroke-dashoffset={ringOffset} transform="rotate(-90 32 32)"/>
      </svg>
      <div class="ring-val" use:countUp={{ value: cacheRatio * 100, format: (n) => n.toFixed(1) + "%" }}></div>
    </div>
    <div>
      <div class="t-label">缓存命中率</div>
      <div class="t-sub">缓存 {formatNumber(summary.cache_tokens)} / 输入 {formatNumber(summary.input_tokens + summary.cache_tokens)}</div>
    </div>
  </div>

  <!-- 四个小指标 -->
  <div class="tile b-2">
    <div class="t-label">输入</div>
    <div class="t-sm" use:countUp={{ value: summary.input_tokens, format: formatNumber }}></div>
    {#if d("input_tokens") !== undefined}<div class="delta mini" class:good={(d("input_tokens") ?? 0) > 0} class:bad={(d("input_tokens") ?? 0) <= 0}>{(d("input_tokens") ?? 0) > 0 ? "↑" : "↓"} {Math.abs(d("input_tokens") ?? 0).toFixed(1)}%</div>{/if}
  </div>
  <div class="tile b-2">
    <div class="t-label">输出</div>
    <div class="t-sm" use:countUp={{ value: summary.output_tokens, format: formatNumber }}></div>
    {#if d("output_tokens") !== undefined}<div class="delta mini" class:good={(d("output_tokens") ?? 0) > 0} class:bad={(d("output_tokens") ?? 0) <= 0}>{(d("output_tokens") ?? 0) > 0 ? "↑" : "↓"} {Math.abs(d("output_tokens") ?? 0).toFixed(1)}%</div>{/if}
  </div>
  <div class="tile b-2">
    <div class="t-label">思考</div>
    <div class="t-sm" use:countUp={{ value: summary.reasoning_tokens, format: formatNumber }}></div>
    {#if d("reasoning_tokens") !== undefined}<div class="delta mini" class:good={(d("reasoning_tokens") ?? 0) > 0} class:bad={(d("reasoning_tokens") ?? 0) <= 0}>{(d("reasoning_tokens") ?? 0) > 0 ? "↑" : "↓"} {Math.abs(d("reasoning_tokens") ?? 0).toFixed(1)}%</div>{/if}
  </div>
  <div class="tile b-2">
    <div class="t-label">缓存</div>
    <div class="t-sm" use:countUp={{ value: summary.cache_tokens, format: formatNumber }}></div>
    {#if d("cache_tokens") !== undefined}<div class="delta mini" class:good={(d("cache_tokens") ?? 0) > 0} class:bad={(d("cache_tokens") ?? 0) <= 0}>{(d("cache_tokens") ?? 0) > 0 ? "↑" : "↓"} {Math.abs(d("cache_tokens") ?? 0).toFixed(1)}%</div>{/if}
  </div>

  <!-- 趋势大图 -->
  <div class="tile b-trend">
    <TrendLine data={trendByAgent} title="Token 用量趋势 · 按 Agent" />
  </div>

  <!-- 请求次数 -->
  <div class="tile b-4">
    <div class="t-label">请求次数</div>
    <div class="t-mid" use:countUp={{ value: summary.call_count, format: (n) => Math.round(n).toLocaleString() + " 次" }}></div>
    {#if d("call_count") !== undefined}
      {@const up = (d("call_count") ?? 0) > 0}
      <div class="delta" class:good={up} class:bad={!up}>{up ? "↑" : "↓"} {Math.abs(d("call_count") ?? 0).toFixed(1)}% <span>较上期</span></div>
    {/if}
  </div>

  <!-- 实时动态 -->
  <div class="tile b-4 b-feed">
    <div class="t-label">实时动态 <span>最新 {feedItems.length} 条</span></div>
    <div class="feed-list">
      {#each feedItems as r (r.timestamp + r.agent + r.model)}
        {@const key = r.timestamp + r.agent + r.model}
        <div class="feed-item" class:fresh={freshKey === key}>
          <span class="feed-dot" style="background:{agentColor(r.agent)}"></span>
          <span class="feed-agent">{r.agent}</span>
          <span class="feed-model">{r.model}</span>
          <span class="feed-time">{fmtTime(r.timestamp)}</span>
          <span class="feed-cost">¥{(r.cost_usd * usdToCnyRate).toFixed(2)}</span>
        </div>
      {/each}
    </div>
  </div>

  <!-- 分布三图 -->
  <div class="tile b-tall"><AgentPie breakdown={agentBreakdown} /></div>
  <div class="tile b-tall"><ModelBar breakdown={modelBreakdown} /></div>
  <div class="tile b-tall"><ProjectBar breakdown={projectBreakdown} /></div>
</div>

<style>
  .bento {
    display: grid;
    grid-template-columns: repeat(12, 1fr);
    gap: 12px;
  }
  .tile {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 15px 17px;
    position: relative;
    overflow: hidden;
    transition: transform .25s cubic-bezier(.2, .7, .3, 1), border-color .25s, box-shadow .25s;
    animation: tile-in .5s cubic-bezier(.2, .7, .3,1) backwards;
  }
  .tile:nth-child(1) { animation-delay: 0ms; }
  .tile:nth-child(2) { animation-delay: 50ms; }
  .tile:nth-child(3) { animation-delay: 100ms; }
  .tile:nth-child(4) { animation-delay: 150ms; }
  .tile:nth-child(5) { animation-delay: 200ms; }
  .tile:nth-child(6) { animation-delay: 250ms; }
  .tile:nth-child(7) { animation-delay: 300ms; }
  .tile:nth-child(8) { animation-delay: 350ms; }
  .tile:nth-child(9) { animation-delay: 400ms; }
  .tile:nth-child(10) { animation-delay: 450ms; }
  .tile:nth-child(11) { animation-delay: 500ms; }
  .tile:nth-child(12) { animation-delay: 550ms; }
  .tile:nth-child(13) { animation-delay: 600ms; }
  @keyframes tile-in { from { opacity: 0; transform: translateY(14px); } }
  .tile:hover {
    transform: translateY(-2px);
    border-color: rgba(var(--primary-rgb), .35);
    box-shadow: 0 8px 24px rgba(var(--bg-rgb), .5);
  }
  .b-hero { grid-column: span 4; grid-row: span 2; display: flex; flex-direction: column; }
  .b-4 { grid-column: span 4; }
  .b-2 { grid-column: span 2; }
  .b-trend { grid-column: span 8; grid-row: span 2; min-height: 340px; }
  .b-tall { grid-column: span 4; grid-row: span 2; min-height: 340px; }
  .b-ring { display: flex; align-items: center; gap: 14px; }

  .t-label {
    font-size: 10px;
    letter-spacing: 1px;
    color: var(--text-3);
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
  }
  .t-hero { font-size: 38px; font-weight: 800; letter-spacing: -1px; line-height: 1.1; }
  .t-mid { font-size: 24px; font-weight: 700; letter-spacing: -.5px; }
  .t-sm { font-size: 18px; font-weight: 700; }
  .t-sub { font-size: 10.5px; color: var(--text-2); }
  .delta {
    font-size: 10px;
    margin-top: 7px;
    display: inline-flex;
    gap: 4px;
    align-items: center;
    padding: 2px 8px;
    border-radius: 99px;
    width: fit-content;
  }
  .delta.mini { padding: 1px 6px; font-size: 9px; }
  .delta.good { color: var(--green); background: rgba(var(--green-rgb, 16, 185, 129), .1); }
  .delta.bad { color: var(--red); background: rgba(var(--red-rgb), .1); }
  .delta span { color: var(--text-3); }
  .hero-spark { margin-top: auto; width: 100%; height: 56px; }

  .cache-ring { position: relative; width: 64px; height: 64px; flex-shrink: 0; }
  .cache-ring circle { transition: stroke-dashoffset 1.1s cubic-bezier(.4, 0, .2, 1); }
  .ring-val { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 12.5px; font-weight: 700; }

  .feed-list { display: flex; flex-direction: column; gap: 5px; }
  .feed-item {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 10px;
    padding: 5px 8px;
    border-radius: 7px;
    background: rgba(var(--border-rgb), .25);
    border: 1px solid transparent;
    transition: background .4s, border-color .4s;
  }
  .feed-item.fresh {
    background: rgba(var(--green-rgb, 16, 185, 129), .08);
    border-color: rgba(var(--green-rgb, 16, 185, 129), .35);
    animation: feed-in .45s cubic-bezier(.2, .8, .3, 1);
  }
  @keyframes feed-in { from { opacity: 0; transform: translateY(-9px); } }
  .feed-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
  .feed-agent { font-weight: 600; max-width: 70px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .feed-model { color: var(--text-3); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .feed-time { color: var(--text-3); font-size: 9px; }
  .feed-cost { color: var(--text-2); }

  /* 图表组件去卡片化，融入 bento tile */
  .bento :global(.chart-card) {
    background: transparent;
    border: 0;
    padding: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
  }
  .bento :global(.chart-title) { font-size: 12px; margin-bottom: 8px; }
  .bento :global(.chart-body) { flex: 1; min-height: 240px; height: auto !important; }

  @media (max-width: 1400px) {
    .bento { grid-template-columns: repeat(4, 1fr); }
    .b-hero { grid-column: span 4; grid-row: span 1; }
    .b-4 { grid-column: span 2; }
    .b-2 { grid-column: span 1; }
    .b-trend { grid-column: span 4; grid-row: span 1; }
    .b-tall { grid-column: span 2; grid-row: span 1; }
  }
  @media (max-width: 760px) {
    .bento { grid-template-columns: 1fr 1fr; }
    .b-hero, .b-4, .b-trend, .b-tall { grid-column: span 2; }
    .b-2 { grid-column: span 1; }
  }
  @media (prefers-reduced-motion: reduce) {
    .tile, .feed-item.fresh { animation: none; }
    .tile, .cache-ring circle { transition: none; }
  }
</style>