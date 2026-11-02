import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToString } from "react-dom/server";
import { applyEvent, initialTranscript, orderedSegments } from "../src/lib/events.ts";
import { CorrectionCard } from "../src/components/CorrectionCard.tsx";
import type { BridgeEvent, CorrectionSuggestion } from "../src/lib/types.ts";

const suggestion: CorrectionSuggestion = {
  task_id: "task", source_revision: 1, status: "unconfirmed", audio_verified: false,
  suggested_text: "작업기억", edits: [{ before: "작업 기역", after: "작업기억", kind: "term", reason: "术语相近，待确认", evidence_ids: ["term:0"] }],
  evidence: [{ id: "term:0", kind: "term", quote: "작업기억" }],
};
const event = (type: string, seq: number, extra: Partial<BridgeEvent> = {}): BridgeEvent => ({
  type, event_id: `${type}:${seq}:${JSON.stringify(extra)}`, event_seq: seq, session_id: "lesson", stream_id: "stream",
  sentence_id: "sentence", source_revision: 1, ...extra,
});
test("suggestions never replace captions; late results and stale snapshots cannot revive dismissed suggestions", () => {
  let state = applyEvent(initialTranscript("lesson"), event("transcript.final", 1, { text: "작업 기역" }));
  state = applyEvent(state, event("segment.suggestion", 2, { suggestion }));
  assert.equal(orderedSegments(state)[0].text, "작업 기역");
  assert.equal(orderedSegments(state)[0].suggestion?.task_id, "task");
  state = applyEvent(state, event("segment.suggestion", 4, { suggestion: null }));
  state = applyEvent(state, event("segment.suggestion", 3, { suggestion }));
  state = applyEvent(state, event("segment.updated", 0, { snapshot_seq: 2, suggestion }));
  assert.equal(orderedSegments(state)[0].suggestion, null);
  state = applyEvent(state, event("transcript.final", 5, { source_revision: 2, text: "校正后的新原文" }));
  state = applyEvent(state, event("segment.suggestion", 6, { suggestion }));
  assert.equal(orderedSegments(state)[0].suggestion, undefined);
  assert.equal(orderedSegments(state)[0].text, "校正后的新原文");
});
test("a fresh HTTP snapshot recovers a suggestion without replaying ephemeral audio", () => {
  let state = applyEvent(initialTranscript("lesson"), event("transcript.final", 1, { text: "작업 기역" }));
  state = applyEvent(state, event("segment.updated", 0, { snapshot_seq: 2, suggestion }));
  assert.equal(orderedSegments(state)[0].suggestion?.task_id, "task");
  state = applyEvent(state, event("segment.updated", 0, { snapshot_seq: 4, suggestion: null }));
  assert.equal(orderedSegments(state)[0].suggestion, null);
});
test("correction card labels textual inference and disables acceptance during capture", () => {
  const html = renderToString(React.createElement(CorrectionCard, { suggestion, sessionId: "lesson", active: true,
    saved() {}, notify() {}, jump() {} }));
  assert.ok(html.includes("推测校正 · 待确认"));
  assert.ok(html.includes("尚未通过音频核实"));
  assert.ok(html.includes("停止录音后可采纳"));
  assert.ok(html.includes('disabled=""'));
  assert.ok(html.includes("查看改动与依据"));
});
