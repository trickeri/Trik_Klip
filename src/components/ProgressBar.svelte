<script lang="ts">
  export let label = '';
  export let value = 0;
  export let max = 100;
  export let showCount = false;
  export let indeterminate = false;

  $: percent = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  $: displayText = showCount ? `${value} / ${max}` : `${Math.round(percent)}%`;
</script>

<div class="progress-container">
  <div class="progress-header">
    {#if label}
      <span class="progress-label">{label}</span>
    {/if}
    {#if !indeterminate}
      <span class="progress-value">{displayText}</span>
    {/if}
  </div>
  <div class="progress-track">
    {#if indeterminate}
      <div class="progress-indeterminate"></div>
    {:else}
      <div
        class="progress-fill"
        style="width: {percent}%"
        class:complete={percent >= 100}
      ></div>
    {/if}
  </div>
</div>

<style>
  .progress-container {
    width: 100%;
  }

  .progress-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 4px;
    font-size: 12px;
  }

  .progress-label {
    color: var(--text);
    font-weight: 500;
  }

  .progress-value {
    color: var(--dim);
    font-variant-numeric: tabular-nums;
  }

  .progress-track {
    height: 6px;
    background: var(--entry-bg);
    border-radius: 3px;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: var(--accent);
    border-radius: 3px;
    transition: width 0.3s ease;
  }

  .progress-fill.complete {
    background: var(--success);
  }

  .progress-indeterminate {
    position: relative;
    height: 100%;
    width: 100%;
    overflow: hidden;
  }

  .progress-indeterminate::before {
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    height: 100%;
    width: 40%;
    background: var(--accent);
    border-radius: 3px;
    animation: indeterminate 1.2s ease-in-out infinite;
  }

  @keyframes indeterminate {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(250%); }
  }
</style>
