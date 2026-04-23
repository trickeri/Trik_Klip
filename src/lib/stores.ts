import { writable } from 'svelte/store';
import type { ClipSuggestion, TranscriptSegment } from './types';

// Pipeline state
export const pipelineRunning = writable(false);
export const currentStage = writable('');

// Progress
export const hashProgress = writable(0);
export const whisperDownloadProgress = writable({
  model: '',
  percent: 0,
  bytes_done: 0,
  bytes_total: 0,
});
export const audioProgress = writable(0);
export const transcriptionProgress = writable(0);
export const transcriptionLabel = writable('');
export const analysisProgress = writable({ done: 0, total: 0 });
export const extractionProgress = writable({ done: 0, total: 0, clip_name: '' });
export const sliceProgress = writable({ done: 0, total: 0 });
export const visualProgress = writable({ done: 0, total: 0 });

// Active tab — lets non-UI modules request tab switches (e.g. SSE → Extract on pipeline done).
export const activeTab = writable(0);

// Results
export const clips = writable<ClipSuggestion[]>([]);
export const mp4Path = writable('');
export const outputDir = writable('');
export const transcriptSegments = writable<TranscriptSegment[]>([]);

// Audio track index selected in Transcribe — shared with Extract so clip
// MP4s carry the same track the user transcribed against (e.g. the mic
// track on multi-track stream recordings). -1 means "let ffmpeg pick".
export const audioTrack = writable<number>(-1);

// Log messages
export const logMessages = writable<Array<{ level: string; message: string; timestamp: string }>>([]);

// Settings
export const activeProfile = writable<{ provider: string; model: string; api_key: string; base_url: string } | null>(null);
export const language = writable('en');

// License
export const licenseValid = writable(false);

// Helper to add a log message
export function addLog(level: string, message: string) {
    const timestamp = new Date().toLocaleTimeString();
    logMessages.update(msgs => [...msgs.slice(-500), { level, message, timestamp }]);
}

// Reset progress state
export function resetProgress() {
    hashProgress.set(0);
    whisperDownloadProgress.set({ model: '', percent: 0, bytes_done: 0, bytes_total: 0 });
    audioProgress.set(0);
    transcriptionProgress.set(0);
    transcriptionLabel.set('');
    analysisProgress.set({ done: 0, total: 0 });
    extractionProgress.set({ done: 0, total: 0, clip_name: '' });
    sliceProgress.set({ done: 0, total: 0 });
    visualProgress.set({ done: 0, total: 0 });
    currentStage.set('');
}
