import { writable } from 'svelte/store';
import type { ClipSuggestion, TranscriptSegment } from './types';

// Pipeline state
export const pipelineRunning = writable(false);
export const currentStage = writable('');

// Progress
export const audioProgress = writable(0);
export const transcriptionProgress = writable(0);
export const transcriptionLabel = writable('');
export const analysisProgress = writable({ done: 0, total: 0 });
export const extractionProgress = writable({ done: 0, total: 0, clip_name: '' });

// Results
export const clips = writable<ClipSuggestion[]>([]);
export const mp4Path = writable('');
export const outputDir = writable('');
export const transcriptSegments = writable<TranscriptSegment[]>([]);

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
    audioProgress.set(0);
    transcriptionProgress.set(0);
    transcriptionLabel.set('');
    analysisProgress.set({ done: 0, total: 0 });
    extractionProgress.set({ done: 0, total: 0, clip_name: '' });
    currentStage.set('');
}
