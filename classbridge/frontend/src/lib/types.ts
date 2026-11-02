export type Mode = "demo" | "real";
export type Page = "home" | "session" | "library" | "settings";
export interface User {
  id: string;
  username: string;
}
export interface Segment {
  suggestion?: CorrectionSuggestion | null;
  suggestion_event_seq?: number;
  provenance?: string;
  sentence_id: string;
  stream_id: string;
  source_revision: number;
  translation_revision: number;
  start_ms: number;
  end_ms: number;
  text: string;
  translation: string;
  status: string;
  mode: Mode;
  source_final?: boolean;
  translation_final?: boolean;
  source_event_seq?: number;
  translation_event_seq?: number;
  speaker?: string | null;
  latency?: Record<string, number | string | boolean | null>;
}
export interface CorrectionSuggestion {
  task_id: string;
  status: "unconfirmed";
  source_revision: number;
  audio_verified: false;
  suggested_text: string;
  edits: { before: string; after: string; reason: string; kind: string; evidence_ids: string[] }[];
  evidence: { id: string; kind: string; quote: string; sentence_id?: string; source_revision?: number; session_id?: string }[];
}
export interface Stage {
  id: string;
  superseded?: boolean;
  topic: string;
  summary: string;
  knowledge_points: unknown[];
  terms: unknown[];
  decisions: unknown[];
  action_items: unknown[];
  source_sentence_ids: string[];
  sources?: {
    sentence_id: string;
    source_revision: number;
    session_id: string;
  }[];
}
export interface Session {
  id: string;
  title: string;
  kind: string;
  mode: Mode;
  status: string;
  retain_audio: boolean;
  created_at: string;
  duration_ms: number;
  captured_ms?: number;
  segments?: Segment[];
  stages?: Stage[];
  audio_status?: string;
  audio_assets?: unknown[];
  event_seq?: number;
  speaker_names?: Record<string, string>;
  tasks?: { id: string; kind: string; status: string; error?: string }[];
  gaps?: BridgeEvent[];
}
export interface BridgeEvent extends Partial<Segment> {
  type: string;
  event_id: string;
  event_seq: number;
  session_id: string;
  message?: string;
  state?: string;
  code?: string;
  queue_size?: number;
  latency?: Record<string, number | string | boolean | null>;
  source_status?: string;
  cleared?: boolean;
  recovered?: boolean;
  task_kind?: string;
  offset_ms?: number;
  captured_ms?: number;
  ready?: boolean;
  request_id?: string;
  snapshot_seq?: number;
  asr_language_mode?: import("./asrLanguages").ASRLanguageMode;
  asr_acoustic_profile?: "far" | "near";
  asr_enhancement?: { hotword_count: number; weight: number; context_chars: number };
  diagnostics?: import("./captureHealth").CaptureHealth;
  data?: Record<string, unknown>;
}
export interface Document {
  id: string;
  name?: string;
  filename?: string;
  status: string;
  index_status?: string;
  index_mode?: Mode;
  error?: string;
  page_count?: number;
  created_at?: string;
  version?: number;
  chunks?: {
    id: string;
    page?: number;
    position?: number;
    location?: string;
    text: string;
  }[];
}
export interface Citation {
  id: string;
  chunk_id?: string;
  label?: string;
  kind: "sentence" | "document";
  sentence_id?: string;
  source_revision?: number;
  session_id?: string;
  document_id?: string;
  page?: number;
  location?: string;
  position?: number;
  quote: string;
}
export interface ChatReply {
  answer: string;
  citations: Citation[];
  mode: Mode;
}
export interface Preferences {
  asr_assist_enabled?: boolean;
  asr_hotword_weight?: 2 | 3 | 4;
  asr_acoustic_profile?: "far" | "near";
  audio_processing_mode?: "standard" | "natural";
  asr_context?: string;
  asr_terms_status?: { enabled_count: number; skipped: { index: number; reason: string }[] };
  asr_language_mode?: import("./asrLanguages").ASRLanguageMode;
  theme: "light" | "dark";
  subtitle_size: number;
  show_original: boolean;
  retain_audio: boolean;
  audio_retention_days: number;
  terms: (string | Record<string, string>)[];
  target_language?: string;
  real_ready?: boolean;
  configuration_error?: { code: string; message: string } | null;
  model_status?: string;
  api_key_configured?: boolean;
  workspace_configured?: boolean;
  models?: Record<string, string>;
  region?: string;
  [key: string]: unknown;
}
