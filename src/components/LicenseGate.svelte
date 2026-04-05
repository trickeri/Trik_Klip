<script lang="ts">
  import { onMount } from 'svelte';
  import { licenseValid } from '../lib/stores';
  import { apiFetch } from '../lib/api';

  let licenseKey = '';
  let checking = false;
  let error = '';
  let initialCheck = true;

  // Dragging state
  let dragging = false;
  let dragOffsetX = 0;
  let dragOffsetY = 0;
  let modalX: number | null = null;
  let modalY: number | null = null;
  let modalEl: HTMLDivElement;

  function onMouseDown(e: MouseEvent) {
    // Only drag from the header area (not inputs/buttons)
    const target = e.target as HTMLElement;
    if (target.tagName === 'INPUT' || target.tagName === 'BUTTON' || target.tagName === 'A') return;
    dragging = true;
    const rect = modalEl.getBoundingClientRect();
    dragOffsetX = e.clientX - rect.left;
    dragOffsetY = e.clientY - rect.top;
  }

  function onMouseMove(e: MouseEvent) {
    if (!dragging) return;
    modalX = e.clientX - dragOffsetX;
    modalY = e.clientY - dragOffsetY;
  }

  function onMouseUp() {
    dragging = false;
  }

  onMount(async () => {
    // Check if there's a saved license key and auto-verify it
    try {
      const status = await apiFetch<{ has_license: boolean; license_key_preview?: string }>('/license/status');
      if (status.has_license) {
        // A key is saved — try to verify it with the server (which re-verifies with Gumroad or allows offline)
        const result = await apiFetch<{ valid: boolean; message?: string }>('/license/verify-saved', {
          method: 'POST',
        });
        if (result.valid) {
          licenseValid.set(true);
        }
      }
    } catch {
      // Server not reachable or license invalid
    } finally {
      initialCheck = false;
    }
  });

  async function verify() {
    if (!licenseKey.trim()) return;
    checking = true;
    error = '';

    try {
      const result = await apiFetch<{ valid: boolean; message?: string }>('/license/verify', {
        method: 'POST',
        body: JSON.stringify({ license_key: licenseKey.trim() }),
      });
      if (result.valid) {
        licenseValid.set(true);
      } else {
        error = result.message || 'Invalid license key';
      }
    } catch (e: any) {
      error = e.message || 'Verification failed';
    } finally {
      checking = false;
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') verify();
  }
</script>

<!-- svelte-ignore a11y-no-static-element-interactions -->
{#if !$licenseValid && !initialCheck}
  <div class="license-overlay" on:mousemove={onMouseMove} on:mouseup={onMouseUp}>
    <div
      class="license-modal"
      class:modal-dragging={dragging}
      bind:this={modalEl}
      on:mousedown={onMouseDown}
      style={modalX !== null ? `position:absolute;left:${modalX}px;top:${modalY}px;` : ''}
    >
      <h2>Trik Klip</h2>
      <p class="subtitle">Enter your license key to continue</p>

      <div class="input-group">
        <input
          type="text"
          class="license-input"
          placeholder="XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX"
          bind:value={licenseKey}
          on:keydown={handleKeydown}
          disabled={checking}
        />
        <button class="verify-btn" on:click={verify} disabled={checking || !licenseKey.trim()}>
          {checking ? 'Verifying...' : 'Verify'}
        </button>
      </div>

      {#if error}
        <p class="error-msg">{error}</p>
      {/if}

      <p class="help-text">
        Purchase a license at <a href="https://trikeri.gumroad.com" target="_blank" rel="noopener">trikeri.gumroad.com</a>
      </p>
    </div>
  </div>
{/if}

<style>
  .license-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.85);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
  }

  .license-modal {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 32px 40px;
    max-width: 480px;
    width: 90%;
    text-align: center;
    cursor: grab;
    user-select: none;
  }

  .license-modal :global(input),
  .license-modal :global(button),
  .license-modal :global(a) {
    cursor: auto;
    user-select: auto;
  }

  .modal-dragging {
    cursor: grabbing;
  }

  h2 {
    color: var(--text);
    font-size: 22px;
    margin-bottom: 6px;
  }

  .subtitle {
    color: var(--dim);
    font-size: 14px;
    margin-bottom: 24px;
  }

  .input-group {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
  }

  .license-input {
    flex: 1;
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--entry-bg);
    color: var(--text);
    font-size: 14px;
    font-family: "Cascadia Code", "Consolas", monospace;
    outline: none;
  }

  .license-input:focus {
    border-color: var(--accent);
  }

  .license-input:disabled {
    opacity: 0.6;
  }

  .verify-btn {
    padding: 10px 20px;
    border: none;
    border-radius: 6px;
    background: var(--accent);
    color: white;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }

  .verify-btn:hover:not(:disabled) {
    background: var(--accent2);
  }

  .verify-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .error-msg {
    color: var(--error);
    font-size: 13px;
    margin-bottom: 8px;
  }

  .help-text {
    color: var(--dim);
    font-size: 12px;
    margin-top: 16px;
  }

  .help-text a {
    color: var(--accent);
    text-decoration: none;
  }

  .help-text a:hover {
    text-decoration: underline;
  }
</style>
