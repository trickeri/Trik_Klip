<script lang="ts">
  import DropZone from '../components/DropZone.svelte';
  import ProgressBar from '../components/ProgressBar.svelte';
  import {
    mp4Path, outputDir, pipelineRunning, currentStage, language,
    hashProgress, audioProgress, transcriptionProgress, transcriptionLabel,
    analysisProgress, whisperDownloadProgress, audioTrack,
    addLog, resetProgress, activeProfile,
  } from '../lib/stores';

  function defaultBaseDir(path: string): string {
    // Everything for a given video goes under <mp4_parent>/Clips/<stem>/.
    const dir = path.replace(/[/\\][^/\\]+$/, '');
    const stem = path.replace(/^.*[/\\]/, '').replace(/\.[^.]+$/, '');
    return `${dir}/Clips/${stem}`;
  }
  import { apiFetch } from '../lib/api';

  // Default to 'small' (Python default). Persist the user's last choice so
  // they don't re-pick it every session.
  const WHISPER_MODEL_LS_KEY = 'trikklip.whisperModel';
  let whisperModel =
    (typeof localStorage !== 'undefined' && localStorage.getItem(WHISPER_MODEL_LS_KEY)) ||
    'small';
  $: if (typeof localStorage !== 'undefined' && whisperModel) {
    localStorage.setItem(WHISPER_MODEL_LS_KEY, whisperModel);
  }
  let maxClips = 10;
  let windowMinutes = 5;
  let paddingMinutes = 3.0;
  let selectedLanguage = 'en';

  // Run mode: 0 = Full Pipeline, 1 = Transcribe Only, 2 = Analyze Only
  let runMode = 0;

  // Custom search prompts
  let customPrompts: string[] = [];

  // File paths
  let loadTranscriptPath = '';
  let saveTranscriptPath = '';
  let outputJsonPath = '';

  // When a transcript is loaded (Analyze Only), default the shared output dir
  // to <transcript_parent>/<stem>_clips — a sibling `_clips` folder next to
  // the transcript, matching the Python layout. stem is derived from the
  // transcript filename by stripping a trailing `_transcript`.
  $: if (loadTranscriptPath) {
    const parent = loadTranscriptPath.replace(/[/\\][^/\\]+$/, '');
    const base = loadTranscriptPath
      .replace(/^.*[/\\]/, '')
      .replace(/\.[^.]+$/, '');
    const stem = base.replace(/_transcript$/i, '');
    if (parent && stem) outputDir.set(`${parent}/${stem}_clips`);
  }

  // Whisper model catalog — matches AVAILABLE_MODELS in whisper_models.rs.
  // Missing models are auto-downloaded from HuggingFace on first use.
  const whisperModels: { value: string; label: string }[] = [
    { value: 'tiny', label: 'tiny (77 MB — fastest, lowest accuracy)' },
    { value: 'tiny.en', label: 'tiny.en (77 MB — English-only, faster)' },
    { value: 'base', label: 'base (147 MB — default, shipped with app)' },
    { value: 'base.en', label: 'base.en (147 MB — English-only)' },
    { value: 'small', label: 'small (488 MB — better at names/terms)' },
    { value: 'small.en', label: 'small.en (488 MB — English-only sweet spot)' },
    { value: 'medium', label: 'medium (1.5 GB — diminishing returns vs small)' },
    { value: 'medium.en', label: 'medium.en (1.5 GB — English-only)' },
    { value: 'large-v3', label: 'large-v3 (3 GB — highest accuracy, slowest)' },
    { value: 'large-v3-turbo', label: 'large-v3-turbo (1.6 GB — near-large quality, 8× faster)' },
  ];

  function onFileSelect(path: string) {
    mp4Path.set(path);
    if (path) {
      const stem = path.replace(/^.*[/\\]/, '').replace(/\.[^.]+$/, '');
      const baseDir = defaultBaseDir(path);
      // Always overwrite — a new file means the previous auto-filled paths
      // are wrong. Users who want a custom path can edit after selecting.
      saveTranscriptPath = `${baseDir}/${stem}_transcript.json`;
      outputJsonPath = `${baseDir}/${stem}_clips.json`;
      // Extract target is a nested <stem>_clips subfolder so per-clip
      // subfolders don't clutter the top-level <stem> folder. Matches the
      // Python layout.
      outputDir.set(`${baseDir}/${stem}_clips`);
    }
  }

  function addPrompt() {
    customPrompts = [...customPrompts, ''];
  }

  function removePrompt(index: number) {
    customPrompts = customPrompts.filter((_, i) => i !== index);
  }

  async function runPipeline() {
    // Validate based on mode
    if (runMode === 0 || runMode === 1) {
      if (!$mp4Path) {
        addLog('error', 'No video file selected');
        return;
      }
    }
    if (runMode === 2) {
      if (!loadTranscriptPath) {
        addLog('error', 'No transcript file specified for Analyze Only mode');
        return;
      }
    }
    if (runMode === 0 || runMode === 2) {
      if (!$activeProfile) {
        addLog('error', 'No AI provider configured — go to Settings first');
        return;
      }
    }

    resetProgress();
    pipelineRunning.set(true);

    const prompts = customPrompts.filter(p => p.trim() !== '');
    const track = $audioTrack === -1 ? undefined : $audioTrack;

    const body: Record<string, any> = {
      source_path: $mp4Path,
      whisper_model: whisperModel,
      language: selectedLanguage,
      audio_track: track,
      top_n: maxClips,
      window_minutes: windowMinutes,
      padding_seconds: paddingMinutes * 60,
      custom_prompts: prompts,
      output_dir: $mp4Path ? defaultBaseDir($mp4Path) : '',
      save_transcript_path: saveTranscriptPath || undefined,
      output_json_path: outputJsonPath || undefined,
    };

    // Add provider info for modes that need analysis
    if ($activeProfile && (runMode === 0 || runMode === 2)) {
      body.provider = $activeProfile.provider;
      body.model = $activeProfile.model;
      body.api_key = $activeProfile.api_key;
      body.base_url = $activeProfile.base_url;
    }

    // Analyze Only: point the backend at the transcript file the user picked.
    // It can load a Python-generated transcript JSON directly; no DB cache hit
    // required.
    if (runMode === 2 && loadTranscriptPath) {
      body.transcript_path = loadTranscriptPath;
      // If the user didn't provide an mp4, derive output_dir from the
      // transcript's folder so extracted clips have somewhere to go later.
      if (!$mp4Path) {
        body.output_dir = loadTranscriptPath.replace(/[/\\][^/\\]+$/, '');
      }
    }

    // Determine endpoint
    let endpoint = '/pipeline/run';
    if (runMode === 1) endpoint = '/pipeline/transcribe';
    if (runMode === 2) endpoint = '/pipeline/analyze';

    const modeLabel = ['Full Pipeline', 'Transcribe Only', 'Analyze Only'][runMode];
    addLog('info', `Starting ${modeLabel}: ${$mp4Path || loadTranscriptPath}`);

    try {
      await apiFetch(endpoint, {
        method: 'POST',
        body: JSON.stringify(body),
      });
    } catch (e: any) {
      addLog('error', `Pipeline failed: ${e.message}`);
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

  async function browseTranscript() {
    // Use Tauri's dialog plugin — HTML <input type="file"> gives only the
    // filename in a webview, which the backend can't open.
    try {
      const { open } = await import('@tauri-apps/plugin-dialog');
      const selected = await open({
        multiple: false,
        directory: false,
        filters: [{ name: 'Transcript JSON', extensions: ['json'] }],
      });
      if (typeof selected === 'string' && selected) {
        loadTranscriptPath = selected;
      }
    } catch (e: any) {
      addLog('error', `File picker failed: ${e.message || e}`);
    }
  }

  language.subscribe(v => { selectedLanguage = v; });
</script>

<div class="tab-content">
  <!-- Drop Zone -->
  <DropZone filePath={$mp4Path} onSelect={onFileSelect} disabled={$pipelineRunning} />

  <!-- Options Card -->
  <div class="card">
    <h4 class="card-title">Options</h4>
    <div class="form-row five-col">
      <label class="form-label">
        Whisper Model
        <select bind:value={whisperModel} disabled={$pipelineRunning}>
          {#each whisperModels as m}
            <option value={m.value}>{m.label}</option>
          {/each}
        </select>
      </label>

      <label class="form-label">
        Max Clips
        <input type="number" bind:value={maxClips} min={1} max={50} disabled={$pipelineRunning} />
      </label>

      <label class="form-label">
        Window (min)
        <input type="number" bind:value={windowMinutes} min={1} max={30} disabled={$pipelineRunning} />
      </label>

      <label class="form-label">
        Padding (min)
        <input type="number" bind:value={paddingMinutes} min={0} max={10} step={0.5} disabled={$pipelineRunning} />
      </label>

      <label class="form-label">
        Audio Track
        <input type="number" bind:value={$audioTrack} min={-1} max={20} disabled={$pipelineRunning} />
        {#if $audioTrack === -1}
          <span class="field-hint">auto</span>
        {/if}
      </label>
    </div>
  </div>

  <!-- Custom Search Prompts Card -->
  <div class="card">
    <div class="card-header">
      <h4 class="card-title">Custom Search Prompts</h4>
      <button class="btn btn-small btn-secondary" on:click={addPrompt} disabled={$pipelineRunning}>+ Add</button>
    </div>
    <p class="hint">Tell the AI what specific things to look for (e.g., 'funny reactions', 'advice moments')</p>
    {#each customPrompts as prompt, i}
      <div class="prompt-row">
        <input
          type="text"
          bind:value={customPrompts[i]}
          placeholder="What to look for..."
          disabled={$pipelineRunning}
        />
        <button class="btn-remove" on:click={() => removePrompt(i)} disabled={$pipelineRunning}>x</button>
      </div>
    {/each}
  </div>

  <!-- File Paths Card -->
  <div class="card">
    <h4 class="card-title">File Paths</h4>

    {#if runMode === 2}
      <div class="path-row">
        <span class="path-label">Load Transcript</span>
        <input type="text" bind:value={loadTranscriptPath} placeholder="existing transcript JSON" disabled={$pipelineRunning} />
        <button class="btn btn-small btn-secondary" on:click={browseTranscript} disabled={$pipelineRunning}>Browse</button>
      </div>
    {:else}
      <div class="path-row">
        <span class="path-label">Save Transcript</span>
        <input type="text" bind:value={saveTranscriptPath} placeholder="(auto-filled from video)" disabled={$pipelineRunning} />
      </div>

      <div class="path-row">
        <span class="path-label">Output JSON</span>
        <input type="text" bind:value={outputJsonPath} placeholder="(auto-filled from video)" disabled={$pipelineRunning} />
      </div>
    {/if}
  </div>

  <!-- Run Mode Card -->
  <div class="card">
    <h4 class="card-title">Run Mode</h4>
    <div class="radio-group">
      <label class="radio-label">
        <input type="radio" bind:group={runMode} value={0} disabled={$pipelineRunning} />
        Full Pipeline
      </label>
      <label class="radio-label">
        <input type="radio" bind:group={runMode} value={1} disabled={$pipelineRunning} />
        Transcribe Only
      </label>
      <label class="radio-label">
        <input type="radio" bind:group={runMode} value={2} disabled={$pipelineRunning} />
        Analyze Only
      </label>
    </div>
  </div>

  <!-- Progress -->
  {#if $pipelineRunning}
    <div class="progress-section">
      {#if $currentStage === 'hashing'}
        <ProgressBar label="Hashing file" value={$hashProgress} />
      {:else if $currentStage === 'whisper_download'}
        <ProgressBar
          label={$whisperDownloadProgress.bytes_total > 0
            ? `Downloading whisper model (${$whisperDownloadProgress.model}) — ${(
                $whisperDownloadProgress.bytes_done /
                1024 /
                1024
              ).toFixed(0)} / ${(
                $whisperDownloadProgress.bytes_total /
                1024 /
                1024
              ).toFixed(0)} MB`
            : `Downloading whisper model (${$whisperDownloadProgress.model})…`}
          value={$whisperDownloadProgress.percent}
        />
      {:else if $currentStage === 'audio'}
        <ProgressBar label="Extracting audio" value={$audioProgress} />
      {:else if $currentStage === 'spikes'}
        <ProgressBar label="Detecting volume spikes" value={0} indeterminate />
      {:else if $currentStage === 'transcription'}
        <ProgressBar label={$transcriptionLabel || 'Transcribing'} value={$transcriptionProgress} />
      {:else if $currentStage === 'chunking'}
        <ProgressBar label="Chunking transcript" value={0} indeterminate />
      {:else if $currentStage === 'analysis'}
        <ProgressBar
          label={`Analyzing chunks (${$analysisProgress.done}/${$analysisProgress.total})`}
          value={$analysisProgress.total > 0 ? Math.round(($analysisProgress.done / $analysisProgress.total) * 100) : 0}
        />
      {/if}
    </div>
  {/if}

  <!-- Actions -->
  <div class="actions">
    {#if $pipelineRunning}
      <button class="btn btn-danger" on:click={cancelPipeline}>Cancel</button>
    {:else}
      <button class="btn btn-primary" on:click={runPipeline} disabled={runMode !== 2 && !$mp4Path}>
        Run
      </button>
    {/if}
  </div>
</div>

<style>
  .tab-content {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  /* Card sections */
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

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  /* Form row */
  .form-row {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
  }

  .five-col .form-label {
    min-width: 100px;
  }

  .form-label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 12px;
    color: var(--dim);
    flex: 1;
    position: relative;
  }

  .field-hint {
    position: absolute;
    right: 10px;
    bottom: 8px;
    font-size: 12px;
    color: var(--dim);
    pointer-events: none;
  }

  select, input[type="text"], input[type="number"] {
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--entry-bg);
    color: var(--text);
    font-size: 13px;
    outline: none;
    width: 100%;
    box-sizing: border-box;
  }

  select:focus, input:focus {
    border-color: var(--accent);
  }

  select:disabled, input:disabled {
    opacity: 0.5;
  }

  /* Hint text */
  .hint {
    color: var(--dim);
    font-size: 11px;
    margin: 0;
  }

  /* Custom prompt rows */
  .prompt-row {
    display: flex;
    gap: 6px;
    align-items: center;
  }

  .prompt-row input {
    flex: 1;
  }

  .btn-remove {
    width: 24px;
    height: 24px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--dim);
    font-size: 14px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .btn-remove:hover {
    background: var(--error);
    color: white;
  }

  .btn-remove:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  /* File paths */
  .path-row {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  .path-label {
    font-size: 12px;
    color: var(--dim);
    white-space: nowrap;
    min-width: 100px;
  }

  .path-row input {
    flex: 1;
  }

  /* Radio group */
  .radio-group {
    display: flex;
    gap: 16px;
  }

  .radio-label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--text);
    cursor: pointer;
  }

  .radio-label input[type="radio"] {
    width: auto;
    accent-color: var(--accent);
    cursor: pointer;
  }

  /* Progress */
  .progress-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* Actions */
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

  .btn-primary {
    background: var(--accent);
    color: white;
  }

  .btn-primary:hover:not(:disabled) {
    background: var(--accent2);
  }

  .btn-danger {
    background: var(--error);
    color: white;
  }

  .btn-danger:hover {
    opacity: 0.9;
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
