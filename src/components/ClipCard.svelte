<script lang="ts">
  import type { ClipSuggestion } from '../lib/types';

  export let clip: ClipSuggestion;
  export let selected = false;
  export let onToggle: (rank: number) => void = () => {};

  function formatTime(seconds: number): string {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function scoreColor(score: number): string {
    if (score >= 8) return 'var(--success)';
    if (score >= 5) return 'var(--warn)';
    return 'var(--error)';
  }
</script>

<div class="clip-card" class:selected>
  <div class="clip-header">
    <label class="clip-check">
      <input type="checkbox" checked={selected} on:change={() => onToggle(clip.rank)} />
      <span class="rank">#{clip.rank}</span>
    </label>
    <span class="clip-title">{clip.title}</span>
    <span class="virality" style="color: {scoreColor(clip.virality_score)}">
      {clip.virality_score.toFixed(1)}
    </span>
  </div>

  <div class="clip-meta">
    <span class="badge">{clip.content_type}</span>
    <span class="time-range">
      {formatTime(clip.clip_start)} - {formatTime(clip.clip_end)}
    </span>
    <span class="duration">({formatTime(clip.clip_duration)})</span>
  </div>

  {#if clip.hook}
    <div class="hook">{clip.hook}</div>
  {/if}

  {#if clip.transcript_excerpt}
    <div class="excerpt">{clip.transcript_excerpt}</div>
  {/if}
</div>

<style>
  .clip-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px;
    transition: border-color 0.15s;
  }

  .clip-card.selected {
    border-color: var(--accent);
  }

  .clip-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
  }

  .clip-check {
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
  }

  .clip-check input[type="checkbox"] {
    accent-color: var(--accent);
    width: 16px;
    height: 16px;
    cursor: pointer;
  }

  .rank {
    font-size: 12px;
    color: var(--dim);
    font-weight: 600;
  }

  .clip-title {
    flex: 1;
    font-weight: 600;
    font-size: 14px;
    color: var(--text);
  }

  .virality {
    font-size: 18px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }

  .clip-meta {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
    font-size: 12px;
  }

  .badge {
    background: var(--accent);
    color: white;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
  }

  .time-range {
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }

  .duration {
    color: var(--dim);
  }

  .hook {
    font-size: 13px;
    color: var(--text);
    font-style: italic;
    margin-bottom: 6px;
  }

  .excerpt {
    font-size: 12px;
    color: var(--dim);
    line-height: 1.5;
    max-height: 60px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
