const BASE = "http://127.0.0.1:31416";

import type { ClipSuggestion, TranscriptSegment } from './types';

export type ProgressEvent =
  | { type: "Hashing"; percent: number }
  | { type: "WhisperDownload"; model: string; percent: number; bytes_done: number; bytes_total: number }
  | { type: "AudioExtraction"; percent: number }
  | { type: "SpikeDetection"; spike_count: number }
  | { type: "Transcription"; percent: number; label: string }
  | { type: "Chunking"; chunk_count: number }
  | { type: "Analysis"; done: number; total: number }
  | { type: "ClipExtraction"; done: number; total: number; clip_name: string }
  | { type: "SliceGeneration"; done: number; total: number }
  | { type: "VisualAids"; done: number; total: number }
  | { type: "ClipsReady"; clips: ClipSuggestion[]; segments?: TranscriptSegment[] }
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
  whisperDownloadProgress,
  audioProgress,
  transcriptionProgress,
  transcriptionLabel,
  analysisProgress,
  extractionProgress,
  sliceProgress,
  visualProgress,
  currentStage,
  clips,
  transcriptSegments,
  activeTab,
  addLog,
} from './stores';

// Tab indices (matches App.svelte's tab array).
const EXTRACT_TAB_INDEX = 1;
const SLICE_TAB_INDEX = 2;

export function connectProgress(): () => void {
  // Track the last stage synchronously so PipelineDone can decide where to
  // navigate before we clear the stage.
  let lastStage = '';
  const unsubStage = currentStage.subscribe(v => { lastStage = v; });
  void unsubStage; // keep subscription alive for module lifetime

  return subscribeProgress((event) => {
    switch (event.type) {
      case 'Hashing':
        currentStage.set('hashing');
        hashProgress.set(event.percent);
        break;
      case 'WhisperDownload':
        currentStage.set('whisper_download');
        whisperDownloadProgress.set({
          model: event.model,
          percent: event.percent,
          bytes_done: event.bytes_done,
          bytes_total: event.bytes_total,
        });
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
        sliceProgress.set({ done: event.done, total: event.total });
        break;
      case 'VisualAids':
        currentStage.set('visuals');
        visualProgress.set({ done: event.done, total: event.total });
        break;
      case 'ClipsReady':
        clips.set(event.clips);
        if (event.segments) {
          transcriptSegments.set(event.segments);
        }
        addLog('info', `Found ${event.clips.length} clip${event.clips.length === 1 ? '' : 's'}`);
        if (event.clips.length > 0) {
          activeTab.set(EXTRACT_TAB_INDEX);
        }
        break;
      case 'Log':
        addLog(event.level, event.message);
        break;
      case 'PipelineDone': {
        const wasExtracting = lastStage === 'extraction';
        const wasSlicing = lastStage === 'slices';
        console.log('[sse] PipelineDone — lastStage =', lastStage, 'wasExtracting =', wasExtracting);
        pipelineRunning.set(false);
        currentStage.set('');
        addLog('info', 'Pipeline complete!');
        // After clips have been extracted to disk, send the user to Slice so
        // they can generate cut plans from the new MP4s. The Slice tab already
        // subscribes to outputDir for its clip_dir, so no extra wiring needed.
        if (wasExtracting) {
          activeTab.set(SLICE_TAB_INDEX);
        } else if (wasSlicing) {
          // No-op — already on Slice. Keeping for clarity if we add per-clip
          // nav later.
        }
        break;
      }
      case 'PipelineError':
        pipelineRunning.set(false);
        currentStage.set('');
        addLog('error', event.message);
        break;
    }
  });
}
