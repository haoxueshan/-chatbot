import assert from "node:assert/strict";
import { test } from "node:test";
import {
  applyEvent,
  initialTranscript,
  orderedSegments,
} from "../src/lib/events.ts";
import type { BridgeEvent } from "../src/lib/types.ts";

const event = (
  type: string,
  values: Partial<BridgeEvent> = {},
): BridgeEvent => ({
  type,
  event_id: crypto.randomUUID(),
  event_seq: 0,
  session_id: "session",
  stream_id: "stream",
  sentence_id: "1",
  source_revision: 1,
  translation_revision: 1,
  text: "source",
  start_ms: 0,
  end_ms: 1000,
  mode: "demo",
  ...values,
});
test("duplicates, late partials and old translations cannot overwrite a final version", () => {
  let state = initialTranscript("session");
  const original = event("transcript.final", {
    source_revision: 2,
    event_seq: 3,
  });
  state = applyEvent(state, original);
  assert.equal(applyEvent(state, original), state);
  state = applyEvent(
    state,
    event("translation.final", {
      source_revision: 2,
      translation: "最终译文",
      event_seq: 4,
    }),
  );
  state = applyEvent(
    state,
    event("transcript.partial", { source_revision: 1, text: "old" }),
  );
  state = applyEvent(
    state,
    event("translation.partial", {
      source_revision: 2,
      translation_revision: 4,
      translation: "迟到",
    }),
  );
  state = applyEvent(
    state,
    event("translation.final", { source_revision: 1, translation: "旧任务" }),
  );
  assert.equal(orderedSegments(state)[0].translation, "最终译文");
  assert.equal(orderedSegments(state)[0].source_final, true);
});
test("source revision change invalidates its old translation", () => {
  let state = applyEvent(
    initialTranscript("session"),
    event("translation.final", { translation: "old" }),
  );
  state = applyEvent(
    state,
    event("transcript.final", { source_revision: 2, text: "corrected" }),
  );
  assert.equal(orderedSegments(state)[0].translation, "");
  assert.equal(orderedSegments(state)[0].text, "corrected");
});
test("higher-numbered provisional text cannot demote a stable sentence", () => {
  let state = applyEvent(
    initialTranscript("session"),
    event("transcript.final", { event_seq: 3 }),
  );
  state = applyEvent(
    state,
    event("translation.final", { translation: "稳定译文", event_seq: 4 }),
  );
  state = applyEvent(
    state,
    event("transcript.partial", {
      source_revision: 10,
      text: "迟到的中间原文",
    }),
  );
  state = applyEvent(
    state,
    event("translation.partial", {
      source_revision: 11,
      translation: "临时译文",
    }),
  );
  assert.equal(orderedSegments(state)[0].text, "source");
  assert.equal(orderedSegments(state)[0].translation, "稳定译文");
  assert.equal(orderedSegments(state)[0].source_revision, 1);
  // A real new final version and its final-source streaming translation remain allowed.
  state = applyEvent(
    state,
    event("translation.partial", {
      source_revision: 2,
      source_status: "final",
      text: "new source",
      translation: "新",
    }),
  );
  assert.equal(orderedSegments(state)[0].source_revision, 2);
  assert.equal(orderedSegments(state)[0].source_final, true);
});
test("different streams may reuse the upstream sentence number without collision", () => {
  let state = applyEvent(
    initialTranscript("session"),
    event("transcript.final"),
  );
  state = applyEvent(
    state,
    event("transcript.final", { stream_id: "second-stream", text: "second" }),
  );
  assert.equal(orderedSegments(state).length, 2);
  assert.equal(
    applyEvent(
      state,
      event("transcript.final", { session_id: "private-other" }),
    ),
    state,
  );
});
test("retirement tombstone and clear cursor survive out-of-order replay", () => {
  let state = applyEvent(
    initialTranscript("session"),
    event("transcript.final", { event_seq: 1 }),
  );
  state = applyEvent(
    state,
    event("segment.updated", {
      status: "retired",
      source_revision: 2,
      event_seq: 3,
    }),
  );
  state = applyEvent(
    state,
    event("transcript.final", { source_revision: 1, event_seq: 2 }),
  );
  assert.equal(orderedSegments(state).length, 0);
  state = applyEvent(
    state,
    event("session.state", { cleared: true, event_seq: 4 }),
  );
  state = applyEvent(
    state,
    event("transcript.final", { stream_id: "older", event_seq: 2 }),
  );
  assert.equal(orderedSegments(state).length, 0);
});
test("stopping removes provisional captions; stable final translations may finish", () => {
  let state = applyEvent(
    initialTranscript("session"),
    event("transcript.partial"),
  );
  state = applyEvent(
    state,
    event("session.state", { state: "stopped", event_seq: 2 }),
  );
  state = applyEvent(
    state,
    event("transcript.partial", { source_revision: 2 }),
  );
  assert.equal(orderedSegments(state).length, 0);
  state = applyEvent(
    state,
    event("transcript.final", { source_revision: 3, event_seq: 3 }),
  );
  state = applyEvent(
    state,
    event("translation.partial", {
      source_revision: 3,
      source_status: "final",
      translation: "中文",
      event_seq: 4,
    }),
  );
  assert.equal(orderedSegments(state)[0].source_final, true);
  assert.equal(orderedSegments(state)[0].translation, "中文");
});
test("out-of-order same-version partial tokens cannot shrink accumulated translation", () => {
  let state = applyEvent(
    initialTranscript("session"),
    event("transcript.final"),
  );
  state = applyEvent(
    state,
    event("translation.partial", { translation: "完整内容", event_seq: 5 }),
  );
  state = applyEvent(
    state,
    event("translation.partial", { translation: "完整", event_seq: 4 }),
  );
  assert.equal(orderedSegments(state)[0].translation, "完整内容");
});
