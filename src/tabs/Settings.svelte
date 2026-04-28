<script lang="ts">
  import { onMount } from 'svelte';
  import { activeProfile, language, addLog } from '../lib/stores';
  import { apiFetch } from '../lib/api';
  import type { ProviderProfile } from '../lib/types';

  interface ProviderEntry {
    key: string;
    label: string;
    default_model: string;
    models: string[];
    has_key: boolean;
  }

  let profiles: ProviderProfile[] = [];
  let providers: ProviderEntry[] = [];
  let models: string[] = [];
  let selectedProfileId = '';
  let loading = true;
  let showApiKey = false;
  let refreshingModels = false;
  let modelsError = '';

  // Profile connection test state
  let testing = false;
  let testResult: { success: boolean; message: string } | null = null;

  // Language
  let selectedLanguage = 'en';
  language.subscribe(v => { selectedLanguage = v; });

  const languageOptions: [string, string][] = [
    ['English (en)', 'en'],
    ['Spanish (es)', 'es'],
    ['French (fr)', 'fr'],
    ['German (de)', 'de'],
    ['Italian (it)', 'it'],
    ['Portuguese (pt)', 'pt'],
    ['Japanese (ja)', 'ja'],
    ['Korean (ko)', 'ko'],
    ['Chinese (zh)', 'zh'],
    ['Russian (ru)', 'ru'],
    ['Arabic (ar)', 'ar'],
    ['Hindi (hi)', 'hi'],
  ];

  // Edit form
  let editName = '';
  let editProvider = '';
  let editModel = '';
  let editApiKey = '';
  let editBaseUrl = '';
  let editIsDefault = false;
  let creating = false;

  // Env var hint per provider
  const envVarHints: Record<string, string> = {
    anthropic: 'ANTHROPIC_API_KEY',
    openai: 'OPENAI_API_KEY',
    gemini: 'GOOGLE_API_KEY',
    grok: 'XAI_API_KEY',
    ollama: '',
    claude_code: '',
  };

  onMount(async () => {
    await Promise.all([loadProfiles(), loadProviders()]);
    loading = false;
  });

  async function loadProfiles() {
    try {
      profiles = await apiFetch<ProviderProfile[]>('/profiles');
      const def = profiles.find(p => p.is_default);
      if (def) {
        selectProfile(def);
      }
    } catch (e: any) {
      addLog('error', `Failed to load profiles: ${e.message}`);
    }
  }

  async function loadProviders() {
    try {
      providers = await apiFetch<ProviderEntry[]>('/providers');
    } catch (e: any) {
      addLog('error', `Failed to load providers: ${e.message}`);
    }
  }

  /// Static defaults from /providers — always populated at tab load,
  /// independent of whether an API key is configured. Used as the dropdown
  /// source when the live /providers/<name>/models refresh fails (typically
  /// because the user hasn't saved a key yet for that provider).
  function defaultModelsFor(provider: string): string[] {
    const entry = providers.find(p => p.key === provider);
    return entry?.models ?? [];
  }

  async function loadModels(provider: string) {
    if (!provider) { models = []; modelsError = ''; return; }
    refreshingModels = true;
    modelsError = '';
    // Seed with the static defaults immediately so the dropdown is
    // never empty while the live request is in flight (or when it fails
    // because no API key is configured yet).
    models = defaultModelsFor(provider);
    try {
      const live = await apiFetch<string[]>(`/providers/${provider}/models`);
      if (Array.isArray(live) && live.length > 0) {
        models = live;
      }
    } catch (e: any) {
      // Keep the static defaults; surface the reason as a subtle hint.
      modelsError = e.message || 'Could not refresh models';
    } finally {
      refreshingModels = false;
    }
  }

  function selectProfile(p: ProviderProfile) {
    selectedProfileId = p.id;
    testResult = null;
    editName = p.name;
    editProvider = p.provider;
    editModel = p.model;
    editApiKey = p.api_key;
    editBaseUrl = p.base_url;
    editIsDefault = p.is_default;
    creating = false;
    showApiKey = false;
    loadModels(p.provider);
    activeProfile.set({
      provider: p.provider,
      model: p.model,
      api_key: p.api_key,
      base_url: p.base_url,
    });
  }

  function startCreate() {
    creating = true;
    selectedProfileId = '';
    editName = '';
    editProvider = providers[0]?.key || '';
    editModel = '';
    editApiKey = '';
    editBaseUrl = '';
    editIsDefault = profiles.length === 0;
    showApiKey = false;
    if (editProvider) loadModels(editProvider);
  }

  async function saveProfile() {
    const body = {
      name: editName,
      provider: editProvider,
      model: editModel,
      api_key: editApiKey,
      base_url: editBaseUrl,
      is_default: editIsDefault,
    };

    try {
      if (creating) {
        await apiFetch('/profiles', {
          method: 'POST',
          body: JSON.stringify(body),
        });
        addLog('info', `Created profile "${editName}"`);
      } else {
        await apiFetch(`/profiles/${selectedProfileId}`, {
          method: 'PUT',
          body: JSON.stringify(body),
        });
        addLog('info', `Updated profile "${editName}"`);
      }
      await loadProfiles();
      creating = false;
    } catch (e: any) {
      addLog('error', `Save failed: ${e.message}`);
    }
  }

  async function testProfile() {
    if (!editProvider) {
      testResult = { success: false, message: 'Select a provider first' };
      return;
    }
    testing = true;
    testResult = null;
    try {
      const body = {
        provider: editProvider,
        model: editModel,
        api_key: editApiKey,
        base_url: editBaseUrl,
      };
      const res = await apiFetch<{
        success: boolean;
        provider?: string;
        model?: string;
        response?: string;
        error?: string;
      }>('/providers/test', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      if (res.success) {
        const preview = (res.response || '').trim().slice(0, 120);
        testResult = {
          success: true,
          message: preview
            ? `OK — ${res.provider}/${res.model} replied: "${preview}"`
            : `OK — ${res.provider}/${res.model} responded`,
        };
      } else {
        testResult = { success: false, message: res.error || 'Unknown error' };
      }
    } catch (e: any) {
      testResult = { success: false, message: e.message || String(e) };
    } finally {
      testing = false;
    }
  }

  async function deleteProfile() {
    if (!selectedProfileId) return;
    try {
      await apiFetch(`/profiles/${selectedProfileId}`, { method: 'DELETE' });
      addLog('info', `Deleted profile "${editName}"`);
      selectedProfileId = '';
      editName = '';
      creating = false;
      await loadProfiles();
    } catch (e: any) {
      addLog('error', `Delete failed: ${e.message}`);
    }
  }

  function handleProviderChange() {
    loadModels(editProvider);
    editModel = '';
    testResult = null;
  }

  function providerLabel(p: string): string {
    const labels: Record<string, string> = {
      anthropic: 'Anthropic (Claude)',
      openai: 'OpenAI',
      gemini: 'Google (Gemini)',
      grok: 'Grok (xAI)',
      ollama: 'Ollama (Local)',
      claude_code: 'Claude Code',
    };
    return labels[p] || p;
  }

  // ── Premiere settings ──────────────────────────────────────────────────
  interface BannerEntry {
    label: string;
    path: string;
    position: [number, number] | null;
  }
  interface TrackPosition {
    label: string;
    track_index: number;
    x: number;
    y: number;
  }
  interface PremiereConfig {
    banners: BannerEntry[];
    positions: TrackPosition[];
  }

  let premiereOpen = false;
  let premiereConfig: PremiereConfig = { banners: [], positions: [] };
  let premiereLoaded = false;
  let premiereSaveTimer: ReturnType<typeof setTimeout> | null = null;

  onMount(async () => {
    try {
      premiereConfig = await apiFetch<PremiereConfig>('/settings/premiere');
      premiereLoaded = true;
    } catch (e: any) {
      addLog('error', `Failed to load premiere settings: ${e.message}`);
    }
  });

  function schedulePremiereSave() {
    if (!premiereLoaded) return;
    if (premiereSaveTimer) clearTimeout(premiereSaveTimer);
    premiereSaveTimer = setTimeout(savePremiereConfig, 400);
  }

  async function savePremiereConfig() {
    try {
      await apiFetch('/settings/premiere', {
        method: 'PUT',
        body: JSON.stringify(premiereConfig),
      });
    } catch (e: any) {
      addLog('error', `Save premiere settings failed: ${e.message}`);
    }
  }

  async function browseBannerPath(idx: number) {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog');
      const selected = await open({
        multiple: false,
        directory: false,
        filters: [{ name: 'Image', extensions: ['png', 'jpg', 'jpeg', 'webp'] }],
      });
      if (typeof selected === 'string' && selected) {
        premiereConfig.banners[idx].path = selected;
        premiereConfig = premiereConfig;
        schedulePremiereSave();
      }
    } catch (e: any) {
      addLog('error', `File picker failed: ${e.message || e}`);
    }
  }

  function addBanner() {
    premiereConfig.banners = [
      ...premiereConfig.banners,
      { label: 'Custom banner', path: '', position: null },
    ];
    schedulePremiereSave();
  }

  function toggleBannerPosition(idx: number, enabled: boolean) {
    premiereConfig.banners[idx].position = enabled ? [0, 0] : null;
    premiereConfig = premiereConfig;
    schedulePremiereSave();
  }

  function updateBannerPosition(idx: number, axis: 0 | 1, value: number) {
    const pos = premiereConfig.banners[idx].position;
    if (pos) {
      pos[axis] = value;
      premiereConfig = premiereConfig;
      schedulePremiereSave();
    }
  }

  function removeBanner(idx: number) {
    premiereConfig.banners = premiereConfig.banners.filter((_, i) => i !== idx);
    schedulePremiereSave();
  }

  function addPosition() {
    const nextTrack = premiereConfig.positions.length > 0
      ? Math.max(...premiereConfig.positions.map(p => p.track_index)) + 1
      : 0;
    premiereConfig.positions = [
      ...premiereConfig.positions,
      { label: 'New override', track_index: nextTrack, x: 0, y: 0 },
    ];
    schedulePremiereSave();
  }

  function removePosition(idx: number) {
    premiereConfig.positions = premiereConfig.positions.filter((_, i) => i !== idx);
    schedulePremiereSave();
  }

  function handleBannerDrop(idx: number, e: DragEvent) {
    e.preventDefault();
    // Tauri's webview drag-drop goes through window events (DropZone uses
    // them for the mp4), but the native HTML drop also fires with a files
    // list in the DataTransfer. In Tauri 2 the File objects don't expose a
    // path — fall back to the built-in drag-drop event via the Tauri window
    // listener. For a simpler UX here, just open the native picker if a
    // file is dropped.
    const items = e.dataTransfer?.files;
    if (items && items.length > 0) {
      const f: any = items[0];
      if (f.path) {
        premiereConfig.banners[idx].path = f.path;
        premiereConfig = premiereConfig;
        schedulePremiereSave();
      } else {
        // No path available — nudge the user to use Browse instead.
        addLog('warn', 'Drag-drop gave no file path — use Browse instead.');
      }
    }
  }
</script>

<div class="tab-content">
  <!-- Transcription Language Card -->
  <div class="card">
    <h4 class="card-title">Transcription Language</h4>
    <div class="lang-row">
      <select
        bind:value={selectedLanguage}
        on:change={() => language.set(selectedLanguage)}
      >
        {#each languageOptions as [label, code]}
          <option value={code}>{label}</option>
        {/each}
      </select>
      <span class="lang-code">{selectedLanguage}</span>
    </div>
  </div>

  <!-- Active Model Profile Card -->
  <div class="card">
    <h4 class="card-title">Active Model Profile</h4>
    <div class="active-profile-row">
      <select bind:value={selectedProfileId} on:change={() => {
        const p = profiles.find(pr => pr.id === selectedProfileId);
        if (p) {
          selectProfile(p);
          addLog('info', `Applied profile "${p.name}"`);
        }
      }}>
        <option value="">Select profile...</option>
        {#each profiles as profile}
          <option value={profile.id}>{profile.name} ({providerLabel(profile.provider)})</option>
        {/each}
      </select>
    </div>
  </div>

  <!-- Profile Editor Card -->
  <div class="card">
    <div class="card-header">
      <h4 class="card-title">Profile Editor</h4>
      {#if !creating}
        <button class="btn btn-small btn-secondary" on:click={startCreate}>+ New</button>
      {/if}
    </div>

    {#if loading}
      <p class="dim-text">Loading...</p>
    {:else if selectedProfileId || creating}
      <div class="form-row-inline">
        <span class="row-label">Name</span>
        <input type="text" bind:value={editName} placeholder="Profile name" />
      </div>

      <div class="form-row-inline">
        <span class="row-label">Provider</span>
        <select bind:value={editProvider} on:change={handleProviderChange}>
          <option value="">Select provider...</option>
          {#each providers as prov}
            <option value={prov.key}>{prov.label || providerLabel(prov.key)}</option>
          {/each}
        </select>
      </div>

      <div class="form-row-inline">
        <span class="row-label">API Key</span>
        <input
          type={showApiKey ? 'text' : 'password'}
          bind:value={editApiKey}
          placeholder="Enter API key"
        />
        <button class="btn btn-small btn-secondary" on:click={() => showApiKey = !showApiKey}>
          {showApiKey ? 'Hide' : 'Show'}
        </button>
      </div>
      {#if editProvider && envVarHints[editProvider]}
        <span class="env-hint">Set via env var: {envVarHints[editProvider]}</span>
      {/if}

      <div class="form-row-inline">
        <span class="row-label">Model</span>
        <input
          type="text"
          bind:value={editModel}
          list="model-suggestions"
          placeholder="Leave empty for default, or type a model name"
        />
        <datalist id="model-suggestions">
          {#each models as m}
            <option value={m}></option>
          {/each}
        </datalist>
        <button
          class="btn btn-small btn-secondary"
          on:click={() => loadModels(editProvider)}
          disabled={refreshingModels || !editProvider}
        >
          {refreshingModels ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>
      {#if modelsError && models.length === 0}
        <span class="env-hint" style="color: var(--error);">{modelsError}</span>
      {:else if modelsError}
        <span class="env-hint" style="color: var(--dim);">Showing defaults — live refresh failed: {modelsError}</span>
      {:else if models.length > 0}
        <span class="env-hint">{models.length} known model{models.length === 1 ? '' : 's'} — type to filter or enter a custom name</span>
      {/if}

      <div class="form-actions">
        <button class="btn btn-primary btn-small" on:click={saveProfile} disabled={!editName || !editProvider}>
          {creating ? 'Save Profile' : 'Save Profile'}
        </button>
        <button class="btn btn-secondary btn-small" on:click={testProfile} disabled={!editProvider || testing}>
          {testing ? 'Testing...' : 'Test'}
        </button>
        {#if !creating}
          <button class="btn btn-danger btn-small" on:click={deleteProfile}>Delete Profile</button>
        {/if}
      </div>

      {#if testResult}
        <div class="test-result" class:ok={testResult.success} class:fail={!testResult.success}>
          {testResult.success ? '✓' : '✗'} {testResult.message}
        </div>
      {/if}
    {:else}
      <p class="dim-text">Select a profile above or create a new one.</p>
    {/if}
  </div>

  <!-- Premiere Prompt Settings Card (collapsible) -->
  <div class="card">
    <button
      class="collapse-header"
      type="button"
      on:click={() => (premiereOpen = !premiereOpen)}
      aria-expanded={premiereOpen}
    >
      <span class="chev">{premiereOpen ? '▼' : '▶'}</span>
      <h4 class="card-title">Premiere Prompt Settings</h4>
    </button>

    {#if premiereOpen}
      <div class="premiere-body">
        <p class="dim-text">
          Customize what goes into the Premiere setup prompt so it matches
          your machine instead of hard-coded paths.
        </p>

        <!-- Banners -->
        <div class="sub-section">
          <div class="sub-header">
            <span class="sub-title">Mandatory banner imports</span>
            <button class="btn btn-small btn-secondary" on:click={addBanner}>+ Add banner</button>
          </div>
          <p class="hint-text">
            These are imported for every clip and placed on the timeline
            after the visual aids. Order determines track index (first → Video 5, second → Video 6, …).
          </p>
          {#each premiereConfig.banners as banner, i}
            <div
              class="banner-row"
              on:dragover|preventDefault
              on:drop={(e) => handleBannerDrop(i, e)}
              role="region"
              aria-label="Banner {i + 1}"
            >
              <input
                type="text"
                class="banner-label"
                bind:value={banner.label}
                placeholder="Label (e.g. Twitch banner)"
                on:input={schedulePremiereSave}
              />
              <input
                type="text"
                class="banner-path"
                bind:value={banner.path}
                placeholder="Drop image here or click Browse"
                on:input={schedulePremiereSave}
              />
              <button class="btn btn-small btn-secondary" on:click={() => browseBannerPath(i)}>Browse</button>
              <button class="btn-remove" title="Remove" on:click={() => removeBanner(i)}>×</button>
            </div>
            <div class="banner-pos-row">
              <label class="checkbox-inline">
                <input
                  type="checkbox"
                  checked={banner.position !== null}
                  on:change={(e) => toggleBannerPosition(i, (e.target as HTMLInputElement).checked)}
                />
                Position reminder
              </label>
              {#if banner.position}
                <input
                  type="number"
                  class="pos-xy"
                  value={banner.position[0]}
                  on:input={(e) => updateBannerPosition(i, 0, parseFloat((e.target as HTMLInputElement).value) || 0)}
                  placeholder="x"
                  title="x position"
                />
                <input
                  type="number"
                  class="pos-xy"
                  value={banner.position[1]}
                  on:input={(e) => updateBannerPosition(i, 1, parseFloat((e.target as HTMLInputElement).value) || 0)}
                  placeholder="y"
                  title="y position"
                />
              {:else}
                <span class="hint-text">(will say "position as needed" in the prompt)</span>
              {/if}
            </div>
          {/each}
          {#if premiereConfig.banners.length === 0}
            <p class="dim-text">No banners configured. Click "+ Add banner" to add one.</p>
          {/if}
        </div>

        <!-- Position overrides -->
        <div class="sub-section">
          <div class="sub-header">
            <span class="sub-title">Manual position overrides</span>
            <button class="btn btn-small btn-secondary" on:click={addPosition}>+ Add position</button>
          </div>
          <p class="hint-text">
            These appear at the end of the prompt as reminders to set
            manually in Effect Controls (documented Adobe UXP API
            limitation — position cannot be set via the official connector).
          </p>
          {#each premiereConfig.positions as pos, i}
            <div class="pos-row">
              <input
                type="number"
                class="pos-track"
                bind:value={pos.track_index}
                on:input={schedulePremiereSave}
                min={0}
                title="Video track index"
              />
              <input
                type="text"
                class="pos-label"
                bind:value={pos.label}
                placeholder="Label (e.g. Main clip (scale 198))"
                on:input={schedulePremiereSave}
              />
              <input
                type="number"
                class="pos-xy"
                bind:value={pos.x}
                on:input={schedulePremiereSave}
                placeholder="x"
                title="x position"
              />
              <input
                type="number"
                class="pos-xy"
                bind:value={pos.y}
                on:input={schedulePremiereSave}
                placeholder="y"
                title="y position"
              />
              <button class="btn-remove" title="Remove" on:click={() => removePosition(i)}>×</button>
            </div>
          {/each}
          {#if premiereConfig.positions.length === 0}
            <p class="dim-text">No position overrides.</p>
          {/if}
        </div>
      </div>
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

  .dim-text {
    color: var(--dim);
    font-size: 13px;
    margin: 0;
  }

  /* Language row */
  .lang-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .lang-row select {
    flex: 1;
  }

  .lang-code {
    color: var(--dim);
    font-size: 13px;
    font-family: "Cascadia Code", "Consolas", monospace;
  }

  /* Active profile row */
  .active-profile-row {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  .active-profile-row select {
    flex: 1;
  }

  /* Form rows */
  .form-row-inline {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .row-label {
    font-size: 12px;
    color: var(--dim);
    min-width: 60px;
    white-space: nowrap;
  }

  .form-row-inline input,
  .form-row-inline select {
    flex: 1;
  }

  .env-hint {
    font-size: 11px;
    color: var(--accent);
    margin-top: -4px;
    padding-left: 68px;
  }

  /* Inputs */
  select, input[type="text"], input[type="password"], input[type="number"] {
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--entry-bg);
    color: var(--text);
    font-size: 13px;
    outline: none;
  }

  select:focus, input:focus {
    border-color: var(--accent);
  }

  /* Actions */
  .form-actions {
    display: flex;
    gap: 8px;
    margin-top: 4px;
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

  .btn-danger {
    background: var(--error);
    color: white;
  }

  .btn-danger:hover {
    opacity: 0.9;
  }

  .btn-small {
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 500;
  }

  .test-result {
    margin-top: 6px;
    padding: 8px 12px;
    border-radius: 6px;
    font-size: 12px;
    line-height: 1.4;
    word-break: break-word;
  }

  .test-result.ok {
    background: color-mix(in srgb, var(--success, #2ecc71) 15%, transparent);
    border: 1px solid var(--success, #2ecc71);
    color: var(--text);
  }

  .test-result.fail {
    background: color-mix(in srgb, var(--error, #e53e3e) 15%, transparent);
    border: 1px solid var(--error, #e53e3e);
    color: var(--text);
  }

  /* ── Premiere settings ─────────────────────────────────────────────── */

  .collapse-header {
    display: flex;
    align-items: center;
    gap: 8px;
    background: transparent;
    border: none;
    color: var(--text);
    cursor: pointer;
    padding: 0;
    text-align: left;
    width: 100%;
  }

  .collapse-header:focus {
    outline: none;
  }

  .chev {
    color: var(--dim);
    font-size: 11px;
    width: 14px;
    text-align: center;
  }

  .premiere-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin-top: 6px;
  }

  .sub-section {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--entry-bg);
  }

  .sub-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .sub-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--text);
  }

  .hint-text {
    font-size: 11px;
    color: var(--dim);
    margin: 0;
    line-height: 1.4;
  }

  .banner-row {
    display: flex;
    gap: 6px;
    align-items: center;
  }

  .banner-pos-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-left: 148px; /* align under the path input */
    margin-bottom: 4px;
  }

  /* Explicit dark theme for inputs inside the Premiere settings body —
     browser defaults for type="number" and some shadow-DOM quirks otherwise
     render them white. */
  .premiere-body input[type="text"],
  .premiere-body input[type="number"] {
    background: var(--entry-bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 13px;
    outline: none;
    font-family: inherit;
  }

  .premiere-body input[type="text"]:focus,
  .premiere-body input[type="number"]:focus {
    border-color: var(--accent);
  }

  /* Hide the browser's default number spinner buttons — they look native
     and don't match the theme. */
  .premiere-body input[type="number"]::-webkit-inner-spin-button,
  .premiere-body input[type="number"]::-webkit-outer-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }

  .premiere-body input[type="number"] {
    -moz-appearance: textfield;
  }

  .checkbox-inline {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: var(--dim);
    cursor: pointer;
    white-space: nowrap;
  }

  .checkbox-inline input[type="checkbox"] {
    accent-color: var(--accent);
    width: 13px;
    height: 13px;
  }

  .banner-label {
    flex: 0 0 140px;
  }

  .banner-path {
    flex: 1;
    min-width: 0;
  }

  .pos-row {
    display: flex;
    gap: 6px;
    align-items: center;
  }

  .pos-track {
    width: 64px;
    flex: 0 0 auto;
    text-align: center;
  }

  .pos-label {
    flex: 1;
    min-width: 0;
  }

  .pos-xy {
    width: 88px;
    flex: 0 0 auto;
    text-align: right;
  }

  .btn-remove {
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

  .btn-remove:hover {
    background: color-mix(in srgb, var(--error, #e53e3e) 20%, transparent);
    color: var(--error, #e53e3e);
  }
</style>
