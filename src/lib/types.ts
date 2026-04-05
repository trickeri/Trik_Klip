export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

export interface ClipSuggestion {
  rank: number;
  title: string;
  hook: string;
  segment_start: number;
  segment_end: number;
  clip_start: number;
  clip_end: number;
  clip_duration: number;
  content_type: string;
  virality_score: number;
  transcript_excerpt: string;
}

export interface ProviderProfile {
  id: string;
  name: string;
  provider: string;
  model: string;
  api_key: string;
  base_url: string;
  is_default: boolean;
}

export interface PipelineParams {
  mp4_path: string;
  whisper_model: string;
  language: string;
  top_n: number;
  padding_minutes: number;
  window_minutes: number;
  overlap_minutes: number;
  audio_track?: number;
  custom_prompts: string[];
  provider: string;
  model?: string;
  output_dir: string;
}
