import type { BridgeEvent, Segment } from "./types";
export interface TranscriptState {
  sessionId: string;
  segments: Record<string, Segment>;
  seen: string[];
  lastSeq: number;
  clearedSeq: number;
  closedStreams: string[];
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
  if (event.type === "segment.suggestion") {
    if (!event.stream_id || !event.sentence_id) return next;
    const key = identity({
      stream_id: event.stream_id,
      sentence_id: event.sentence_id,
    });
    const old = state.segments[key];
    if (
      !old ||
      !old.source_final ||
      old.status === "retired" ||
      old.source_revision !== event.source_revision ||
      (event.event_seq > 0 && event.event_seq < (old.suggestion_event_seq || 0))
    )
      return next;
    return {
      ...next,
      segments: {
        ...state.segments,
        [key]: {
          ...old,
          suggestion: event.suggestion,
          suggestion_event_seq: event.event_seq || old.suggestion_event_seq,
        },
      },
    };
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
    if (event.type !== "transcript.partial") value.source_final = true;
    value.source_event_seq = event.event_seq || value.source_event_seq;
  }
  if (
    event.type.startsWith("translation.") ||
    (event.type === "segment.updated" && event.translation !== undefined)
  ) {
    const tr = event.translation_revision || 1;
    if (
      tr < value.translation_revision ||
      (value.translation_final && event.type === "translation.partial")
    )
      return next;
    if (event.event_seq && event.event_seq < (value.translation_event_seq || 0))
      return next;
    if (
      event.type === "translation.partial" &&
      tr === value.translation_revision &&
      (event.translation?.length || 0) < value.translation.length
    )
      return next;
    value.translation_revision = tr;
    if (event.translation !== undefined) value.translation = event.translation;
    if (event.type !== "translation.partial") value.translation_final = true;
    value.translation_event_seq =
      event.event_seq || value.translation_event_seq;
    if (event.source_status === "final") value.source_final = true;
    if (event.text && !value.text) value.text = event.text;
  }
  value.start_ms = event.start_ms ?? value.start_ms;
  if (
    event.type === "segment.updated" &&
    event.suggestion !== undefined &&
    (event.snapshot_seq || 0) >= (value.suggestion_event_seq || 0)
  ) {
    value.suggestion = event.suggestion;
    value.suggestion_event_seq =
      event.snapshot_seq || value.suggestion_event_seq;
  }
  if (event.provenance) value.provenance = event.provenance;
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
