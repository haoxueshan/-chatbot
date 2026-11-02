import type { BridgeEvent, Segment } from "./types";

export type TimelineEntry =
  | { kind: "segment"; time: number; key: string; segment: Segment }
  | { kind: "gap"; time: number; key: string; gap: BridgeEvent };

export function buildTimeline(segments: Segment[], gaps: BridgeEvent[]): TimelineEntry[] {
  const items: TimelineEntry[] = [
    ...segments.map((segment): TimelineEntry => ({
      kind: "segment", time: segment.start_ms, key: `segment:${segment.stream_id}:${segment.sentence_id}`, segment,
    })),
    ...gaps.map((gap, index): TimelineEntry => ({
      kind: "gap", time: gap.start_ms ?? gap.end_ms ?? 0, key: `gap:${gap.event_id || index}`, gap,
    })),
  ];
  return items.sort((a, b) => a.time - b.time || (a.kind === b.kind ? 0 : a.kind === "gap" ? -1 : 1));
}
