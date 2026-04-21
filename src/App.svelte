<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { licenseValid } from './lib/stores';

  import { activeTab as activeTabStore } from './lib/stores';
  let activeTab = $state(0);
  activeTabStore.subscribe(v => { activeTab = v; });
  const tabs = ['Transcribe', 'Extract', 'Slice', 'Settings', 'About'];
  let mounted = $state(false);
  let loadError = $state('');

  // Lazy-load components to catch import errors
  let LogPanel: any = $state(null);
  let LicenseGate: any = $state(null);
  let Transcribe: any = $state(null);
  let Extract: any = $state(null);
  let Slice: any = $state(null);
  let Settings: any = $state(null);
  let About: any = $state(null);

  let disconnectSSE: (() => void) | null = null;
  let statusPollHandle: ReturnType<typeof setInterval> | null = null;

  onMount(async () => {
    console.log('[TrikKlip] App mounting...');
    try {
      // Load components one by one to catch errors
      console.log('[TrikKlip] Loading LogPanel...');
      LogPanel = (await import('./components/LogPanel.svelte')).default;
      console.log('[TrikKlip] Loading LicenseGate...');
      LicenseGate = (await import('./components/LicenseGate.svelte')).default;
      console.log('[TrikKlip] Loading Transcribe...');
      Transcribe = (await import('./tabs/Transcribe.svelte')).default;
      console.log('[TrikKlip] Loading Extract...');
      Extract = (await import('./tabs/Extract.svelte')).default;
      console.log('[TrikKlip] Loading Slice...');
      Slice = (await import('./tabs/Slice.svelte')).default;
      console.log('[TrikKlip] Loading Settings...');
      Settings = (await import('./tabs/Settings.svelte')).default;
      console.log('[TrikKlip] Loading About...');
      About = (await import('./tabs/About.svelte')).default;
      console.log('[TrikKlip] All components loaded');
    } catch (e: any) {
      console.error('[TrikKlip] Component load error:', e);
      loadError = e.message || String(e);
    }

    try {
      const { connectProgress } = await import('./lib/sse');
      disconnectSSE = connectProgress();
      console.log('[TrikKlip] SSE connected');
    } catch (e: any) {
      console.error('[TrikKlip] SSE error:', e);
    }

    try {
      const { apiFetch } = await import('./lib/api');
      const { activeProfile } = await import('./lib/stores');
      const profiles = await apiFetch<Array<any>>('/profiles');
      const def = profiles.find(p => p.is_default);
      if (def) {
        activeProfile.set({
          provider: def.provider,
          model: def.model,
          api_key: def.api_key,
          base_url: def.base_url,
        });
        console.log('[TrikKlip] Default profile loaded:', def.name);
      }
    } catch (e: any) {
      console.error('[TrikKlip] Profile load error:', e);
    }

    // Safety-net status poll — reconciles client state with server if an SSE
    // PipelineDone/PipelineError event is lost or delayed.
    try {
      const { apiFetch } = await import('./lib/api');
      const { pipelineRunning, currentStage } = await import('./lib/stores');
      let running = false;
      pipelineRunning.subscribe(v => { running = v; });
      statusPollHandle = setInterval(async () => {
        if (!running) return;
        try {
          const status = await apiFetch<{ running: boolean }>('/pipeline/status');
          if (!status.running && running) {
            pipelineRunning.set(false);
            currentStage.set('');
          }
        } catch {}
      }, 2000);
    } catch (e: any) {
      console.error('[TrikKlip] Status poll setup error:', e);
    }

    mounted = true;
    console.log('[TrikKlip] Mount complete');
  });

  onDestroy(() => {
    disconnectSSE?.();
    if (statusPollHandle) clearInterval(statusPollHandle);
  });

  async function minimize() {
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      await getCurrentWindow().minimize();
    } catch {}
  }

  async function maximize() {
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      await getCurrentWindow().toggleMaximize();
    } catch {}
  }

  async function close() {
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      await getCurrentWindow().close();
    } catch {
      window.close();
    }
  }

  // Log panel resize
  let logHeight = $state(180);
  let resizing = $state(false);
  let startY = 0;
  let startHeight = 0;

  function onDividerDown(e: MouseEvent) {
    resizing = true;
    startY = e.clientY;
    startHeight = logHeight;
    e.preventDefault();
  }

  function onWindowMouseMove(e: MouseEvent) {
    if (!resizing) return;
    const delta = startY - e.clientY;
    logHeight = Math.max(60, Math.min(600, startHeight + delta));
  }

  function onWindowMouseUp() {
    resizing = false;
  }
</script>

<svelte:window onmousemove={onWindowMouseMove} onmouseup={onWindowMouseUp} />

{#if LicenseGate}
  <LicenseGate />
{/if}

<div class="app" class:resizing>
  <header class="titlebar" data-tauri-drag-region>
    <div class="title-block">
      <span class="title">Trik_Klip</span>
      <span class="title-sub">Trik_Klip</span>
    </div>
    <div class="controls">
      <button class="ctrl-btn" title="Minimize" onclick={minimize}>&#9472;</button>
      <button class="ctrl-btn" title="Maximize" onclick={maximize}>&#9633;</button>
      <button class="ctrl-btn close" title="Close" onclick={close}>&#10005;</button>
    </div>
  </header>

  <nav class="tabs">
    {#each tabs as tab, i}
      <button
        class="tab"
        class:active={activeTab === i}
        onclick={() => activeTabStore.set(i)}
      >
        {tab}
      </button>
    {/each}
  </nav>

  <main class="content">
    {#if loadError}
      <div class="placeholder" style="color: var(--error);">
        <h2>Load Error</h2>
        <pre>{loadError}</pre>
      </div>
    {:else if !mounted}
      <div class="placeholder">Loading...</div>
    {:else if activeTab === 0 && Transcribe}
      <Transcribe />
    {:else if activeTab === 1 && Extract}
      <Extract />
    {:else if activeTab === 2 && Slice}
      <Slice />
    {:else if activeTab === 3 && Settings}
      <Settings />
    {:else if activeTab === 4 && About}
      <About />
    {:else}
      <div class="placeholder">Loading tab...</div>
    {/if}
  </main>

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="log-divider" class:divider-active={resizing} onmousedown={onDividerDown}></div>

  <footer class="log-area" style="height: {logHeight}px;">
    {#if LogPanel}
      <LogPanel />
    {:else}
      <div class="log-placeholder">Loading log panel...</div>
    {/if}
  </footer>
</div>
