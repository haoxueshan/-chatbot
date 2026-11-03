import assert from "node:assert/strict";
import { test } from "node:test";
import {
  applyEvent,
  initialTranscript,
  orderedSegments,
} from "../src/lib/events.ts";
import type { BridgeEvent } from "../src/lib/types.ts";
const e = (type: string, fields: Partial<BridgeEvent> = {}): BridgeEvent => ({
  type,
  event_id: crypto.randomUUID(),
  event_seq: 0,
  session_id: "lesson",
  stream_id: "stream",
  sentence_id: "1",
  source_revision: 1,
  start_ms: 100,
  end_ms: 500,
  mode: "real",
  ...fields,
});
const source = (fields: Partial<BridgeEvent> = {}) =>
  e("transcript.partial", { text: "오늘 수업", ...fields });
const view = orderedSegments;

test("source displays immediately; translation touches no source reference or lifecycle", () => {
  let s = applyEvent(initialTranscript("lesson"), source());
  assert.equal(view(s)[0].text, "오늘 수업");
  assert.equal(view(s)[0].translation_status, "pending");
  const original = s.sources;
  s = applyEvent(
    s,
    e("translation.partial", {
      text: "FORGED",
      source_status: "final",
      translation: "今天",
      end_ms: 999,
    }),
  );
  assert.equal(s.sources, original);
  assert.equal(view(s)[0].source_status, "partial");
  assert.equal(view(s)[0].end_ms, 500);
  assert.equal(view(s)[0].translation, "今天");
  s = applyEvent(
    s,
    e("translation.final", { text: "FORGED FINAL", translation: "今天上课" }),
  );
  assert.equal(s.sources, original);
  assert.equal(view(s)[0].text, "오늘 수업");
});
test("translation failure only changes the identified translation, never source", () => {
  let s = applyEvent(
    initialTranscript("lesson"),
    e("transcript.final", { text: "확인된 원문" }),
  );
  const original = s.sources;
  s = applyEvent(
    s,
    e("processing.failed", {
      task_kind: "translate",
      message: "timeout",
      event_seq: 3,
    }),
  );
  assert.equal(s.sources, original);
  assert.equal(view(s)[0].source_status, "final");
  assert.equal(view(s)[0].translation_status, "failed");
  const before = s.translations;
  s = applyEvent(
    s,
    e("processing.failed", { task_kind: "translate", sentence_id: undefined }),
  );
  assert.equal(s.translations, before);
});
test("translation arriving first is bounded invisible metadata until matching source arrives", () => {
  let s = applyEvent(
    initialTranscript("lesson"),
    e("translation.partial", {
      source_status: "final",
      translation: "你好",
      text: "not source",
    }),
  );
  assert.deepEqual(view(s), []);
  assert.deepEqual(s.sources, {});
  s = applyEvent(s, e("transcript.final", { text: "안녕" }));
  assert.equal(view(s)[0].translation, "你好");
  for (let i = 0; i < 250; i++)
    s = applyEvent(
      s,
      e("translation.final", {
        sentence_id: String(i + 2),
        translation: "orphan",
      }),
    );
  assert.equal(Object.keys(s.translations).length, 201);
  assert.equal(view(s).length, 1);
});
test("ASR may shorten a partial and keeps only one previous diagnostic; old versions lose", () => {
  let s = applyEvent(
    initialTranscript("lesson"),
    source({ text: "오늘은 인공지능을 공부합니다." }),
  );
  s = applyEvent(s, source({ source_revision: 2, text: "오늘은 인공지능" }));
  assert.equal(view(s)[0].text, "오늘은 인공지능");
  assert.equal(s.sources["stream:1"].previous_partial?.revision, 1);
  s = applyEvent(s, source({ source_revision: 1, text: "old" }));
  assert.equal(view(s)[0].source_revision, 2);
  const translations = s.translations;
  s = applyEvent(s, source({ source_revision: 3, text: "오늘" }));
  assert.equal(s.translations, translations);
  assert.equal(s.sources["stream:1"].previous_partial?.revision, 2);
});
test("final v4 survives partial v5, arbitrary translation tokens and old finals", () => {
  let s = applyEvent(
    initialTranscript("lesson"),
    e("transcript.final", {
      source_revision: 4,
      text: "공식 원문",
      event_seq: 10,
    }),
  );
  const sources = s.sources;
  s = applyEvent(s, source({ source_revision: 5, text: "late" }));
  s = applyEvent(
    s,
    e("transcript.final", { source_revision: 3, text: "old", event_seq: 9 }),
  );
  for (let i = 0; i < 10; i++)
    s = applyEvent(
      s,
      e("translation.partial", {
        source_revision: 4,
        source_status: "final",
        translation: "中".repeat(i + 1),
        event_seq: 11 + i,
      }),
    );
  assert.equal(s.sources, sources);
  assert.equal(view(s)[0].text, "공식 원문");
});
test("interrupted retains text on stop and a later final replaces it without duplicates", () => {
  let s = applyEvent(initialTranscript("lesson"), source());
  s = applyEvent(
    s,
    e("transcript.interrupted", {
      text: "오늘 수업",
      source_status: "interrupted",
      event_seq: 2,
    }),
  );
  s = applyEvent(s, e("session.state", { state: "stopped", event_seq: 3 }));
  assert.equal(view(s)[0].source_status, "interrupted");
  assert.equal(view(s)[0].source_final, false);
  s = applyEvent(
    s,
    e("transcript.final", {
      text: "오늘 수업입니다.",
      source_revision: 2,
      event_seq: 4,
    }),
  );
  assert.equal(view(s).length, 1);
  assert.equal(view(s)[0].source_status, "final");
  s = applyEvent(
    s,
    e("transcript.interrupted", {
      text: "old",
      source_revision: 3,
      event_seq: 5,
    }),
  );
  assert.equal(view(s)[0].text, "오늘 수업입니다.");
});
test("old translations cannot attach to new source; compatible completed prefixes stay provisional", () => {
  let s = applyEvent(
    initialTranscript("lesson"),
    source({ stable_preview: "오늘", unstable_tail: " 수업" }),
  );
  s = applyEvent(
    s,
    e("translation.partial", {
      translation: "今天",
      preview_source_text: "오늘",
      preview_request_id: 2,
      preview_complete: true,
    }),
  );
  s = applyEvent(
    s,
    source({
      source_revision: 5,
      text: "오늘 수업입니다",
      stable_preview: "오늘 수업",
      unstable_tail: "입니다",
    }),
  );
  assert.equal(view(s)[0].translation, "今天");
  assert.equal(view(s)[0].translation_final, false);
  const sources = s.sources;
  s = applyEvent(
    s,
    e("translation.final", { source_revision: 3, translation: "过期" }),
  );
  assert.equal(s.sources, sources);
  assert.equal(view(s)[0].translation, "今天");
  s = applyEvent(
    s,
    source({
      source_revision: 6,
      text: "어제 수업",
      stable_preview: "어제",
      unstable_tail: " 수업",
    }),
  );
  assert.equal(view(s)[0].translation, "");
});
test("stream identity, deduplication, sequence and ownership survive replay", () => {
  const first = e("transcript.final", { text: "A", event_seq: 3 });
  let s = applyEvent(initialTranscript("lesson"), first);
  assert.equal(applyEvent(s, first), s);
  s = applyEvent(
    s,
    e("transcript.final", { stream_id: "B", text: "B", event_seq: 4 }),
  );
  s = applyEvent(s, e("transcript.final", { text: "stale", event_seq: 2 }));
  assert.deepEqual(
    view(s).map((x) => x.text),
    ["B", "A"],
  ); // equal timestamps, identity sorting
  const before = s;
  s = applyEvent(
    s,
    e("transcript.final", { session_id: "private", text: "secret" }),
  );
  assert.equal(s, before);
  // A late MT event with a larger global seq cannot suppress a valid start.
  s = applyEvent(
    s,
    e("translation.final", {
      stream_id: "future",
      event_seq: 100,
      translation: "metadata",
    }),
  );
  s = applyEvent(
    s,
    e("session.state", { stream_id: "new", state: "recording", event_seq: 5 }),
  );
  assert.equal(s.activeStream, "new");
  s = applyEvent(
    s,
    e("session.state", { stream_id: "old", state: "recording", event_seq: 2 }),
  );
  assert.equal(s.activeStream, "new");
});
test("snapshot restoration preserves final and interrupted separately and rejects stale snapshots", () => {
  let s = applyEvent(
    initialTranscript("lesson"),
    e("transcript.final", { text: "final", source_revision: 4, event_seq: 9 }),
  );
  s = applyEvent(
    s,
    e("transcript.interrupted", {
      sentence_id: "2",
      text: "unfinished",
      event_seq: 10,
    }),
  );
  const rows = view(s);
  const restored = initialTranscript(
    "lesson",
    rows.filter((r) => r.source_final),
    rows.filter((r) => !r.source_final),
  );
  assert.deepEqual(
    view(restored).map((r) => [r.text, r.source_status]),
    view(s).map((r) => [r.text, r.source_status]),
  );
  s = applyEvent(
    s,
    e("segment.updated", {
      text: "stale",
      source_revision: 3,
      snapshot_seq: 8,
    }),
  );
  assert.equal(view(s)[0].text, "final");
});
test("clear removes both channels and blocks old source/translation/interrupted snapshots", () => {
  let s = applyEvent(initialTranscript("lesson"), source());
  s = applyEvent(s, e("translation.partial", { translation: "今天" }));
  s = applyEvent(s, e("session.state", { cleared: true, event_seq: 5 }));
  for (const type of [
    "transcript.final",
    "transcript.interrupted",
    "translation.final",
    "segment.updated",
  ])
    s = applyEvent(
      s,
      e(type, {
        text: "old",
        translation: "旧",
        event_seq: 0,
        snapshot_seq: 4,
      }),
    );
  assert.deepEqual(view(s), []);
  assert.deepEqual(s.translations, {});
});

test("late clear preserves newer durable rows but blocks transient and zero-watermark old snapshots", () => {
  let s = applyEvent(
    initialTranscript("lesson"),
    e("transcript.final", { event_seq: 2, text: "old" }),
  );
  s = applyEvent(
    s,
    e("transcript.final", { stream_id: "new", event_seq: 6, text: "new" }),
  );
  s = applyEvent(s, e("session.state", { cleared: true, event_seq: 5 }));
  s = applyEvent(s, source({ text: "late" }));
  s = applyEvent(
    s,
    e("segment.updated", { text: "old snapshot", snapshot_seq: 0 }),
  );
  assert.deepEqual(
    view(s).map((x) => x.text),
    ["new"],
  );
});
test("failed translation and historical provenance survive snapshot hydration", () => {
  const s = initialTranscript("lesson", [
    {
      stream_id: "stream",
      sentence_id: "1",
      source_revision: 2,
      translation_revision: 0,
      text: "人工确认历史",
      translation: "",
      source_status: "final",
      translation_status: "failed",
      translation_error: "timeout",
      status: "translating",
      mode: "real",
      start_ms: 0,
      end_ms: 50,
      provenance: "user_correction",
    },
  ]);
  assert.equal(view(s)[0].translation_status, "failed");
  assert.equal(view(s)[0].source_status, "final");
  assert.equal(view(s)[0].provenance, "user_correction");
});

test("old preview request cannot overwrite newer preview even with a higher source revision", () => {
  let s = applyEvent(
    initialTranscript("lesson"),
    source({ stable_preview: "오늘", unstable_tail: " 수업" }),
  );
  s = applyEvent(
    s,
    e("translation.partial", {
      preview_source_text: "오늘",
      preview_complete: true,
      preview_request_id: 3,
      translation: "今天",
    }),
  );
  s = applyEvent(
    s,
    source({
      source_revision: 2,
      text: "오늘 수업입니다",
      stable_preview: "오늘",
      unstable_tail: " 수업입니다",
    }),
  );
  s = applyEvent(
    s,
    e("translation.partial", {
      source_revision: 2,
      preview_source_text: "오늘",
      preview_request_id: 2,
      translation: "迟到旧请求",
    }),
  );
  assert.equal(view(s)[0].translation, "今天");
  assert.equal(view(s)[0].text, "오늘 수업입니다");
});
