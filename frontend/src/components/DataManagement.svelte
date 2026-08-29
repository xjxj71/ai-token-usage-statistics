<script lang="ts">
  import { onMount } from "svelte";
  import {
    createBackup,
    deleteBackup,
    fetchBackups,
    fetchDataSettings,
    runCleanup,
    updateDataSettings,
  } from "../api/client";
  type BackupInfo = import("../api/client").BackupInfo;

  let expanded = $state(false);

  let settings = $state({ retention_days: 0, backup_keep: 10, auto_backup: true });
  let backups: BackupInfo[] = $state([]);

  let saving = $state(false);
  let saveMsg = $state("");
  let cleaning = $state(false);
  let cleanMsg = $state("");
  let backing = $state(false);
  let backupMsg = $state("");
  let busyBackup = $state("");

  function fmtSize(bytes: number): string {
    if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + " KB";
    return bytes + " B";
  }

  function fmtTime(iso: string): string {
    try {
      return new Date(iso).toLocaleString();
    } catch {
      return iso;
    }
  }

  async function load() {
    try {
      settings = await fetchDataSettings();
    } catch {
      // defaults stay in place
    }
    try {
      backups = await fetchBackups();
    } catch {
      // backup list is optional
    }
  }

  onMount(load);

  async function handleSave() {
    saving = true;
    saveMsg = "";
    try {
      const res = await updateDataSettings({
        retention_days: Number(settings.retention_days) || 0,
        backup_keep: Number(settings.backup_keep) || 1,
        auto_backup: settings.auto_backup,
      });
      settings = res.settings;
      saveMsg = "已保存";
    } catch (e: any) {
      saveMsg = e.message || "保存失败";
    } finally {
      saving = false;
      setTimeout(() => (saveMsg = ""), 3000);
    }
  }

  async function handleCleanup() {
    if (settings.retention_days <= 0) {
      cleanMsg = "请先设置保留天数（0 表示永久保留）";
      return;
    }
    if (!window.confirm(`确定立即清理 ${settings.retention_days} 天前的明细数据？\n（会先按天聚合归档，趋势与汇总不受影响）`)) {
      return;
    }
    cleaning = true;
    cleanMsg = "";
    try {
      const result = await runCleanup();
      cleanMsg = `已归档 ${result.archived_rows ?? 0} 行、删除 ${result.deleted_rows ?? 0} 行明细`;
      await load();
    } catch (e: any) {
      cleanMsg = e.message || "清理失败";
    } finally {
      cleaning = false;
    }
  }

  async function handleBackup() {
    backing = true;
    backupMsg = "";
    try {
      const info = await createBackup();
      backupMsg = `已创建 ${info.name}`;
      backups = await fetchBackups();
    } catch (e: any) {
      backupMsg = e.message || "备份失败";
    } finally {
      backing = false;
      setTimeout(() => (backupMsg = ""), 3000);
    }
  }

  async function handleDeleteBackup(name: string) {
    if (!window.confirm(`确定删除备份 ${name}？`)) return;
    busyBackup = name;
    try {
      await deleteBackup(name);
      backups = await fetchBackups();
    } catch (e: any) {
      window.alert(e.message || "删除失败");
    } finally {
      busyBackup = "";
    }
  }
</script>

<div class="dm-card">
  <button class="dm-header" onclick={() => (expanded = !expanded)}>
    <div class="flex items-center gap-2">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--amber)" stroke-width="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
      <span class="dm-title">数据管理</span>
      <span class="text-xs text-[var(--text-3)]">· 保留策略与备份</span>
    </div>
    <svg
      class="chevron {expanded ? 'open' : ''}"
      width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke="var(--text-3)" stroke-width="2"
    ><path d="M6 9l6 6 6-6"/></svg>
  </button>

  {#if expanded}
    <div class="dm-body">
      <div class="settings-row">
        <label class="field">
          <span class="field-label">明细保留天数</span>
          <input type="number" min="0" bind:value={settings.retention_days} />
          <span class="field-hint">0 = 永久保留；超期明细先按天聚合归档再删除，趋势/汇总历史不受影响</span>
        </label>
        <label class="field">
          <span class="field-label">备份保留个数</span>
          <input type="number" min="1" bind:value={settings.backup_keep} />
        </label>
        <label class="field checkbox">
          <input type="checkbox" bind:checked={settings.auto_backup} />
          <span>每日自动备份</span>
        </label>
        <button class="save-btn" onclick={handleSave} disabled={saving}>
          {saving ? "保存中..." : "保存设置"}
        </button>
        {#if saveMsg}<span class="msg">{saveMsg}</span>{/if}
      </div>

      <div class="actions-row">
        <button class="action-btn" onclick={handleCleanup} disabled={cleaning}>
          {cleaning ? "清理中..." : "立即清理"}
        </button>
        <button class="action-btn" onclick={handleBackup} disabled={backing}>
          {backing ? "备份中..." : "立即备份"}
        </button>
        {#if cleanMsg}<span class="msg">{cleanMsg}</span>{/if}
        {#if backupMsg}<span class="msg">{backupMsg}</span>{/if}
      </div>

      {#if backups.length > 0}
        <table class="backup-table">
          <thead>
            <tr>
              <th>备份文件</th>
              <th class="text-right">大小</th>
              <th>时间</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {#each backups as b (b.name)}
              <tr>
                <td class="mono">{b.name}</td>
                <td class="text-right">{fmtSize(b.size_bytes)}</td>
                <td class="text-[var(--text-3)]">{fmtTime(b.created_at)}</td>
                <td class="text-right">
                  <a class="link-btn" href="/api/backups/{encodeURIComponent(b.name)}" download>下载</a>
                  <button class="link-btn danger" onclick={() => handleDeleteBackup(b.name)} disabled={busyBackup === b.name}>
                    删除
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else}
        <div class="empty-hint">暂无备份 — 点击「立即备份」创建第一个</div>
      {/if}

      <div class="restore-hint">
        恢复方法：停止后端服务，用备份文件替换 <code>data/token_statistic.db</code> 后重新启动。
      </div>
    </div>
  {/if}
</div>

<style>
  .dm-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }
  .dm-header {
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
  .dm-header:hover {
    background: rgba(99, 102, 241, 0.06);
  }
  .dm-title {
    font-size: 14px;
    font-weight: 600;
  }
  .chevron {
    transition: transform 0.15s;
  }
  .chevron.open {
    transform: rotate(180deg);
  }
  .dm-body {
    padding: 16px 20px;
    border-top: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .settings-row {
    display: flex;
    align-items: flex-end;
    gap: 16px;
    flex-wrap: wrap;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 12px;
  }
  .field-label {
    color: var(--text-3);
  }
  .field input[type="number"] {
    width: 110px;
    padding: 6px 10px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
    font-size: 13px;
    outline: none;
  }
  .field input[type="number"]:focus {
    border-color: var(--amber);
  }
  .field-hint {
    font-size: 11px;
    color: var(--text-3);
    max-width: 340px;
  }
  .field.checkbox {
    flex-direction: row;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--text-2);
    padding-bottom: 8px;
  }
  .field.checkbox input {
    accent-color: var(--amber);
  }
  .save-btn,
  .action-btn {
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 13px;
    cursor: pointer;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-2);
    transition: all 0.2s;
  }
  .save-btn:hover:not(:disabled) {
    border-color: var(--primary);
    color: var(--text);
  }
  .action-btn:hover:not(:disabled) {
    border-color: var(--amber);
    color: var(--amber);
  }
  .save-btn:disabled,
  .action-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  .actions-row {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .msg {
    font-size: 12px;
    color: var(--green);
  }
  .backup-table {
    width: 100%;
    border-collapse: collapse;
  }
  .backup-table th {
    padding: 8px 12px;
    font-size: 11px;
    font-weight: 500;
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid var(--border);
    text-align: left;
  }
  .backup-table td {
    padding: 8px 12px;
    font-size: 13px;
    border-bottom: 1px solid rgba(51, 65, 85, 0.4);
    color: var(--text-2);
  }
  .backup-table .mono {
    font-family: ui-monospace, monospace;
    font-size: 12px;
  }
  .link-btn {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 12px;
    color: var(--cyan);
    text-decoration: none;
    border: none;
    background: transparent;
    cursor: pointer;
  }
  .link-btn:hover {
    background: rgba(34, 211, 238, 0.1);
  }
  .link-btn.danger {
    color: var(--red);
    margin-left: 4px;
  }
  .link-btn.danger:hover {
    background: rgba(239, 68, 68, 0.1);
  }
  .empty-hint,
  .restore-hint {
    font-size: 12px;
    color: var(--text-3);
  }
  .restore-hint code {
    font-family: ui-monospace, monospace;
    color: var(--text-2);
    background: var(--bg);
    padding: 1px 6px;
    border-radius: 4px;
  }
</style>
