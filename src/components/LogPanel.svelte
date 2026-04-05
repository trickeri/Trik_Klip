<script lang="ts">
  import { logMessages } from '../lib/stores';
  import { afterUpdate } from 'svelte';

  let logContainer: HTMLDivElement;

  afterUpdate(() => {
    if (logContainer) {
      logContainer.scrollTop = logContainer.scrollHeight;
    }
  });

  function levelClass(level: string): string {
    switch (level) {
      case 'error': return 'log-error';
      case 'warn':
      case 'warning': return 'log-warn';
      case 'debug': return 'log-debug';
      default: return 'log-info';
    }
  }
</script>

<div class="log-panel" bind:this={logContainer}>
  {#each $logMessages as msg}
    <div class="log-line {levelClass(msg.level)}">
      <span class="log-time">{msg.timestamp}</span>
      <span class="log-level">[{msg.level.toUpperCase()}]</span>
      <span class="log-msg">{msg.message}</span>
    </div>
  {/each}
  {#if $logMessages.length === 0}
    <div class="log-empty">Waiting for log output...</div>
  {/if}
</div>

<style>
  .log-panel {
    height: 100%;
    overflow-y: auto;
    padding: 8px 12px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
    line-height: 1.6;
  }

  .log-line {
    display: flex;
    gap: 8px;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .log-time {
    color: var(--dim);
    flex-shrink: 0;
  }

  .log-level {
    flex-shrink: 0;
    min-width: 56px;
  }

  .log-msg {
    flex: 1;
  }

  .log-info {
    color: var(--text);
  }

  .log-warn .log-level,
  .log-warn .log-msg {
    color: var(--warn);
  }

  .log-error .log-level,
  .log-error .log-msg {
    color: var(--error);
  }

  .log-debug {
    color: var(--dim);
  }

  .log-empty {
    color: var(--dim);
    padding: 4px 0;
  }
</style>
