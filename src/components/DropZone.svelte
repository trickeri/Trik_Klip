<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { getCurrentWebview } from '@tauri-apps/api/webview';

  export let filePath = '';
  export let onSelect: (path: string) => void = () => {};
  export let accept = '.mp4';
  export let disabled = false;

  let dragging = false;
  let fileInput: HTMLInputElement;
  let dropzoneEl: HTMLDivElement;
  let unlisten: (() => void) | null = null;

  function isOverDropzone(px: number, py: number): boolean {
    if (!dropzoneEl) return false;
    const rect = dropzoneEl.getBoundingClientRect();
    // Tauri drag-drop positions are in physical pixels; CSS rects are logical.
    const dpr = window.devicePixelRatio || 1;
    const x = px / dpr;
    const y = py / dpr;
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
  }

  onMount(async () => {
    unlisten = await getCurrentWebview().onDragDropEvent((event) => {
      if (disabled) {
        dragging = false;
        return;
      }
      const p = event.payload;
      if (p.type === 'enter' || p.type === 'over') {
        const pos = (p as any).position;
        dragging = pos ? isOverDropzone(pos.x, pos.y) : false;
      } else if (p.type === 'leave') {
        dragging = false;
      } else if (p.type === 'drop') {
        dragging = false;
        const pos = (p as any).position;
        if (!pos || !isOverDropzone(pos.x, pos.y)) return;
        const paths = (p as any).paths as string[] | undefined;
        const match = paths?.find((f) => f.toLowerCase().endsWith('.mp4'));
        if (match) {
          filePath = match;
          onSelect(match);
        }
      }
    });
  });

  onDestroy(() => {
    if (unlisten) unlisten();
  });

  function handleClick() {
    if (!disabled) {
      fileInput?.click();
    }
  }

  function handleFileInput(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      const path = (file as any).path || file.name;
      filePath = path;
      onSelect(path);
    }
  }
</script>

<!-- svelte-ignore a11y-no-static-element-interactions -->
<!-- svelte-ignore a11y-click-events-have-key-events -->
<div
  bind:this={dropzoneEl}
  class="dropzone"
  class:dragging
  class:disabled
  class:has-file={!!filePath}
  on:click={handleClick}
  role="button"
  tabindex="0"
>
  {#if filePath}
    <div class="file-info">
      <span class="file-icon">&#128253;</span>
      <span class="file-path">{filePath}</span>
    </div>
  {:else}
    <div class="prompt">
      <span class="drop-icon">&#128194;</span>
      <span>Drop an .mp4 file here or click to browse</span>
    </div>
  {/if}
</div>

<input
  bind:this={fileInput}
  type="file"
  {accept}
  class="hidden-input"
  on:change={handleFileInput}
/>

<style>
  .dropzone {
    border: 2px dashed var(--border);
    border-radius: 8px;
    padding: 32px 20px;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
    background: var(--card);
    user-select: none;
  }

  .dropzone:hover,
  .dropzone.dragging {
    border-color: var(--accent);
    background: var(--entry-bg);
  }

  .dropzone.disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .dropzone.has-file {
    border-style: solid;
    border-color: var(--success);
  }

  .prompt {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    color: var(--dim);
    font-size: 14px;
  }

  .drop-icon {
    font-size: 28px;
  }

  .file-info {
    display: flex;
    align-items: center;
    gap: 10px;
    justify-content: center;
  }

  .file-icon {
    font-size: 20px;
  }

  .file-path {
    font-size: 13px;
    color: var(--text);
    word-break: break-all;
  }

  .hidden-input {
    display: none;
  }
</style>
