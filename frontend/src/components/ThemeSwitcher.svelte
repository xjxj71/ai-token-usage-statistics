<script lang="ts">
  import { THEME_LIST, themeState, setTheme, type ThemeId } from "../theme.svelte.ts";

  let open = $state(false);

  function pick(id: ThemeId) {
    setTheme(id);
    open = false;
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") open = false;
  }

  const current = $derived(THEME_LIST.find((t) => t.id === themeState.current) ?? THEME_LIST[0]);
</script>

<svelte:window onkeydown={onKeydown} />

<div class="theme-switcher">
  <button class="theme-btn" onclick={() => (open = !open)} aria-expanded={open} title="切换主题">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="10"/>
      <path d="M12 2a10 10 0 000 20c1.1 0 2-.9 2-2v-1c0-.6.4-1 1-1h2a3 3 0 003-3c0-5-4-9-8-9z"/>
      <circle cx="7.5" cy="11.5" r="1"/><circle cx="10.5" cy="7.5" r="1"/><circle cx="15" cy="8" r="1"/>
    </svg>
    <span class="theme-dot" style="background:{current.dot}"></span>
    <span class="theme-label">{current.label}</span>
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
  </button>
  {#if open}
    <div class="theme-menu" role="menu">
      {#each THEME_LIST as t (t.id)}
        <button class="theme-option" class:active={t.id === themeState.current} role="menuitem" onclick={() => pick(t.id)}>
          <span class="theme-dot" style="background:{t.dot}"></span>
          <span class="theme-option-text">
            <span class="theme-option-label">{t.label}</span>
            <span class="theme-option-hint">{t.hint}</span>
          </span>
          {#if t.id === themeState.current}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="3"><path d="M20 6L9 17l-5-5"/></svg>
          {/if}
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .theme-switcher {
    position: relative;
  }
  .theme-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    font-size: 11px;
    font-family: inherit;
    color: var(--text-2);
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
  }
  .theme-btn:hover {
    border-color: var(--primary);
    color: var(--text);
  }
  .theme-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .theme-label {
    white-space: nowrap;
  }
  .theme-menu {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    z-index: 50;
    min-width: 200px;
    padding: 5px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: var(--shadow-pop);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .theme-option {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 7px 9px;
    font-family: inherit;
    text-align: left;
    background: transparent;
    border: none;
    border-radius: 7px;
    cursor: pointer;
    color: var(--text-2);
  }
  .theme-option:hover {
    background: rgba(var(--primary-rgb), 0.1);
    color: var(--text);
  }
  .theme-option.active {
    background: rgba(var(--primary-rgb), 0.12);
    color: var(--text);
  }
  .theme-option-text {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .theme-option-label {
    font-size: 12px;
    font-weight: 600;
  }
  .theme-option-hint {
    font-size: 10px;
    color: var(--text-3);
  }
</style>