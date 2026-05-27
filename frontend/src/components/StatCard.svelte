<script lang="ts">
  interface Props {
    title: string;
    value: number;
    unit?: string;
    prefix?: boolean;
    icon?: string;
    trend?: number;
    trendUp?: boolean;
  }

  let { title, value, unit = "", prefix = false, icon = "", trend = 0, trendUp = true }: Props = $props();

  function formatNumber(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    if (prefix) return n.toFixed(2);
    return n.toLocaleString();
  }

  let display = $derived(
    prefix ? `${unit}${formatNumber(value)}` : `${formatNumber(value)} ${unit}`.trim()
  );
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
  {#if trend > 0}
    <div class="flex items-center gap-1 {trendUp ? 'text-[var(--green)]' : 'text-[var(--red)]'}">
      {#if trendUp}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M12 19V5M5 12l7-7 7 7"/></svg>
      {:else}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M12 5v14M5 12l7 7 7-7"/></svg>
      {/if}
      <span class="text-xs">{trendUp ? '+' : '-'}{trend}%</span>
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
