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

  async function loadModels(provider: string) {
    if (!provider) { models = []; modelsError = ''; return; }
    refreshingModels = true;
    modelsError = '';
    try {
      models = await apiFetch<string[]>(`/providers/${provider}/models`);
    } catch (e: any) {
      models = [];
      modelsError = e.message || 'Could not load models';
    } finally {
      refreshingModels = false;
    }
  }

  function selectProfile(p: ProviderProfile) {
    selectedProfileId = p.id;
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

  function applyProfile() {
    const p = profiles.find(pr => pr.id === selectedProfileId);
    if (p) {
      activeProfile.set({
        provider: p.provider,
        model: p.model,
        api_key: p.api_key,
        base_url: p.base_url,
      });
      addLog('info', `Applied profile "${p.name}"`);
    }
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
        if (p) selectProfile(p);
      }}>
        <option value="">Select profile...</option>
        {#each profiles as profile}
          <option value={profile.id}>{profile.name} ({providerLabel(profile.provider)})</option>
        {/each}
      </select>
      <button class="btn btn-small btn-secondary" on:click={applyProfile} disabled={!selectedProfileId}>Apply</button>
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
      {#if modelsError}
        <span class="env-hint" style="color: var(--error);">{modelsError}</span>
      {:else if models.length > 0}
        <span class="env-hint">{models.length} known model{models.length === 1 ? '' : 's'} — type to filter or enter a custom name</span>
      {/if}

      <div class="form-actions">
        <button class="btn btn-primary btn-small" on:click={saveProfile} disabled={!editName || !editProvider}>
          {creating ? 'Save Profile' : 'Save Profile'}
        </button>
        {#if !creating}
          <button class="btn btn-danger btn-small" on:click={deleteProfile}>Delete Profile</button>
        {/if}
      </div>
    {:else}
      <p class="dim-text">Select a profile above or create a new one.</p>
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
  select, input[type="text"], input[type="password"] {
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
</style>
