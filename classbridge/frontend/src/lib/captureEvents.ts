import type { BridgeEvent } from "./types";

// Persistent replay and current microphone control are separate concerns.
// Keep the request identity through stop/drain until its terminal event arrives.
export function isCurrentCaptureEvent(
  event: BridgeEvent,
  requestId: string | null,
  streamId: string | null,
  afterSeq: number,
): boolean {
  if (!requestId || event.recovered || event.task_kind) return false;
  if (event.event_seq > 0 && event.event_seq <= afterSeq) return false;
  if (event.request_id)
    return (
      event.request_id === requestId &&
      (!streamId || !event.stream_id || event.stream_id === streamId)
    );
  // Compatibility with older servers is safe only after the stream is known.
  return !!streamId && event.stream_id === streamId;
}
