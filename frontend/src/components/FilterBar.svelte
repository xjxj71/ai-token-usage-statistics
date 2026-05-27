<script lang="ts">
  import { onMount } from "svelte";

  interface Props {
    agents: string[];
    models: string[];
    selectedAgents: string[];
    selectedModels: string[];
    onchange: (agents: string[], models: string[]) => void;
  }

  let { agents, models, selectedAgents, selectedModels, onchange }: Props = $props();

  let showModels = $state(false);
  let containerEl: HTMLDivElement | undefined = $state();

  function handleClickOutside(e: MouseEvent) {
    if (containerEl && !containerEl.contains(e.target as Node)) {
      showModels = false;
    }
  }

  onMount(() => {
    document.addEventListener("click", handleClickOutside, true);
    return () => document.removeEventListener("click", handleClickOutside, true);
  });

  function toggleAgent(agent: string) {
    const next = selectedAgents.includes(agent)
      ? selectedAgents.filter((a) => a !== agent)
      : [...selectedAgents, agent];
    onchange(next, selectedModels);
  }

  function clearFilters() {
    onchange([], []);
  }

  const agentColors: Record<string, string> = {
    hermes: "#6366F1",
    "claude-code": "#8B5CF6",
    openclaw: "#10B981",
    openclaude: "#F59E0B",
    hanako: "#EC4899",
  };
</script>

<div bind:this={containerEl} class="filter-bar">
  <div class="flex items-center gap-3 flex-wrap">
    <span class="text-xs text-[var(--text-3)] uppercase tracking-wide shrink-0">Agent:</span>
    {#each agents as agent}
      {@const isActive = selectedAgents.length === 0 || selectedAgents.includes(agent)}
      {@const color = agentColors[agent] || "#6366F1"}
      <button
        class="agent-tag {isActive ? 'active' : ''}"
        style="--tag-color: {color}"
        onclick={() => toggleAgent(agent)}
      >
        <span class="tag-dot" style="background:{isActive ? color : 'var(--text-3)'}"></span>
        {agent}
      </button>
    {/each}

    {#if selectedAgents.length > 0 || selectedModels.length > 0}
      <button class="clear-btn" onclick={clearFilters}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
        清除
      </button>
    {/if}
  </div>
</div>

<style>
  .filter-bar {
    padding: 12px 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .agent-tag {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 14px;
    border-radius: 9999px;
    font-size: 13px;
    cursor: pointer;
    transition: all 0.2s;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-2);
  }
  .agent-tag:hover {
    border-color: var(--tag-color);
    color: var(--text);
  }
  .agent-tag.active {
    background: color-mix(in srgb, var(--tag-color) 15%, transparent);
    border-color: var(--tag-color);
    color: var(--text);
  }
  .tag-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    transition: background 0.2s;
  }
  .clear-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 6px 12px;
    border-radius: 9999px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.2s;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-3);
    margin-left: 8px;
  }
  .clear-btn:hover {
    border-color: var(--red);
    color: var(--red);
  }
</style>
