import type { TargetLanguage } from "./translationLanguages";
import type {
  BridgeEvent,
  Segment,
  SourceState,
  TranslationState,
} from "./types";
export interface TranscriptState {
  sessionId: string;
  targetLanguage: TargetLanguage;
  sources: Record<string, SourceState>;
  translations: Record<string, TranslationState>;
  seen: string[];
  lastSeq: number;
  clearedSeq: number;
  controlSeq: number;
  closedStreams: string[];
  activeStream?: string;
}
export const identity = (s: Pick<Segment, "stream_id" | "sentence_id">) =>
  `${s.stream_id}:${s.sentence_id}`;
const keyOf = (e: BridgeEvent) =>
  identity({ stream_id: e.stream_id!, sentence_id: e.sentence_id! });
const seqOf = (e: BridgeEvent) => e.snapshot_seq ?? e.event_seq ?? 0;

export function initialTranscript(
  sessionId: string,
  segments: Segment[] = [],
  unconfirmed: Segment[] = [],
  targetLanguage: TargetLanguage = "zh-CN",
): TranscriptState {
  let state: TranscriptState = {
    sessionId,
    targetLanguage,
    sources: {},
    translations: {},
    seen: [],
    lastSeq: 0,
    clearedSeq: 0,
    controlSeq: 0,
    closedStreams: [],
  };
  for (const s of [...unconfirmed, ...segments]) {
    state = applyEvent(state, {
      ...s,
      session_id: sessionId,
      event_id: `initial:${identity(s)}:${s.source_revision}:${s.source_status}`,
      event_seq: 0,
      snapshot_seq: s.source_event_seq,
      type:
        s.source_status === "interrupted" || s.status === "interrupted"
          ? "transcript.interrupted"
          : "segment.updated",
    });
  }
  return state;
}

// This handler owns source lifecycle. It never writes the translation map.
export function applySourceEvent(
  state: TranscriptState,
  event: BridgeEvent,
): TranscriptState {
  const key = keyOf(event),
    old = state.sources[key],
    revision = event.source_revision || 1;
  const partial = event.type === "transcript.partial";
  const interrupted =
    event.type === "transcript.interrupted" ||
    event.source_status === "interrupted";
  if (
    partial &&
    (state.closedStreams.includes(event.stream_id!) ||
      (state.activeStream && state.activeStream !== event.stream_id))
  )
    return state;
  if (
    old &&
    (revision < old.revision ||
      ((partial || interrupted) && ["final", "retired"].includes(old.status)))
  )
    return state;
  if (old?.status === "retired" && revision === old.revision) return state;
  if (partial && old?.status === "interrupted") return state;
  if (old && seqOf(event) && seqOf(event) < (old.source_event_seq || 0))
    return state;
  // A same-version snapshot cannot silently rewrite an already authoritative final.
  if (
    old?.status === "final" &&
    revision === old.revision &&
    event.text !== undefined &&
    event.text !== old.text
  )
    return state;
  const status =
    event.status === "retired"
      ? "retired"
      : interrupted
        ? "interrupted"
        : partial
          ? "partial"
          : "final";
  const text = event.text ?? old?.text ?? "";
  const value: SourceState = {
    sentence_id: event.sentence_id!,
    stream_id: event.stream_id!,
    text,
    revision,
    status,
    start_ms: event.start_ms ?? old?.start_ms ?? 0,
    end_ms: event.end_ms ?? old?.end_ms ?? 0,
    mode: event.mode ?? old?.mode ?? "demo",
    source_event_seq: seqOf(event) || old?.source_event_seq,
    speaker: event.speaker ?? old?.speaker,
    provenance: event.provenance ?? old?.provenance,
    latency: { ...old?.latency, ...event.latency },
  };
  if (partial) {
    value.previous_partial =
      old?.status === "partial" && old.text !== text
        ? { text: old.text.slice(0, 2000), revision: old.revision }
        : old?.previous_partial;
    if (
      event.stable_preview !== undefined &&
      event.stable_preview + (event.unstable_tail || "") === text
    ) {
      value.stable_preview = event.stable_preview;
      value.unstable_tail = event.unstable_tail;
      value.hypothesis_revision = event.hypothesis_revision;
    }
  }
  return { ...state, sources: { ...state.sources, [key]: value } };
}

// Translation metadata can validate a source, never create or change one.
export function applyTranslationEvent(
  state: TranscriptState,
  event: BridgeEvent,
): TranscriptState {
  // Missing language is exclusively the legacy Chinese event contract.
  if ((event.target_language ?? "zh-CN") !== state.targetLanguage) return state;
  const key = keyOf(event),
    source = state.sources[key],
    old = state.translations[key];
  const revision = event.source_revision || 1,
    tr = event.translation_revision || 1;
  const preview = event.preview_source_text !== undefined;
  const failed = event.type === "processing.failed";
  if (source?.status === "retired") return state;
  if (source && revision < source.revision) return state;
  if (source?.status === "final" && preview) return state;
  if (
    source?.status === "final" &&
    revision > source.revision &&
    event.type === "translation.partial" &&
    event.source_status !== "final"
  )
    return state;
  if (
    event.type === "translation.partial" &&
    event.source_status !== "final" &&
    (state.closedStreams.includes(event.stream_id!) ||
      (state.activeStream && event.stream_id !== state.activeStream))
  )
    return state;
  if (preview && source && !source.text.startsWith(event.preview_source_text!))
    return state;
  if (old && revision < old.source_revision) return state;
  if (
    preview &&
    (event.preview_request_id || 0) < (old?.preview_request_id || 0)
  )
    return state;
  const same = old?.source_revision === revision;
  const replacement =
    preview && (event.preview_request_id || 0) > (old?.preview_request_id || 0);
  if (same) {
    if (seqOf(event) && seqOf(event) < (old.translation_event_seq || 0))
      return state;
    if (
      old.status === "final" &&
      (event.type === "translation.partial" || failed)
    )
      return state;
    if (tr < old.revision && !failed) return state;
    if (
      preview &&
      ((event.preview_request_id || 0) < (old.preview_request_id || 0) ||
        (old.preview_complete && !replacement && !event.preview_complete))
    )
      return state;
    if (
      event.type === "translation.partial" &&
      !replacement &&
      tr === old.revision &&
      (event.translation?.length || 0) < old.text.length
    )
      return state;
  }
  const value: TranslationState = {
    target_language: state.targetLanguage,
    sentence_id: event.sentence_id!,
    stream_id: event.stream_id!,
    source_revision: revision,
    revision: failed && same ? old.revision : tr,
    text: failed ? (same ? old.text : "") : (event.translation ?? ""),
    status: failed
      ? "failed"
      : event.type === "translation.partial"
        ? "partial"
        : "final",
    translation_event_seq:
      seqOf(event) || (same ? old.translation_event_seq : undefined),
    preview_source_text: event.preview_source_text,
    preview_request_id: event.preview_request_id,
    preview_complete: event.preview_complete,
    error: failed ? event.message : undefined,
    latency: { ...(same ? old.latency : undefined), ...event.latency },
  };
  const translations = { ...state.translations, [key]: value };
  // Misordered translation-only messages may wait for sources, but never grow without bound.
  const orphans = Object.keys(translations).filter((k) => !state.sources[k]);
  for (const k of orphans.slice(0, Math.max(0, orphans.length - 200)))
    delete translations[k];
  return { ...state, translations };
}

export function applySessionEvent(
  state: TranscriptState,
  event: BridgeEvent,
): TranscriptState {
  if (event.cleared) {
    const sources = Object.fromEntries(
      Object.entries(state.sources).filter(
        ([, s]) => (s.source_event_seq || 0) > event.event_seq,
      ),
    );
    const translations = Object.fromEntries(
      Object.entries(state.translations).filter(
        ([, t]) => (t.translation_event_seq || 0) > event.event_seq,
      ),
    );
    return {
      ...state,
      sources,
      translations,
      clearedSeq: Math.max(state.clearedSeq, event.event_seq),
      controlSeq: Math.max(state.controlSeq, event.event_seq),
      closedStreams: [
        ...new Set([
          ...state.closedStreams,
          ...Object.values(state.sources)
            .filter((s) => !sources[identity(s)])
            .map((s) => s.stream_id),
        ]),
      ].slice(-200),
    };
  }
  const status = event.state || event.status || "";
  if (!event.stream_id) return state;
  const starting = ["preparing", "recording"].includes(status),
    ending = ["stopped", "failed"].includes(status);
  if (!starting && !ending) return state;
  if (starting && event.event_seq > 0 && event.event_seq < state.controlSeq)
    return state;
  const sources = { ...state.sources };
  for (const [key, s] of Object.entries(sources)) {
    if (
      s.status === "partial" &&
      (starting
        ? s.stream_id !== event.stream_id
        : s.stream_id === event.stream_id)
    )
      sources[key] = {
        ...s,
        status: "interrupted",
        stable_preview: undefined,
        unstable_tail: undefined,
      };
  }
  return {
    ...state,
    sources,
    activeStream: starting ? event.stream_id : state.activeStream,
    controlSeq: Math.max(state.controlSeq, event.event_seq || 0),
    closedStreams: ending
      ? [...new Set([...state.closedStreams, event.stream_id])].slice(-200)
      : state.closedStreams,
  };
}

function applySegmentUpdated(
  state: TranscriptState,
  event: BridgeEvent,
): TranscriptState {
  const next = applySourceEvent(state, event);
  if (
    event.text !== undefined &&
    next.sources[keyOf(event)]?.text !== event.text
  )
    return next;
  if (
    event.translation_status === "failed" &&
    next.sources[keyOf(event)]?.revision === event.source_revision
  )
    return applyTranslationEvent(next, {
      ...event,
      type: "processing.failed",
      task_kind: "translate",
      message: event.translation_error,
    });
  if (
    !event.translation ||
    event.status === "retired" ||
    event.source_status === "interrupted"
  )
    return next;
  return applyTranslationEvent(next, { ...event, type: "translation.final" });
}

export function applyEvent(
  state: TranscriptState,
  event: BridgeEvent,
): TranscriptState {
  if (
    event.session_id !== state.sessionId ||
    state.seen.includes(event.event_id) ||
    (seqOf(event) > 0 && seqOf(event) <= state.clearedSeq) ||
    (state.clearedSeq > 0 &&
      event.snapshot_seq !== undefined &&
      event.snapshot_seq <= state.clearedSeq) ||
    (state.clearedSeq > 0 &&
      seqOf(event) === 0 &&
      !!event.stream_id &&
      state.closedStreams.includes(event.stream_id))
  )
    return state;
  const next = {
    ...state,
    lastSeq: Math.max(state.lastSeq, event.event_seq || 0),
    seen: [...state.seen.slice(-2047), event.event_id],
  };
  if (event.type === "session.state") return applySessionEvent(next, event);
  if (!event.sentence_id || !event.stream_id) return next;
  switch (event.type) {
    case "transcript.partial":
    case "transcript.final":
    case "transcript.interrupted":
      return applySourceEvent(next, event);
    case "translation.partial":
    case "translation.final":
      return applyTranslationEvent(next, event);
    case "processing.failed":
      return event.task_kind === "translate" &&
        event.source_revision !== undefined
        ? applyTranslationEvent(next, event)
        : next;
    case "segment.updated":
      return applySegmentUpdated(next, event);
    default:
      return next;
  }
}

export function matchesSource(s: SourceState, t: TranslationState): boolean {
  return identity(s) === identity(t) && s.revision === t.source_revision;
}
function visibleTranslation(
  s: SourceState,
  t?: TranslationState,
): TranslationState | undefined {
  if (!t || s.status === "interrupted") return undefined;
  if (t.preview_source_text !== undefined) {
    if (s.status !== "partial" || !s.text.startsWith(t.preview_source_text))
      return undefined;
    return matchesSource(s, t) ||
      (t.preview_complete &&
        s.stable_preview !== undefined &&
        t.source_revision < s.revision)
      ? t
      : undefined;
  }
  return matchesSource(s, t) ? t : undefined;
}
export function orderedSegments(state: TranscriptState): Segment[] {
  return Object.values(state.sources)
    .filter((s) => s.status !== "retired")
    .map((s): Segment => {
      const t = visibleTranslation(s, state.translations[identity(s)]);
      return {
        target_language: state.targetLanguage,
        sentence_id: s.sentence_id,
        stream_id: s.stream_id,
        text: s.text,
        source_revision: s.revision,
        source_status: s.status,
        source_final: s.status === "final",
        translation: t?.text ?? "",
        translation_revision: t?.revision ?? 0,
        translation_status: t?.status ?? "pending",
        translation_final: t?.status === "final",
        translation_error: t?.error,
        status:
          s.status === "final"
            ? t?.status === "final"
              ? "final"
              : "translating"
            : s.status,
        start_ms: s.start_ms,
        end_ms: s.end_ms,
        mode: s.mode,
        speaker: s.speaker,
        provenance: s.provenance,
        stable_preview: s.stable_preview,
        unstable_tail: s.unstable_tail,
        hypothesis_revision: s.hypothesis_revision,
        preview_source_text: t?.preview_source_text,
        preview_request_id: t?.preview_request_id,
        preview_complete: t?.preview_complete,
        source_event_seq: s.source_event_seq,
        translation_event_seq: t?.translation_event_seq,
        latency: { ...s.latency, ...t?.latency },
      };
    })
    .sort(
      (a, b) =>
        a.start_ms - b.start_ms ||
        a.end_ms - b.end_ms ||
        identity(a).localeCompare(identity(b)),
    );
}
