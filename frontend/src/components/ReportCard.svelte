<script lang="ts">
  import { fetchReport } from "../api/client";
  import { buildParams } from "../api/params";
  import type { FilterState, ReportResponse, ReportTopItem } from "../types";

  interface Props {
    filter: FilterState;
    usdToCnyRate?: number;
  }

  let { filter, usdToCnyRate = 7.25 }: Props = $props();

  let report: ReportResponse | null = $state(null);
  let loading = $state(false);
  let error = $state("");
  let expanded = $state(false);
  let copying = $state(false);
  let copyMsg = $state("");

  let lastParamsKey: string | null = null;

  function fmtTokens(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (n >= 10_000) return (n / 10_000).toFixed(1) + "万";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    return n.toLocaleString();
  }

  function delta(cur: number, prev: number): string {
    if (prev <= 0) return "—";
    const pct = ((cur - prev) / prev) * 100;
    return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
  }

  async function load(params: Record<string, string>) {
    loading = true;
    error = "";
    try {
      report = await fetchReport(params);
    } catch (e: any) {
      error = e.message || "报告加载失败";
    } finally {
      loading = false;
    }
  }

  // Refetch when the dashboard filter changes (not on every SSE data refresh)
  $effect(() => {
    const params = buildParams(filter);
    const key = JSON.stringify(params);
    if (key === lastParamsKey) return;
    lastParamsKey = key;
    void load(params);
  });

  async function handleCopy() {
    if (!report) return;
    copying = true;
    copyMsg = "";
    try {
      await navigator.clipboard.writeText(report.markdown);
      copyMsg = "已复制";
    } catch {
      copyMsg = "复制失败（浏览器拒绝剪贴板访问）";
    } finally {
      copying = false;
      setTimeout(() => (copyMsg = ""), 2500);
    }
  }

  function topList(items: ReportTopItem[]) {
    return items.slice(0, 3);
  }
</script>

<div class="report-card">
  <button class="report-header" onclick={() => (expanded = !expanded)}>
    <div class="flex items-center gap-2">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--cyan)" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
      <span class="report-title">用量报告</span>
      {#if report}
        <span class="text-xs text-[var(--text-3)]">· {report.label}</span>
        <span class="report-chip">总 {fmtTokens(report.totals.total_tokens)} · ¥{(report.totals.cost_usd * usdToCnyRate).toFixed(2)}</span>
      {/if}
    </div>
    <div class="flex items-center gap-2">
      {#if loading}
        <svg class="animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="2"><path d="M21 12a9 9 0 11-6.219-8.56"/></svg>
      {/if}
      <svg
        class="chevron {expanded ? 'open' : ''}"
        width="14" height="14" viewBox="0 0 24 24" fill="none"
        stroke="var(--text-3)" stroke-width="2"
      ><path d="M6 9l6 6 6-6"/></svg>
    </div>
  </button>

  {#if expanded}
    <div class="report-body">
      {#if error}
        <div class="report-error">{error}</div>
      {:else if report}
        <div class="report-grid">
          <div class="report-section">
            <h4>消耗概览（环比）</h4>
            <ul class="metric-list">
              <li><span>总 Token</span><b>{fmtTokens(report.totals.total_tokens)} <em>{delta(report.totals.total_tokens, report.previous.total_tokens)}</em></b></li>
              <li><span>思考 Token</span><b>{fmtTokens(report.totals.reasoning_tokens)} <em>{delta(report.totals.reasoning_tokens, report.previous.reasoning_tokens)}</em></b></li>
              <li><span>费用</span><b>¥{(report.totals.cost_usd * usdToCnyRate).toFixed(2)} <em>{delta(report.totals.cost_usd, report.previous.cost_usd)}</em></b></li>
              <li><span>请求次数</span><b>{report.totals.call_count.toLocaleString()} <em>{delta(report.totals.call_count, report.previous.call_count)}</em></b></li>
            </ul>
          </div>
          <div class="report-section">
            <h4>Top Agent（按 Token）</h4>
            <ol class="top-list">
              {#each topList(report.top_agents) as it, i}
                <li><span class="rank">{i + 1}</span>{it.name}<b>{fmtTokens(it.total_tokens)}</b></li>
              {:else}
                <li class="empty">暂无数据</li>
              {/each}
            </ol>
          </div>
          <div class="report-section">
            <h4>Top 模型（按费用）</h4>
            <ol class="top-list">
              {#each topList(report.top_models) as it, i}
                <li><span class="rank">{i + 1}</span>{it.name}<b>¥{(it.cost_usd * usdToCnyRate).toFixed(2)}</b></li>
              {:else}
                <li class="empty">暂无数据</li>
              {/each}
            </ol>
          </div>
          <div class="report-section">
            <h4>Top 项目（按 Token）</h4>
            <ol class="top-list">
              {#each topList(report.top_projects) as it, i}
                <li><span class="rank">{i + 1}</span>{it.name}<b>{fmtTokens(it.total_tokens)}</b></li>
              {:else}
                <li class="empty">暂无数据</li>
              {/each}
            </ol>
          </div>
        </div>

        {#if report.quota.length > 0}
          <div class="quota-line">
            {#each report.quota as q}
              <span class="quota-chip" title="{q.display_name} · {q.source}">
                {q.display_name}
                {#if q.total}
                  {((q.used ?? 0) / q.total * 100).toFixed(0)}% 已用
                {:else}
                  暂无数据
                {/if}
              </span>
            {/each}
          </div>
        {/if}

        <div class="report-actions">
          <button class="copy-btn" onclick={handleCopy} disabled={copying || !report}>
            {#if copying}复制中...{:else}{copyMsg || "复制 Markdown 报告"}{/if}
          </button>
        </div>
      {:else}
        <div class="report-error">加载中...</div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .report-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }
  .report-header {
    width: 100%;
    padding: 14px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: transparent;
    border: none;
    cursor: pointer;
    color: var(--text);
  }
  .report-header:hover {
    background: rgba(99, 102, 241, 0.06);
  }
  .report-title {
    font-size: 14px;
    font-weight: 600;
  }
  .report-chip {
    font-size: 12px;
    color: var(--text-2);
    padding: 2px 10px;
    border: 1px solid var(--border);
    border-radius: 9999px;
  }
  .chevron {
    transition: transform 0.15s;
  }
  .chevron.open {
    transform: rotate(180deg);
  }
  .report-body {
    padding: 4px 20px 16px;
    border-top: 1px solid var(--border);
  }
  .report-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 20px;
    padding-top: 12px;
  }
  .report-section h4 {
    font-size: 12px;
    font-weight: 500;
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 10px;
  }
  .metric-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .metric-list li {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: 13px;
  }
  .metric-list li span {
    color: var(--text-3);
  }
  .metric-list li em {
    font-style: normal;
    font-size: 11px;
    color: var(--text-3);
    margin-left: 6px;
  }
  .top-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .top-list li {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--text-2);
  }
  .top-list li b {
    margin-left: auto;
    color: var(--text);
    font-weight: 500;
  }
  .top-list .rank {
    width: 18px;
    height: 18px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 4px;
    background: rgba(99, 102, 241, 0.15);
    color: var(--primary);
    font-size: 11px;
    flex-shrink: 0;
  }
  .top-list .empty {
    color: var(--text-3);
  }
  .quota-line {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 16px;
  }
  .quota-chip {
    font-size: 12px;
    color: var(--text-2);
    padding: 4px 12px;
    border: 1px solid var(--border);
    border-radius: 9999px;
  }
  .report-actions {
    margin-top: 14px;
    display: flex;
    justify-content: flex-end;
  }
  .copy-btn {
    padding: 7px 14px;
    border-radius: 8px;
    font-size: 13px;
    cursor: pointer;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-2);
    transition: all 0.2s;
  }
  .copy-btn:hover:not(:disabled) {
    border-color: var(--cyan);
    color: var(--cyan);
  }
  .copy-btn:disabled {
    opacity: 0.6;
  }
  .report-error {
    padding: 14px 0;
    font-size: 13px;
    color: var(--text-3);
  }
</style>
