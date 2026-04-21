const BASE = "http://127.0.0.1:31416";

import type { ClipSuggestion } from './types';

export type ProgressEvent =
  | { type: "Hashing"; percent: number }
  | { type: "AudioExtraction"; percent: number }
  | { type: "SpikeDetection"; spike_count: number }
  | { type: "Transcription"; percent: number; label: string }
  | { type: "Chunking"; chunk_count: number }
  | { type: "Analysis"; done: number; total: number }
  | { type: "ClipExtraction"; done: number; total: number; clip_name: string }
  | { type: "SliceGeneration"; done: number; total: number }
  | { type: "ClipsReady"; clips: ClipSuggestion[] }
  | { type: "Log"; level: string; message: string }
  | { type: "PipelineDone" }
  | { type: "PipelineError"; message: string };

export function subscribeProgress(
  onEvent: (event: ProgressEvent) => void,
  onError?: (err: Event) => void
): () => void {
  const es = new EventSource(`${BASE}/api/pipeline/progress`);

  es.onmessage = (e) => {
    try {
      const event: ProgressEvent = JSON.parse(e.data);
      onEvent(event);
    } catch {
      // ignore malformed events
    }
  };

  es.onerror = (e) => {
    if (onError) onError(e);
  };

  // Return cleanup function
  return () => es.close();
}

// Store-integrated SSE connection
import {
  pipelineRunning,
  hashProgress,
  audioProgress,
  transcriptionProgress,
  transcriptionLabel,
  analysisProgress,
  extractionProgress,
  currentStage,
  clips,
  activeTab,
  addLog,
} from './stores';

// Tab index for the Extract tab in App.svelte's tab array.
const EXTRACT_TAB_INDEX = 1;

export function connectProgress(): () => void {
  return subscribeProgress((event) => {
    switch (event.type) {
      case 'Hashing':
        currentStage.set('hashing');
        hashProgress.set(event.percent);
        break;
      case 'AudioExtraction':
        currentStage.set('audio');
        audioProgress.set(event.percent);
        break;
      case 'SpikeDetection':
        currentStage.set('spikes');
        addLog('info', `Detected ${event.spike_count} volume spikes`);
        break;
      case 'Transcription':
        currentStage.set('transcription');
        transcriptionProgress.set(event.percent);
        transcriptionLabel.set(event.label);
        break;
      case 'Chunking':
        currentStage.set('chunking');
        addLog('info', `Split transcript into ${event.chunk_count} chunks`);
        break;
      case 'Analysis':
        currentStage.set('analysis');
        analysisProgress.set({ done: event.done, total: event.total });
        break;
      case 'ClipExtraction':
        currentStage.set('extraction');
        extractionProgress.set({ done: event.done, total: event.total, clip_name: event.clip_name });
        break;
      case 'SliceGeneration':
        currentStage.set('slices');
        addLog('info', `Slice generation: ${event.done}/${event.total}`);
        break;
      case 'ClipsReady':
        clips.set(event.clips);
        addLog('info', `Found ${event.clips.length} clip${event.clips.length === 1 ? '' : 's'}`);
        if (event.clips.length > 0) {
          activeTab.set(EXTRACT_TAB_INDEX);
        }
        break;
      case 'Log':
        addLog(event.level, event.message);
        break;
      case 'PipelineDone':
        pipelineRunning.set(false);
        currentStage.set('');
        addLog('info', 'Pipeline complete!');
        break;
      case 'PipelineError':
        pipelineRunning.set(false);
        currentStage.set('');
        addLog('error', event.message);
        break;
    }
  });
}
