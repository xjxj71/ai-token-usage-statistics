<script lang="ts">
  import { onMount } from "svelte";

  interface Props {
    agents: string[];
    models: string[];
    projects: string[];
    selectedAgents: string[];
    selectedModels: string[];
    selectedProjects: string[];
    onchange: (agents: string[], models: string[], projects: string[]) => void;
  }

  let { agents, models, projects, selectedAgents, selectedModels, selectedProjects, onchange }: Props = $props();

  let showModels = $state(false);
  let showProjects = $state(false);
  let containerEl: HTMLDivElement | undefined = $state();

  function handleClickOutside(e: MouseEvent) {
    if (containerEl && !containerEl.contains(e.target as Node)) {
      showModels = false;
      showProjects = false;
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
    onchange(next, selectedModels, selectedProjects);
  }

  function toggleModel(model: string) {
    const next = selectedModels.includes(model)
      ? selectedModels.filter((m) => m !== model)
      : [...selectedModels, model];
    onchange(selectedAgents, next, selectedProjects);
  }

  function toggleProject(project: string) {
    const next = selectedProjects.includes(project)
      ? selectedProjects.filter((p) => p !== project)
      : [...selectedProjects, project];
    onchange(selectedAgents, selectedModels, next);
  }

  function clearFilters() {
    onchange([], [], []);
  }

  const agentColors: Record<string, string> = {
    hermes: "#6366F1",
    "hermes-win": "#818CF8",
    "claude-code": "#8B5CF6",
    openclaw: "#10B981",
    openclaude: "#F59E0B",
    hanako: "#EC4899",
    "mimo-code": "#0EA5E9",
    opencode: "#14B8A6",
    zcode: "#F97316",
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
        aria-pressed={isActive}
        onclick={() => toggleAgent(agent)}
      >
        <span class="tag-dot" style="background:{isActive ? color : 'var(--text-3)'}"></span>
        {agent}
      </button>
    {/each}

    {#if models.length > 0}
      <div class="project-select">
        <button
          class="project-toggle"
          aria-expanded={showModels}
          onclick={() => (showModels = !showModels)}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
          模型{selectedModels.length > 0 ? ` · ${selectedModels.length} 项` : ""}
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
        </button>
        {#if showModels}
          <div class="project-dropdown">
            {#each models as model}
              <label class="project-option">
                <input
                  type="checkbox"
                  checked={selectedModels.includes(model)}
                  onchange={() => toggleModel(model)}
                />
                <span class="truncate" title={model}>{model}</span>
              </label>
            {/each}
            {#if selectedModels.length > 0}
              <button class="project-clear" onclick={() => onchange(selectedAgents, [], selectedProjects)}>
                清除模型筛选
              </button>
            {/if}
          </div>
        {/if}
      </div>
    {/if}

    {#if projects.length > 0}
      <div class="project-select">
        <button
          class="project-toggle"
          aria-expanded={showProjects}
          onclick={() => (showProjects = !showProjects)}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2z"/></svg>
          项目{selectedProjects.length > 0 ? ` · ${selectedProjects.length} 项` : ""}
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
        </button>
        {#if showProjects}
          <div class="project-dropdown">
            {#each projects as project}
              <label class="project-option">
                <input
                  type="checkbox"
                  checked={selectedProjects.includes(project)}
                  onchange={() => toggleProject(project)}
                />
                <span class="truncate" title={project}>{project}</span>
              </label>
            {/each}
            {#if selectedProjects.length > 0}
              <button class="project-clear" onclick={() => onchange(selectedAgents, selectedModels, [])}>
                清除项目筛选
              </button>
            {/if}
          </div>
        {/if}
      </div>
    {/if}

    {#if selectedAgents.length > 0 || selectedModels.length > 0 || selectedProjects.length > 0}
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
  .project-select {
    position: relative;
    margin-left: 4px;
  }
  .project-toggle {
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
  .project-toggle:hover,
  .project-toggle:focus {
    border-color: var(--amber);
    color: var(--text);
  }
  .project-dropdown {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    z-index: 50;
    min-width: 220px;
    max-height: 280px;
    overflow-y: auto;
    padding: 8px;
    border-radius: 10px;
    border: 1px solid var(--border);
    background: var(--card);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .project-option {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    border-radius: 6px;
    font-size: 13px;
    color: var(--text-2);
    cursor: pointer;
  }
  .project-option:hover {
    background: rgba(99, 102, 241, 0.12);
    color: var(--text);
  }
  .project-option input {
    accent-color: var(--amber);
  }
  .project-clear {
    margin-top: 6px;
    padding: 6px 8px;
    border: none;
    border-top: 1px solid var(--border);
    background: transparent;
    color: var(--text-3);
    font-size: 12px;
    cursor: pointer;
    text-align: left;
  }
  .project-clear:hover {
    color: var(--red);
  }
</style>
