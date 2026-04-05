<script lang="ts">
  import ProgressBar from '../components/ProgressBar.svelte';
  import ClipCard from '../components/ClipCard.svelte';
  import {
    mp4Path, outputDir, clips, pipelineRunning, currentStage,
    extractionProgress,
    addLog, resetProgress,
  } from '../lib/stores';
  import { apiFetch } from '../lib/api';

  let selectedClips = new Set<number>();
  let outDir = './clips';

  // Select all clips by default when clips update
  clips.subscribe(c => {
    selectedClips = new Set(c.map(cl => cl.rank));
  });

  function toggleClip(rank: number) {
    if (selectedClips.has(rank)) {
      selectedClips.delete(rank);
    } else {
      selectedClips.add(rank);
    }
    selectedClips = selectedClips;
  }

  function selectAll() {
    selectedClips = new Set($clips.map(c => c.rank));
  }

  function deselectAll() {
    selectedClips = new Set();
  }

  function browseOutputDir() {
    const input = document.createElement('input');
    input.type = 'file';
    input.setAttribute('webkitdirectory', '');
    input.onchange = () => {
      const file = input.files?.[0];
      if (file) {
        // Get directory path from file
        const path = (file as any).path || file.name;
        outDir = path.replace(/[/\\][^/\\]+$/, '');
      }
    };
    input.click();
  }

  async function extractSelected() {
    const selected = $clips.filter(c => selectedClips.has(c.rank));
    if (selected.length === 0) {
      addLog('error', 'No clips selected');
      return;
    }
    if (!$mp4Path) {
      addLog('error', 'No source file');
      return;
    }

    resetProgress();
    pipelineRunning.set(true);
    addLog('info', `Extracting ${selected.length} clips`);

    try {
      await apiFetch('/pipeline/extract', {
        method: 'POST',
        body: JSON.stringify({
          mp4_path: $mp4Path,
          clips: selected,
          output_dir: $outputDir || outDir || undefined,
        }),
      });
    } catch (e: any) {
      addLog('error', `Extraction failed: ${e.message}`);
      pipelineRunning.set(false);
    }
  }
</script>

<div class="tab-content">
  <!-- Clip Selection Header -->
  <div class="card">
    <div class="clip-header-row">
      <h4 class="card-title">Clip Selection</h4>
      <span class="clip-count">{$clips.length} clips</span>
      <button class="btn btn-small btn-secondary" on:click={selectAll} disabled={$clips.length === 0}>Select All</button>
      <button class="btn btn-small btn-secondary" on:click={deselectAll} disabled={$clips.length === 0}>Deselect All</button>
    </div>

    <!-- Clip List -->
    <div class="clips-list">
      {#if $clips.length === 0}
        <div class="empty-state">No clips yet. Run the pipeline from the Transcribe tab.</div>
      {:else}
        {#each $clips as clip}
          <ClipCard {clip} selected={selectedClips.has(clip.rank)} onToggle={toggleClip} />
        {/each}
      {/if}
    </div>
  </div>

  <!-- Progress -->
  {#if $pipelineRunning && $currentStage === 'extraction'}
    <div class="progress-section">
      <ProgressBar
        label={`Extracting: ${$extractionProgress.clip_name}`}
        value={$extractionProgress.done}
        max={$extractionProgress.total}
        showCount
      />
    </div>
  {/if}

  <!-- Output Dir -->
  <div class="card">
    <div class="path-row">
      <span class="path-label">Output Dir</span>
      <input type="text" bind:value={outDir} placeholder="./clips" disabled={$pipelineRunning} />
      <button class="btn btn-small btn-secondary" on:click={browseOutputDir} disabled={$pipelineRunning}>Browse</button>
    </div>
  </div>

  <!-- Extract Button -->
  <div class="actions">
    <button
      class="btn btn-primary"
      on:click={extractSelected}
      disabled={$pipelineRunning || selectedClips.size === 0}
    >
      Extract Selected Clips
    </button>
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

  .card-title {
    font-size: 13px;
    font-weight: 700;
    color: var(--text);
    margin: 0;
  }

  .clip-header-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .clip-count {
    flex: 1;
    text-align: right;
    font-size: 12px;
    color: var(--dim);
  }

  .clips-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-height: 400px;
    overflow-y: auto;
  }

  .empty-state {
    color: var(--dim);
    font-size: 13px;
    text-align: center;
    padding: 32px 0;
  }

  .path-row {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  .path-label {
    font-size: 12px;
    color: var(--dim);
    white-space: nowrap;
    min-width: 70px;
  }

  .path-row input {
    flex: 1;
  }

  input[type="text"] {
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--entry-bg);
    color: var(--text);
    font-size: 13px;
    outline: none;
  }

  input:focus {
    border-color: var(--accent);
  }

  input:disabled {
    opacity: 0.5;
  }

  .progress-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .actions {
    display: flex;
    justify-content: center;
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
</style>
