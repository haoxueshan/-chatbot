import assert from "node:assert/strict";
import { test } from "node:test";
import { applyEvent, initialTranscript, orderedSegments } from "../src/lib/events.ts";
import { translationLanguages, parseTranslationTerms, formatTranslationTerms } from "../src/lib/translationLanguages.ts";
import type { TargetLanguage } from "../src/lib/translationLanguages.ts";
import type { BridgeEvent } from "../src/lib/types.ts";

const event = (type: string, values: Partial<BridgeEvent> = {}): BridgeEvent => ({
  type, event_id: crypto.randomUUID(), event_seq: 0, session_id: "lesson", stream_id: "s", sentence_id: "1",
  source_revision: 1, translation_revision: 1, start_ms: 0, end_ms: 1000, mode: "real", ...values,
});

test("14 targets share the backend registry; source is immediate and translation cannot rewrite it", () => {
  assert.equal(Object.keys(translationLanguages).length, 14);
  for (const code of Object.keys(translationLanguages) as TargetLanguage[]) {
    let state = initialTranscript("lesson", [], [], code);
    state = applyEvent(state, event("transcript.partial", { text: "작업기억 working memory" }));
    assert.equal(orderedSegments(state)[0].text, "작업기억 working memory");
    assert.equal(orderedSegments(state)[0].translation, "");
    const sources = state.sources;
    state = applyEvent(state, event("translation.partial", { translation: "preview", target_language: code, text: "must not replace source" }));
    assert.equal(state.sources, sources);
    assert.equal(orderedSegments(state)[0].translation, "preview");
    state = applyEvent(state, event("transcript.final", { text: "작업기억 working memory", event_seq: 1 }));
    state = applyEvent(state, event("translation.final", { translation: "final", target_language: code, event_seq: 2 }));
    assert.equal(orderedSegments(state)[0].translation, "final");
    assert.equal(orderedSegments(state)[0].target_language, code);
  }
});

test("wrong-language previews, finals, failures and old untagged events cannot replace an English translation", () => {
  let state = initialTranscript("lesson", [], [], "en");
  state = applyEvent(state, event("transcript.final", { text: "한국어 원문" }));
  state = applyEvent(state, event("translation.final", { translation: "English final", target_language: "en" }));
  const sources=state.sources, translations=state.translations;
  for (const target_language of ["zh-CN", "ja", undefined] as const) {
    for (const type of ["translation.partial", "translation.final", "processing.failed"]) {
      state = applyEvent(state, event(type, { translation: "wrong language", target_language,
        source_revision: 99, translation_revision: 99, task_kind: "translate", message: "late failure" }));
      assert.equal(state.sources,sources);
      assert.equal(state.translations,translations);
    }
  }
  assert.equal(orderedSegments(state)[0].translation,"English final");
});

test("refresh uses persisted language; legacy untagged Chinese only restores in Chinese sessions", () => {
  const snapshot:any={stream_id:"s",sentence_id:"1",text:"한국어",translation:"日本語",source_revision:2,
    translation_revision:1,start_ms:0,end_ms:1000,mode:"real",status:"final",target_language:"ja"};
  let state=initialTranscript("lesson",[snapshot],[],"ja");
  assert.equal(orderedSegments(state)[0].translation,"日本語");
  state=initialTranscript("lesson",[snapshot],[],"en");
  assert.equal(orderedSegments(state)[0].text,"한국어");
  assert.equal(orderedSegments(state)[0].translation,"");
  const legacy={...snapshot,target_language:undefined,translation:"中文历史"};
  assert.equal(orderedSegments(initialTranscript("lesson",[legacy]))[0].translation,"中文历史");
  assert.equal(orderedSegments(initialTranscript("lesson",[legacy],[],"en"))[0].translation,"");
});

test("term editor preserves explicit target labels and rejects unknown codes", () => {
  const terms=["인지심리학",{source:"memory",target:"记忆"},{source:"기억",target:"memory",target_language:"en"}];
  assert.deepEqual(parseTranslationTerms(formatTranslationTerms(terms)),terms);
  assert.throws(()=>parseTranslationTerms("[xx] source = target"),/语言/);
  assert.throws(()=>parseTranslationTerms("[__proto__] source = target"),/语言/);
});
