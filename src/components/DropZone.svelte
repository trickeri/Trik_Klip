<script lang="ts">
  export let filePath = '';
  export let onSelect: (path: string) => void = () => {};
  export let accept = '.mp4';
  export let disabled = false;

  let dragging = false;
  let fileInput: HTMLInputElement;

  function handleDragOver(e: DragEvent) {
    e.preventDefault();
    if (!disabled) dragging = true;
  }

  function handleDragLeave() {
    dragging = false;
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    dragging = false;
    if (disabled) return;

    const files = e.dataTransfer?.files;
    if (files && files.length > 0) {
      const file = files[0];
      if (file.name.endsWith('.mp4')) {
        // In Tauri, dataTransfer gives us the full path
        const path = (file as any).path || file.name;
        filePath = path;
        onSelect(path);
      }
    }
  }

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
  class="dropzone"
  class:dragging
  class:disabled
  class:has-file={!!filePath}
  on:dragover={handleDragOver}
  on:dragleave={handleDragLeave}
  on:drop={handleDrop}
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
