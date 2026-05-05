<script lang="ts">
  import type { TokenRecord } from "../types";

  interface Props {
    items: TokenRecord[];
    total: number;
    page: number;
    pageSize: number;
    onPageChange: (page: number) => void;
  }

  let { items, total, page, pageSize, onPageChange }: Props = $props();

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

  let totalPages = $derived(Math.max(1, Math.ceil(total / pageSize)));

  function pageNumbers(): number[] {
    const pages: number[] = [];
    const start = Math.max(1, page - 2);
    const end = Math.min(totalPages, page + 2);
    for (let i = start; i <= end; i++) pages.push(i);
    return pages;
  }
</script>

<div class="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
  <div class="px-4 py-3 border-b border-gray-700 flex justify-between items-center">
    <h3 class="text-sm text-gray-400">最近使用记录</h3>
    <span class="text-xs text-gray-500">共 {total} 条</span>
  </div>

  <div class="overflow-x-auto">
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-gray-700 text-gray-500 text-left">
          <th class="px-4 py-2 font-medium">时间</th>
          <th class="px-4 py-2 font-medium">Agent</th>
          <th class="px-4 py-2 font-medium">模型</th>
          <th class="px-4 py-2 font-medium text-right">输入</th>
          <th class="px-4 py-2 font-medium text-right">输出</th>
          <th class="px-4 py-2 font-medium text-right">缓存</th>
          <th class="px-4 py-2 font-medium text-right">费用</th>
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
        {:else}
          <tr>
            <td colspan="7" class="px-4 py-8 text-center text-gray-500">暂无使用记录</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <!-- Pagination UI -->
  {#if totalPages > 1}
    <div class="px-4 py-3 border-t border-gray-700 flex items-center justify-between">
      <span class="text-xs text-gray-500">
        第 {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} 条 / 共 {total} 条
      </span>
      <div class="flex items-center gap-1">
        <button
          class="px-2 py-1 text-xs rounded {page <= 1 ? 'text-gray-600 cursor-not-allowed' : 'text-gray-400 hover:bg-gray-700'}"
          disabled={page <= 1}
          onclick={() => onPageChange(page - 1)}
        >
          上一页
        </button>
        {#each pageNumbers() as p}
          <button
            class="px-2.5 py-1 text-xs rounded {p === page ? 'bg-blue-600 text-white' : 'text-gray-400 hover:bg-gray-700'}"
            onclick={() => onPageChange(p)}
          >
            {p}
          </button>
        {/each}
        <button
          class="px-2 py-1 text-xs rounded {page >= totalPages ? 'text-gray-600 cursor-not-allowed' : 'text-gray-400 hover:bg-gray-700'}"
          disabled={page >= totalPages}
          onclick={() => onPageChange(page + 1)}
        >
          下一页
        </button>
      </div>
    </div>
  {/if}
</div>
