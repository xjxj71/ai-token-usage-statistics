<script lang="ts">
  interface Props {
    title: string;
    value: number;
    unit?: string;
    prefix?: boolean;
  }

  let { title, value, unit = "", prefix = false }: Props = $props();

  function formatNumber(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    if (unit === "$" || prefix) return n.toFixed(2);
    return n.toLocaleString();
  }

  let display = $derived(
    prefix ? `${unit}${formatNumber(value)}` : `${formatNumber(value)} ${unit}`.trim()
  );
</script>

<div class="bg-gray-800 rounded-lg p-4 border border-gray-700">
  <p class="text-xs text-gray-500 uppercase tracking-wide mb-1">{title}</p>
  <p class="text-2xl font-semibold text-white">{display}</p>
</div>
