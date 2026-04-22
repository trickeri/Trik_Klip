<script lang="ts">
  import ProgressBar from '../components/ProgressBar.svelte';
  import {
    pipelineRunning, outputDir, activeProfile, currentStage,
    sliceProgress, visualProgress,
    addLog, resetProgress,
  } from '../lib/stores';
  import { apiFetch } from '../lib/api';

  interface ClipFolderEntry {
    folder_name: string;
    path: string;
    has_edit_plan: boolean;
    slice_count: number;
  }

  // State for the parent clip directory + per-clip rows.
  let clipDir = '';
  let autoRemove = false;
  let loading = false;
  let loadError = '';
  let entries: ClipFolderEntry[] = [];
  // Per-row state keyed by folder path: editing notes + a "busy" flag so we
  // can show a running indicator on the row we're actively slicing.
  let notes: Record<string, string> = {};
  let busy: Record<string, boolean> = {};

  // Pick up the shared output dir so the Slice tab opens pointing at the
  // folder Extract just wrote to.
  outputDir.subscribe(v => {
    if (v && !clipDir) {
      clipDir = v;
      refresh();
    }
  });

  $: if (clipDir) {
    // Re-scan whenever the clipDir changes (e.g. user types/browses).
    refresh();
  }

  async function refresh() {
    if (!clipDir) {
      entries = [];
      loadError = '';
      return;
    }
    loading = true;
    loadError = '';
    try {
      const res = await apiFetch<ClipFolderEntry[]>(
        `/slices/clips?dir=${encodeURIComponent(clipDir)}`
      );
      entries = res;
      // Seed notes map for any new rows.
      for (const e of entries) {
        if (!(e.path in notes)) notes[e.path] = '';
      }
    } catch (e: any) {
      entries = [];
      loadError = e.message || String(e);
    } finally {
      loading = false;
    }
  }

  async function browseClipDir() {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog');
      const selected = await open({ multiple: false, directory: true });
      if (typeof selected === 'string' && selected) {
        clipDir = selected;
      }
    } catch (e: any) {
      addLog('error', `Folder picker failed: ${e.message || e}`);
    }
  }

  async function runSliceOne(entry: ClipFolderEntry) {
    const profile = $activeProfile;
    if (!profile) {
      addLog('error', 'No AI provider profile configured. Go to Settings tab.');
      return;
    }
    busy[entry.path] = true;
    busy = busy;

    resetProgress();
    pipelineRunning.set(true);
    addLog('info', `Slicing ${entry.folder_name}...`);

    try {
      await apiFetch('/pipeline/slices', {
        method: 'POST',
        body: JSON.stringify({
          clip_dir: entry.path,
          provider: profile.provider,
          model: profile.model || undefined,
          editing_notes: notes[entry.path] || undefined,
          premiere: false,
          davinci: false,
          auto_remove: autoRemove,
        }),
      });
      // The SSE PipelineDone handler flips pipelineRunning back to false.
      // Only auto-remove the row if the user checked the auto-remove option;
      // otherwise refresh badges and leave the row in place.
      //
      // Declare unsub up front (with a no-op placeholder) so the callback
      // can reference it even if svelte's store fires synchronously during
      // subscribe() — `const unsub = subscribe(cb => cb uses unsub)` trips
      // the temporal-dead-zone error otherwise.
      let unsub: () => void = () => {};
      unsub = pipelineRunning.subscribe(running => {
        if (!running && busy[entry.path]) {
          busy[entry.path] = false;
          busy = busy;
          if (autoRemove) {
            entries = entries.filter(e => e.path !== entry.path);
            delete notes[entry.path];
            delete busy[entry.path];
          } else {
            refreshMetadata();
          }
          // Defer so the subscribe() call has finished returning and
          // unsub has been assigned the real cleanup fn.
          queueMicrotask(() => unsub());
        }
      });
    } catch (e: any) {
      addLog('error', `Slice failed for ${entry.folder_name}: ${e.message}`);
      pipelineRunning.set(false);
      busy[entry.path] = false;
      busy = busy;
    }
  }

  async function writePremierePrompt(entry: ClipFolderEntry) {
    try {
      const res = await apiFetch<{ status: string; path: string; prompt: string }>(
        '/slices/premiere-prompt',
        {
          method: 'POST',
          body: JSON.stringify({ clip_dir: entry.path }),
        }
      );
      // Primary UX: copy to clipboard. Also written to disk as a backup.
      try {
        await navigator.clipboard.writeText(res.prompt);
        addLog('info', `Premiere prompt copied to clipboard (also saved to ${res.path})`);
      } catch {
        addLog('warn', `Clipboard copy failed — prompt saved to ${res.path}`);
      }
    } catch (e: any) {
      addLog('error', `Premiere prompt failed: ${e.message}`);
    }
  }

  async function refreshMetadata() {
    // Re-fetch the list and merge: update slice_count / has_edit_plan for
    // rows still visible, drop rows whose folders disappeared on disk, but
    // do NOT add rows that the user dismissed with the × button.
    if (!clipDir) return;
    try {
      const fresh = await apiFetch<ClipFolderEntry[]>(
        `/slices/clips?dir=${encodeURIComponent(clipDir)}`
      );
      const byPath = new Map(fresh.map(e => [e.path, e]));
      entries = entries
        .map(e => byPath.get(e.path) ?? e)
        .filter(e => byPath.has(e.path));
    } catch {
      // Silent — the row just stays with its old badges.
    }
  }

  function removeRow(entry: ClipFolderEntry) {
    // Manual dismiss — doesn't touch any files on disk, just hides the row.
    // Use when `Auto-remove after slicing` is off and you want to clear a
    // clip from the list yourself.
    entries = entries.filter(e => e.path !== entry.path);
    delete notes[entry.path];
    delete busy[entry.path];
  }

  async function cancelPipeline() {
    try {
      await apiFetch('/pipeline/cancel', { method: 'POST' });
      addLog('warn', 'Pipeline cancellation requested');
    } catch (e: any) {
      addLog('error', `Cancel failed: ${e.message}`);
    }
  }
</script>

<div class="tab-content">
  <!-- Header: clip directory picker -->
  <div class="card">
    <h4 class="card-title">Generate Slices from Clips</h4>
    <div class="path-row">
      <input
        type="text"
        bind:value={clipDir}
        placeholder="Path to clips folder (the one Extract wrote to)..."
        disabled={$pipelineRunning}
      />
      <button class="btn btn-small btn-secondary" on:click={browseClipDir} disabled={$pipelineRunning}>Browse</button>
      <button class="btn btn-small btn-secondary" on:click={refresh} disabled={$pipelineRunning || !clipDir}>Refresh</button>
    </div>
    {#if loadError}
      <div class="error-msg">{loadError}</div>
    {/if}
  </div>

  <!-- Per-clip list -->
  <div class="card">
    <div class="card-header">
      <h4 class="card-title">Clips</h4>
      <span class="clip-count">{entries.length} {entries.length === 1 ? 'clip' : 'clips'}</span>
    </div>

    {#if loading}
      <p class="dim-text">Loading…</p>
    {:else if entries.length === 0}
      <p class="dim-text">
        {clipDir
          ? 'No clip folders found. Run Extract first, or pick the folder containing extracted clips.'
          : 'Pick a clips folder to see what\'s inside.'}
      </p>
    {:else}
      {#each entries as entry (entry.path)}
        <div class="clip-row" class:busy={busy[entry.path]}>
          <div class="clip-row-header">
            <span class="clip-name">{entry.folder_name}</span>
            {#if entry.slice_count > 0}
              <span class="badge">{entry.slice_count} existing slice{entry.slice_count === 1 ? '' : 's'}</span>
            {/if}
            {#if entry.has_edit_plan}
              <span class="badge muted">edit plan present</span>
            {/if}
            <button
              class="remove-btn"
              title="Remove from list"
              aria-label="Remove from list"
              on:click={() => removeRow(entry)}
              disabled={$pipelineRunning || busy[entry.path]}
            >
              ×
            </button>
          </div>
          <textarea
            bind:value={notes[entry.path]}
            placeholder="Editing notes for this clip (optional)…"
            rows={2}
            disabled={$pipelineRunning}
          ></textarea>
          <div class="row-actions">
            <button
              class="btn btn-primary btn-small"
              on:click={() => runSliceOne(entry)}
              disabled={$pipelineRunning}
            >
              {busy[entry.path] ? 'Slicing…' : 'Slice'}
            </button>
            <button
              class="btn btn-secondary btn-small"
              on:click={() => writePremierePrompt(entry)}
              disabled={$pipelineRunning}
            >
              Premiere Prompt
            </button>
          </div>

          {#if busy[entry.path]}
            <div class="row-progress">
              {#if $currentStage === 'slices' && $sliceProgress.total > 0}
                <ProgressBar
                  label={`Slicing ${$sliceProgress.done}/${$sliceProgress.total}`}
                  value={$sliceProgress.done}
                  max={$sliceProgress.total}
                  showCount
                />
              {:else if $currentStage === 'visuals'}
                <ProgressBar
                  label={`Fetching visual aids ${$visualProgress.done}/${$visualProgress.total}`}
                  value={$visualProgress.done}
                  max={$visualProgress.total || 1}
                  showCount
                />
              {:else}
                <ProgressBar label="Generating edit plan…" value={0} indeterminate />
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    {/if}
  </div>

  <!-- Options footer -->
  <div class="card options-card">
    <label class="checkbox-label">
      <input type="checkbox" bind:checked={autoRemove} disabled={$pipelineRunning} />
      Auto-remove sections after slicing
    </label>
    {#if $pipelineRunning}
      <button class="btn btn-danger btn-small" on:click={cancelPipeline}>Cancel</button>
    {/if}
  </div>
</div>

<style>
  .tab-content {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .card-title {
    font-size: 13px;
    font-weight: 700;
    color: var(--text);
    margin: 0;
  }

  .dim-text {
    color: var(--dim);
    font-size: 13px;
    margin: 0;
  }

  .error-msg {
    color: var(--error);
    font-size: 12px;
  }

  .path-row {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  .path-row input {
    flex: 1;
  }

  .clip-count {
    color: var(--dim);
    font-size: 12px;
  }

  .clip-row {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--entry-bg);
    transition: opacity 0.2s;
  }

  .clip-row.busy {
    opacity: 0.65;
  }

  .clip-row-header {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .clip-name {
    flex: 1;
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
    word-break: break-all;
  }

  .badge {
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 3px;
    background: color-mix(in srgb, var(--success, #2ecc71) 20%, transparent);
    color: var(--text);
  }

  .badge.muted {
    background: color-mix(in srgb, var(--dim) 20%, transparent);
  }

  .remove-btn {
    background: transparent;
    border: none;
    color: var(--dim);
    font-size: 18px;
    line-height: 1;
    width: 22px;
    height: 22px;
    border-radius: 4px;
    cursor: pointer;
    padding: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s, color 0.15s;
  }

  .remove-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--error, #e53e3e) 20%, transparent);
    color: var(--error, #e53e3e);
  }

  .remove-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }

  .row-actions {
    display: flex;
    gap: 6px;
  }

  .row-progress {
    margin-top: 4px;
    padding-top: 6px;
    border-top: 1px solid var(--border);
  }

  .options-card {
    flex-direction: row;
    justify-content: space-between;
    align-items: center;
  }

  input[type="text"], textarea {
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--entry-bg);
    color: var(--text);
    font-size: 13px;
    outline: none;
    font-family: inherit;
    resize: vertical;
    width: 100%;
    box-sizing: border-box;
  }

  input:focus, textarea:focus {
    border-color: var(--accent);
  }

  input:disabled, textarea:disabled {
    opacity: 0.5;
  }

  .checkbox-label {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--text);
    cursor: pointer;
  }

  .checkbox-label input[type="checkbox"] {
    accent-color: var(--accent);
    width: 16px;
    height: 16px;
  }

  .btn {
    padding: 8px 14px;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }

  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-small {
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 500;
  }

  .btn-primary {
    background: var(--accent);
    color: white;
  }

  .btn-primary:hover:not(:disabled) {
    background: var(--accent2);
  }

  .btn-secondary {
    background: var(--card);
    color: var(--text);
    border: 1px solid var(--border);
  }

  .btn-secondary:hover:not(:disabled) {
    background: var(--entry-bg);
  }

  .btn-danger {
    background: var(--error);
    color: white;
  }

  .btn-danger:hover {
    opacity: 0.9;
  }
</style>
