<script lang="ts">
  import { onMount } from "svelte";
  import type { TokenRecord, SummaryResponse, BreakdownItem } from "../types";
  import { countUp, formatNumber } from "../motion";
  import { agentColor } from "../theme.svelte.ts";
  import AgentPie from "./AgentPie.svelte";
  import ModelBar from "./ModelBar.svelte";

  interface Props {
    items: TokenRecord[];
    summary: SummaryResponse;
    cacheRatio: number;
    agentBreakdown: BreakdownItem[];
    modelBreakdown: BreakdownItem[];
    usdToCnyRate: number;
    sseConnected: boolean;
  }

  let { items, summary, cacheRatio, agentBreakdown, modelBreakdown, usdToCnyRate, sseConnected }: Props = $props();

  let paused = $state(false);
  let frozenItems = $state<TokenRecord[]>([]);
  const displayItems = $derived(paused ? frozenItems : items);

  function togglePause() {
    if (!paused) frozenItems = items;
    paused = !paused;
  }

  // 新记录高亮：对比上一批 key，新增的标 fresh 1.8s。
  // 复位定时器放在 effect 之外：cleanup 在每次重跑前执行，挂在上面
  // 会被翻页/切筛选提前清掉，高亮永久残留。
  let known = new Set<string>();
  let freshKeys = $state<Set<string>>(new Set());
  let freshTimer: ReturnType<typeof setTimeout> | null = null;
  const keyOf = (r: TokenRecord) => r.timestamp + "|" + r.agent + "|" + r.model + "|" + r.session_id;
  $effect(() => {
    const keys = items.map(keyOf);
    if (known.size > 0 && !paused) {
      const added = keys.filter((k) => !known.has(k));
      if (added.length > 0) {
        freshKeys = new Set(added);
        if (freshTimer) clearTimeout(freshTimer);
        freshTimer = setTimeout(() => {
          freshKeys = new Set();
          freshTimer = null;
        }, 1800);
      }
    }
    known = new Set(keys);
  });
  onMount(() => () => {
    if (freshTimer) clearTimeout(freshTimer);
  });

  function fmtTime(ts: string): string {
    try {
      const t = new Date(ts);
      return [t.getHours(), t.getMinutes(), t.getSeconds()].map((x) => String(x).padStart(2, "0")).join(":");
    } catch {
      return ts;
    }
  }
  function fmtK(n: number): string {
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(0) + "K";
    return String(n);
  }
</script>

<div class="monitor">
  <div class="feed-pane">
    <div class="feed-head">
      <span class="feed-title">实时使用流</span>
      <span class="feed-sub">{sseConnected ? "SSE 推送 · 自动刷新" : "连接断开 · 等待重连"}</span>
      <button class="feed-toggle" onclick={togglePause}>{paused ? "▶ 恢复" : "⏸ 暂停"}</button>
    </div>
    {#if paused}<div class="paused-note">已暂停 — 画面冻结，恢复后回到最新</div>{/if}
    <div class="feed-cols">
      <span>时间</span><span>AGENT</span><span>模型</span><span>项目</span>
      <span class="num">输入</span><span class="num">输出</span><span class="num">费用</span>
    </div>
    <div class="feed-scroll">
      {#each displayItems as r (keyOf(r))}
        <div class="rec" class:fresh={freshKeys.has(keyOf(r))}>
          <span class="rec-time">{fmtTime(r.timestamp)}</span>
          <span class="rec-agent"><span class="rec-dot" style="background:{agentColor(r.agent)}"></span>{r.agent}</span>
          <span class="rec-model">{r.model}</span>
          <span class="rec-proj">{r.project || "—"}</span>
          <span class="rec-num">{fmtK(r.input_tokens)}</span>
          <span class="rec-num">{fmtK(r.output_tokens)}</span>
          <span class="rec-cost">¥{(r.cost_usd * usdToCnyRate).toFixed(2)}</span>
        </div>
      {/each}
      {#if displayItems.length === 0}
        <div class="feed-empty">当前范围内暂无记录</div>
      {/if}
    </div>
  </div>

  <div class="rail">
    <div class="r-card">
      <div class="r-title">总费用 · 当前范围</div>
      <div class="r-big" use:countUp={{ value: summary.cost_usd * usdToCnyRate, format: (n) => "¥" + n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}></div>
      <div class="r-sub">总 Token {formatNumber(summary.total_tokens)} · 请求 {summary.call_count.toLocaleString()} 次</div>
    </div>
    <div class="r-card">
      <div class="r-title">缓存命中率</div>
      <div class="r-big" use:countUp={{ value: cacheRatio * 100, format: (n) => n.toFixed(1) + "%" }}></div>
      <div class="r-bar"><div class="r-fill" style="width:{Math.min(100, cacheRatio * 100)}%"></div></div>
    </div>
    <div class="r-card r-chart"><AgentPie breakdown={agentBreakdown} compact /></div>
    <div class="r-card r-chart"><ModelBar breakdown={modelBreakdown} compact /></div>
  </div>
</div>

<style>
  .monitor {
    display: grid;
    grid-template-columns: 1fr 320px;
    gap: 14px;
    height: calc(100vh - 150px);
    min-height: 480px;
  }
  .feed-pane {
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    overflow: hidden;
  }
  .feed-head { display: flex; align-items: center; gap: 12px; padding: 12px 18px; border-bottom: 1px solid var(--border); }
  .feed-title { font-size: 12.5px; font-weight: 700; }
  .feed-sub { font-size: 10px; color: var(--text-3); }
  .feed-toggle {
    margin-left: auto;
    font-size: 10.5px;
    font-family: inherit;
    color: var(--text-2);
    background: rgba(var(--border-rgb), .3);
    border: 1px solid var(--border);
    border-radius: 7px;
    padding: 4px 12px;
    cursor: pointer;
    transition: all .2s;
  }
  .feed-toggle:hover { color: var(--text); border-color: rgba(var(--primary-rgb), .4); }
  .paused-note { text-align: center; font-size: 10px; color: var(--amber); padding: 6px; background: rgba(var(--amber-rgb), .08); }
  .feed-cols {
    display: grid;
    grid-template-columns: 70px 110px 1fr 130px 64px 64px 64px;
    gap: 10px;
    padding: 7px 18px;
    font-size: 9px;
    letter-spacing: 1px;
    color: var(--text-3);
    border-bottom: 1px solid var(--border);
  }
  .feed-cols .num { text-align: right; }
  .feed-scroll { flex: 1; overflow-y: auto; padding: 6px 10px 14px; }
  .feed-scroll::-webkit-scrollbar { width: 8px; }
  .feed-scroll::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
  .rec {
    display: grid;
    grid-template-columns: 70px 110px 1fr 130px 64px 64px 64px;
    gap: 10px;
    align-items: center;
    padding: 7px 8px;
    border-radius: 8px;
    font-size: 11px;
    border: 1px solid transparent;
    transition: background .4s, border-color .4s;
  }
  .rec:hover { background: rgba(var(--border-rgb), .25); }
  .rec.fresh {
    background: rgba(var(--green-rgb, 16, 185, 129), .07);
    border-color: rgba(var(--green-rgb, 16, 185, 129), .3);
    animation: rec-in .45s cubic-bezier(.2, .8, .3, 1);
  }
  @keyframes rec-in { from { opacity: 0; transform: translateY(-12px); } }
  .rec-time { color: var(--text-3); font-size: 10px; }
  .rec-agent { display: flex; align-items: center; gap: 7px; font-weight: 600; font-size: 10.5px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .rec-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .rec-model { color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rec-proj { color: var(--text-3); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rec-num { text-align: right; color: var(--text-2); font-size: 10.5px; }
  .rec-cost { text-align: right; font-weight: 600; color: var(--text-2); }
  .feed-empty { text-align: center; color: var(--text-3); font-size: 11px; padding: 30px; }

  .rail { display: flex; flex-direction: column; gap: 12px; overflow-y: auto; min-height: 0; padding-right: 2px; }
  .rail::-webkit-scrollbar { width: 8px; }
  .rail::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
  .r-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 14px 16px;
    flex-shrink: 0;
  }
  .r-title { font-size: 10px; letter-spacing: 1.2px; color: var(--text-3); margin-bottom: 8px; }
  .r-big { font-size: 25px; font-weight: 800; letter-spacing: -.5px; }
  .r-sub { font-size: 10px; color: var(--text-2); margin-top: 5px; }
  .r-bar { height: 6px; border-radius: 99px; background: rgba(var(--border-rgb), .5); overflow: hidden; margin-top: 10px; }
  .r-fill { height: 100%; border-radius: 99px; background: var(--green); transition: width 1s cubic-bezier(.4, 0, .2, 1); }
  .r-chart :global(.chart-card) { background: transparent; border: 0; padding: 0; }
  .r-chart :global(.chart-title) { font-size: 11px; margin-bottom: 6px; }
  .r-chart :global(.chart-body) { height: 240px !important; }

  @media (max-width: 1100px) {
    .monitor { grid-template-columns: 1fr; height: auto; }
    .feed-pane { height: 480px; }
    .rail { flex-direction: row; flex-wrap: wrap; overflow: visible; }
    .r-card { flex: 1 1 240px; }
  }
  /* 新记录高亮由数据推送触发、一次性播放，不做 reduced-motion 门禁 */
</style>