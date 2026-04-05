<script lang="ts">
  import ProgressBar from '../components/ProgressBar.svelte';
  import { pipelineRunning, outputDir, activeProfile, addLog, resetProgress } from '../lib/stores';
  import { apiFetch } from '../lib/api';

  let clipDir = '';
  let editingNotes = '';
  let autoRemove = false;

  outputDir.subscribe(v => {
    if (v && !clipDir) clipDir = v;
  });

  function browseClipDir() {
    const input = document.createElement('input');
    input.type = 'file';
    input.setAttribute('webkitdirectory', '');
    input.onchange = () => {
      const file = input.files?.[0];
      if (file) {
        const path = (file as any).path || file.name;
        clipDir = path.replace(/[/\\][^/\\]+$/, '');
      }
    };
    input.click();
  }

  async function runSlice(mode: 'slice' | 'premiere' | 'davinci') {
    if (!clipDir) {
      addLog('error', 'No clip directory specified');
      return;
    }
    const profile = $activeProfile;
    if (!profile) {
      addLog('error', 'No AI provider profile configured. Go to Settings tab.');
      return;
    }

    resetProgress();
    pipelineRunning.set(true);

    const modeLabel = mode === 'slice' ? 'Slice' : mode === 'premiere' ? 'Premiere' : 'DaVinci';
    addLog('info', `${modeLabel}: generating from ${clipDir}`);

    try {
      await apiFetch('/pipeline/slices', {
        method: 'POST',
        body: JSON.stringify({
          clip_dir: clipDir,
          provider: profile.provider,
          model: profile.model || undefined,
          editing_notes: editingNotes || undefined,
          premiere: mode === 'premiere',
          davinci: mode === 'davinci',
          auto_remove: autoRemove,
        }),
      });
    } catch (e: any) {
      addLog('error', `${modeLabel} generation failed: ${e.message}`);
      pipelineRunning.set(false);
    }
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
  <!-- Header -->
  <div class="card">
    <h4 class="card-title">Generate Slices from Clip</h4>

    <!-- Clip Directory -->
    <div class="path-row">
      <input type="text" bind:value={clipDir} placeholder="Path to clip folder..." disabled={$pipelineRunning} />
      <button class="btn btn-small btn-secondary" on:click={browseClipDir} disabled={$pipelineRunning}>Browse</button>
    </div>
  </div>

  <!-- Editing Notes -->
  <div class="card">
    <span class="field-label">Editing Notes (optional)</span>
    <textarea
      bind:value={editingNotes}
      placeholder="Add custom editing instructions here (e.g., 'focus on funny moments', 'keep the energy high', 'include the part where they react to...')"
      rows={5}
      disabled={$pipelineRunning}
    ></textarea>
  </div>

  <!-- Action Buttons -->
  <div class="actions">
    {#if $pipelineRunning}
      <button class="btn btn-danger" on:click={cancelPipeline}>Cancel</button>
    {:else}
      <button class="btn btn-primary btn-large" on:click={() => runSlice('slice')} disabled={!clipDir}>
        Slice
      </button>
      <button class="btn btn-secondary" on:click={() => runSlice('premiere')} disabled={!clipDir}>
        Premiere
      </button>
      <button class="btn btn-secondary" on:click={() => runSlice('davinci')} disabled={!clipDir}>
        DaVinci
      </button>
    {/if}
  </div>

  <!-- Auto-remove checkbox -->
  <label class="checkbox-label">
    <input type="checkbox" bind:checked={autoRemove} disabled={$pipelineRunning} />
    Auto-remove sections after slicing
  </label>
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

  .card-title {
    font-size: 13px;
    font-weight: 700;
    color: var(--text);
    margin: 0;
  }

  .field-label {
    font-size: 12px;
    color: var(--dim);
  }

  .path-row {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  .path-row input {
    flex: 1;
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

  .actions {
    display: flex;
    gap: 8px;
  }

  .btn {
    padding: 10px 20px;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }

  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-large {
    padding: 10px 32px;
    flex: 1;
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

  .btn-small {
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 500;
  }

  .btn-danger {
    background: var(--error);
    color: white;
  }

  .btn-danger:hover {
    opacity: 0.9;
  }
</style>
