<script lang="ts">
  import type { TimeRange } from "../types";

  interface Props {
    current: TimeRange;
    onchange: (range: TimeRange, from?: string, to?: string) => void;
  }

  let { current, onchange }: Props = $props();

  const ranges: { key: TimeRange; label: string }[] = [
    { key: "today", label: "今日" },
    { key: "7d", label: "7 天" },
    { key: "30d", label: "30 天" },
    { key: "custom", label: "自定义" },
  ];

  let customFrom = $state("");
  let customTo = $state("");
  let showCustomInputs = $state(false);

  function selectRange(key: TimeRange) {
    if (key === "custom") {
      showCustomInputs = true;
    } else {
      showCustomInputs = false;
      onchange(key);
    }
  }

  function applyCustom() {
    onchange("custom", customFrom, customTo);
  }
</script>

<div class="flex items-center gap-1 bg-[var(--card)] rounded-xl p-1 border border-[var(--border)]">
  {#each ranges as r}
    <button
      class="tab-btn {(current === r.key || (r.key === 'custom' && showCustomInputs)) ? 'active' : ''}"
      onclick={() => selectRange(r.key)}
    >
      {r.label}
    </button>
  {/each}

  {#if showCustomInputs}
    <div class="flex items-center gap-2 ml-3 pl-3 border-l border-[var(--border)]">
      <input
        type="date"
        bind:value={customFrom}
        class="date-input"
      />
      <span class="text-[var(--text-3)]">-</span>
      <input
        type="date"
        bind:value={customTo}
        class="date-input"
      />
      <button class="apply-btn" onclick={applyCustom}>应用</button>
    </div>
  {/if}
</div>

<style>
  .tab-btn {
    padding: 8px 16px;
    border-radius: 10px;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
    background: transparent;
    color: var(--text-3);
    border: none;
  }
  .tab-btn:hover {
    color: var(--text);
    background: rgba(99, 102, 241, 0.1);
  }
  .tab-btn.active {
    background: var(--primary);
    color: #fff;
  }
  .date-input {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
    color: var(--text);
    outline: none;
  }
  .date-input:focus {
    border-color: var(--primary);
  }
  .apply-btn {
    padding: 6px 14px;
    font-size: 13px;
    background: var(--primary);
    color: #fff;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    transition: opacity 0.2s;
  }
  .apply-btn:hover {
    opacity: 0.85;
  }
</style>
