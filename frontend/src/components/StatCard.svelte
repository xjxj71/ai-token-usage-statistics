<script lang="ts">
  interface Props {
    title: string;
    value: number;
    unit?: string;
    prefix?: boolean;
    icon?: string; // trusted inline SVG from App (not user input)
    /** Signed percent change vs the previous period; undefined/0 hides the badge. */
    trend?: number;
    /** When true a decrease is good (e.g. cost) — colors are inverted. */
    goodWhenDown?: boolean;
    trendLabel?: string;
  }

  let { title, value, unit = "", prefix = false, icon = "", trend = undefined, goodWhenDown = false, trendLabel = "较上期" }: Props = $props();

  function formatNumber(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    if (prefix) return n.toFixed(2);
    return n.toLocaleString();
  }

  let display = $derived(
    prefix ? `${unit}${formatNumber(value)}` : `${formatNumber(value)} ${unit}`.trim()
  );

  let showTrend = $derived(trend !== undefined && Number.isFinite(trend) && trend !== 0);
</script>

<div class="stat-card group">
  <div class="flex items-center gap-2 mb-3">
    {#if icon}
      <div class="stat-icon">
        {@html icon}
      </div>
    {/if}
    <span class="text-xs uppercase tracking-wide text-[var(--text-3)]">{title}</span>
  </div>
  <p class="text-2xl font-bold mb-2">{display}</p>
  {#if showTrend}
    {@const up = (trend as number) > 0}
    {@const good = goodWhenDown ? !up : up}
    <div
      class="flex items-center gap-1 {good ? 'text-[var(--green)]' : 'text-[var(--red)]'}"
      title="{trendLabel}：{(trend as number) > 0 ? '+' : ''}{(trend as number).toFixed(1)}%"
    >
      {#if up}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M12 19V5M5 12l7-7 7 7"/></svg>
      {:else}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M12 5v14M5 12l7 7 7-7"/></svg>
      {/if}
      <span class="text-xs">{up ? '+' : ''}{(trend as number).toFixed(1)}%</span>
      <span class="text-[10px] text-[var(--text-3)]">{trendLabel}</span>
    </div>
  {/if}
</div>

<style>
  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    transition: transform 0.2s, border-color 0.2s;
  }
  .stat-card:hover {
    transform: translateY(-2px);
    border-color: var(--primary);
  }
  .stat-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 8px;
    background: rgba(99, 102, 241, 0.15);
  }
</style>
