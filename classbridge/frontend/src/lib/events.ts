import type { BridgeEvent, Segment } from "./types";
export interface TranscriptState {
  sessionId: string;
  segments: Record<string, Segment>;
  seen: string[];
  lastSeq: number;
  clearedSeq: number;
  closedStreams: string[];
  activeStream?: string;
}
export const identity = (s: Pick<Segment, "stream_id" | "sentence_id">) =>
  `${s.stream_id}:${s.sentence_id}`;
export function initialTranscript(
  sessionId: string,
  segments: Segment[] = [],
): TranscriptState {
  return {
    sessionId,
    segments: Object.fromEntries(
      segments.map((s) => [
        identity(s),
        { ...s, source_final: true, translation_final: !!s.translation },
      ]),
    ),
    seen: [],
    lastSeq: 0,
    clearedSeq: 0,
    closedStreams: [],
  };
}
export function applyEvent(
  state: TranscriptState,
  event: BridgeEvent,
): TranscriptState {
  if (
    event.session_id !== state.sessionId ||
    state.seen.includes(event.event_id) ||
    (event.event_seq > 0 && event.event_seq <= state.clearedSeq)
  )
    return state;
  const next = {
    ...state,
    lastSeq: Math.max(state.lastSeq, event.event_seq || 0),
    seen: [...state.seen.slice(-2047), event.event_id],
  };
  if (event.type === "session.state") {
    if (event.cleared)
      return { ...next, segments: {}, clearedSeq: event.event_seq };
    if (event.stream_id && ["preparing", "recording"].includes(event.state || event.status || "")) {
      // Durable historic control events may be replayed out of order. Never let
      // an older control event restore a previous live preview stream.
      if (event.event_seq > 0 && event.event_seq < state.lastSeq) return next;
      const segments = { ...state.segments };
      for (const [key, value] of Object.entries(segments))
        if (!value.source_final && value.stream_id !== event.stream_id) delete segments[key];
      return { ...next, activeStream: event.stream_id, segments };
    }
    if (
      event.stream_id &&
      ["stopped", "failed"].includes(event.state || event.status || "")
    ) {
      const segments = { ...state.segments };
      for (const [key, s] of Object.entries(segments))
        if (s.stream_id === event.stream_id && !s.source_final)
          delete segments[key];
      return {
        ...next,
        segments,
        closedStreams: [...state.closedStreams, event.stream_id].slice(-200),
      };
    }
  }
  if (
    !event.sentence_id ||
    !event.stream_id ||
    ![
      "transcript.partial",
      "transcript.final",
      "translation.partial",
      "translation.final",
      "segment.updated",
    ].includes(event.type)
  )
    return next;
  const key = identity({
    stream_id: event.stream_id,
    sentence_id: event.sentence_id,
  });
  const old = state.segments[key];
  if (event.type.endsWith(".partial") && !event.source_status && state.activeStream && event.stream_id !== state.activeStream)
    return next;
  if (event.preview_source_text !== undefined && old?.source_final) return next;
  const revision = event.source_revision || 1;
  if (old && revision < old.source_revision) return next;
  // A larger provisional revision is still provisional. Only a stable source
  // revision may replace a final caption (including its streamed translation).
  if (
    old?.source_final &&
    (event.type === "transcript.partial" ||
      (event.type === "translation.partial" &&
        revision > old.source_revision &&
        event.source_status !== "final"))
  )
    return next;
  if (
    event.type.endsWith(".partial") &&
    state.closedStreams.includes(event.stream_id) &&
    !event.source_status
  )
    return next;
  const value: Segment =
    old && revision === old.source_revision
      ? { ...old }
      : {
          sentence_id: event.sentence_id,
          stream_id: event.stream_id,
          source_revision: revision,
          translation_revision: 0,
          start_ms: event.start_ms ?? old?.start_ms ?? 0,
          end_ms: event.end_ms ?? old?.end_ms ?? 0,
          text: "",
          translation: "",
          status: "partial",
          mode: event.mode || "demo",
        };
  // Preserve only a completed result for an explicitly identified source prefix.
  // A rewritten prefix immediately drops it; never freeze a Chinese character LCP.
  if (event.type === "transcript.partial" && old && revision > old.source_revision &&
      old.preview_complete && old.preview_source_text &&
      event.stable_preview !== undefined && event.text?.startsWith(old.preview_source_text)) {
    value.translation = old.translation;
    value.preview_source_text = old.preview_source_text;
    value.preview_complete = true;
  }
  if (event.status === "retired")
    return {
      ...next,
      segments: {
        ...state.segments,
        [key]: { ...value, status: "retired", source_final: true },
      },
    };
  if (old?.status === "retired" && revision === old.source_revision)
    return next;
  if (
    event.type.startsWith("transcript.") ||
    event.type === "segment.updated"
  ) {
    if (event.type === "transcript.partial" && value.source_final) return next;
    if (event.event_seq && event.event_seq < (value.source_event_seq || 0))
      return next;
    if (event.text !== undefined) value.text = event.text;
    if (event.type === "transcript.partial") {
      const stable = event.stable_preview;
      if (stable !== undefined && value.text.startsWith(stable) &&
          stable + (event.unstable_tail || "") === value.text) {
        value.stable_preview = stable;
        value.unstable_tail = event.unstable_tail;
        value.hypothesis_revision = event.hypothesis_revision;
      } else {
        value.stable_preview = undefined;
        value.unstable_tail = undefined;
      }
    } else {
      value.source_final = true;
      value.stable_preview = undefined;
      value.unstable_tail = undefined;
      value.preview_source_text = undefined;
      value.preview_request_id = undefined;
      value.preview_complete = undefined;
    }
    value.source_event_seq = event.event_seq || value.source_event_seq;
  }
  if (
    event.type.startsWith("translation.") ||
    (event.type === "segment.updated" && event.translation !== undefined)
  ) {
    const tr = event.translation_revision || 1;
    const preview = event.preview_source_text !== undefined;
    if (preview && (!value.text || !value.text.startsWith(event.preview_source_text!) ||
        (event.preview_request_id || 0) < (value.preview_request_id || 0))) return next;
    const replacementPreview = preview && (event.preview_request_id || 0) > (value.preview_request_id || 0);
    if (preview && value.preview_complete && !replacementPreview &&
        event.preview_request_id === value.preview_request_id && !event.preview_complete) return next;
    if (
      tr < value.translation_revision ||
      (value.translation_final && event.type === "translation.partial")
    )
      return next;
    if (event.event_seq && event.event_seq < (value.translation_event_seq || 0))
      return next;
    if (
      event.type === "translation.partial" &&
      !replacementPreview &&
      tr === value.translation_revision &&
      (event.translation?.length || 0) < value.translation.length
    )
      return next;
    value.translation_revision = tr;
    if (event.translation !== undefined) value.translation = event.translation;
    if (preview) {
      value.preview_source_text = event.preview_source_text;
      value.preview_request_id = event.preview_request_id;
      value.preview_complete = !!event.preview_complete;
    } else {
      value.preview_source_text = undefined;
      value.preview_request_id = undefined;
      value.preview_complete = undefined;
    }
    if (event.type !== "translation.partial") value.translation_final = true;
    value.translation_event_seq =
      event.event_seq || value.translation_event_seq;
    if (event.source_status === "final") value.source_final = true;
    if (event.text && !value.text) value.text = event.text;
  }
  value.start_ms = event.start_ms ?? value.start_ms;
  if (event.provenance) value.provenance = event.provenance;
  if (event.latency) value.latency = { ...value.latency, ...event.latency };
  value.speaker = event.speaker ?? value.speaker;
  value.end_ms = event.end_ms ?? value.end_ms;
  value.status = value.translation_final
    ? "final"
    : value.source_final
      ? "translating"
      : "partial";
  return { ...next, segments: { ...state.segments, [key]: value } };
}
export function orderedSegments(state: TranscriptState): Segment[] {
  return Object.values(state.segments)
    .filter((s) => s.status !== "retired")
    .sort(
      (a, b) =>
        a.start_ms - b.start_ms ||
        a.end_ms - b.end_ms ||
        identity(a).localeCompare(identity(b)),
    );
}
