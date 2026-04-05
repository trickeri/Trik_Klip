const BASE = "http://127.0.0.1:31416";

export type ProgressEvent =
  | { type: "AudioExtraction"; percent: number }
  | { type: "SpikeDetection"; spike_count: number }
  | { type: "Transcription"; percent: number; label: string }
  | { type: "Chunking"; chunk_count: number }
  | { type: "Analysis"; done: number; total: number }
  | { type: "ClipExtraction"; done: number; total: number; clip_name: string }
  | { type: "SliceGeneration"; done: number; total: number }
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
  audioProgress,
  transcriptionProgress,
  transcriptionLabel,
  analysisProgress,
  extractionProgress,
  currentStage,
  addLog,
} from './stores';

export function connectProgress(): () => void {
  return subscribeProgress((event) => {
    switch (event.type) {
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
