import assert from "node:assert/strict";
import { test } from "node:test";
import { buildTimeline } from "../src/lib/timeline.ts";
import type { BridgeEvent, Segment } from "../src/lib/types.ts";

test("old gaps remain before resumed captions so following reaches the latest subtitle", () => {
  const segments = [
    { start_ms: 1_824_800, stream_id: "new", sentence_id: "1" },
    { start_ms: 1_830_000, stream_id: "new", sentence_id: "2" },
  ] as Segment[];
  const gaps = [
    { event_id: "overflow", start_ms: 1_816_900 },
    { event_id: "pause", start_ms: 14_000, end_ms: 1_814_000 },
    { event_id: "resume", start_ms: 1_816_950, end_ms: 1_824_437 },
  ] as BridgeEvent[];
  const items = buildTimeline(segments, gaps);
  assert.deepEqual(items.map((x) => x.key), ["gap:pause", "gap:overflow", "gap:resume", "segment:new:1", "segment:new:2"]);
  assert.equal(items.at(-1)?.kind, "segment");
  assert.equal(segments[0].start_ms, 1_824_800); // Evidence offsets remain unchanged.
});

test("gaps with the same timestamp precede the new segment and remain visible", () => {
  const items = buildTimeline(
    [{ start_ms: 0, stream_id: "new", sentence_id: "0" }] as Segment[],
    [{ event_id: "unknown" }] as BridgeEvent[],
  );
  assert.deepEqual(items.map((x) => x.kind), ["gap", "segment"]);
});
