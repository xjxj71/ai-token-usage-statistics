<script lang="ts">
  import type { TokenRecord } from "../types";

  interface Props {
    items: TokenRecord[];
    total: number;
    page: number;
  }

  let { items, total, page }: Props = $props();

  function fmt(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    return n.toLocaleString();
  }

  function fmtTime(ts: string): string {
    try {
      return new Date(ts).toLocaleString();
    } catch {
      return ts;
    }
  }
</script>

<div class="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
  <div class="px-4 py-3 border-b border-gray-700 flex justify-between items-center">
    <h3 class="text-sm text-gray-400">Recent Usage</h3>
    <span class="text-xs text-gray-500">{total} records</span>
  </div>

  <div class="overflow-x-auto">
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-gray-700 text-gray-500 text-left">
          <th class="px-4 py-2 font-medium">Time</th>
          <th class="px-4 py-2 font-medium">Agent</th>
          <th class="px-4 py-2 font-medium">Model</th>
          <th class="px-4 py-2 font-medium text-right">Input</th>
          <th class="px-4 py-2 font-medium text-right">Output</th>
          <th class="px-4 py-2 font-medium text-right">Cache</th>
          <th class="px-4 py-2 font-medium text-right">Cost</th>
        </tr>
      </thead>
      <tbody>
        {#each items as item}
          <tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
            <td class="px-4 py-2 text-gray-400">{fmtTime(item.timestamp)}</td>
            <td class="px-4 py-2">
              <span
                class="px-2 py-0.5 rounded text-xs {item.agent === 'claude-code'
                  ? 'bg-blue-900 text-blue-300'
                  : item.agent === 'hermes'
                    ? 'bg-green-900 text-green-300'
                    : 'bg-red-900 text-red-300'}"
              >
                {item.agent}
              </span>
            </td>
            <td class="px-4 py-2 text-gray-300">{item.model}</td>
            <td class="px-4 py-2 text-right text-gray-400">{fmt(item.input_tokens)}</td>
            <td class="px-4 py-2 text-right text-gray-400">{fmt(item.output_tokens)}</td>
            <td class="px-4 py-2 text-right text-gray-400">
              {fmt(item.cache_read_tokens + item.cache_write_tokens)}
            </td>
            <td class="px-4 py-2 text-right text-yellow-400">${item.cost_usd.toFixed(4)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>
