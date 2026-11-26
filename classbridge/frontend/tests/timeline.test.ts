import assert from "node:assert/strict";
import { test } from "node:test";
import { buildTimeline, incidentLabel } from "../src/lib/timeline.ts";
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

test("incident rows group only matching incidents and retain uncertainty and missing evidence",()=>{
  const gaps=[
    {event_id:'a',session_id:'s',incident_id:'one',gap_kind:'audio_missing',missing_audio_ms:20,start_ms:100},
    {event_id:'b',session_id:'s',incident_id:'one',gap_kind:'asr_result_uncertain',start_ms:200},
    {event_id:'c',session_id:'s',incident_id:'two',gap_kind:'user_paused',start_ms:300},
    {event_id:'d',session_id:'s',gap_kind:'connection_recovered',start_ms:400},
  ] as BridgeEvent[];
  const items=buildTimeline([],gaps);
  assert.equal(items.length,3);
  const first=items[0];assert.equal(first.kind,'gap');
  if(first.kind==='gap'){
    assert.equal(first.related.length,2);assert.equal(first.related[0].missing_audio_ms,20);
    assert.equal(incidentLabel(first.related),'采集缺口');
  }
  assert.equal(incidentLabel([gaps[2]]),'录音暂停');
  assert.match(incidentLabel([gaps[3]]),/音频未确认恢复/);
  assert.equal(gaps.length,4); // No raw evidence is deleted.
});

test("gaps with the same timestamp precede the new segment and remain visible", () => {
  const items = buildTimeline(
    [{ start_ms: 0, stream_id: "new", sentence_id: "0" }] as Segment[],
    [{ event_id: "unknown" }] as BridgeEvent[],
  );
  assert.deepEqual(items.map((x) => x.kind), ["gap", "segment"]);
});
