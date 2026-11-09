import assert from "node:assert/strict";
import { test } from "node:test";
import { applyEvent, initialTranscript, orderedSegments } from "../src/lib/events.ts";
import type { BridgeEvent } from "../src/lib/types.ts";

function e(type: string, fields: Partial<BridgeEvent> = {}): BridgeEvent {
  return { type, session_id: "lesson", stream_id: "stream", sentence_id: "1",
    source_revision: 1, translation_revision: 1, event_id: crypto.randomUUID(),
    event_seq: 0, start_ms: 0, end_ms: 1000, mode: "real", ...fields };
}
const source = "오늘은 RAG 공부합니다.";

test("equivalent preview preserves view references but consumes event identity", () => {
  let s = applyEvent(applyEvent(initialTranscript("lesson"), partial()), preview());
  const before=s.translations;
  const repeated=preview();s=applyEvent(s,repeated);
  assert.equal(s.translations,before);
  assert.ok(s.seen.includes(repeated.event_id));
});

test("short replacement tokens retain compatible completed preview until complete", () => {
  let s = applyEvent(applyEvent(initialTranscript("lesson"), partial()), preview());
  s=applyEvent(s,preview({preview_request_id:2,preview_complete:false,translation:"今"}));
  assert.equal(orderedSegments(s)[0].translation,"今天学习 RAG。");
  s=applyEvent(s,preview({preview_request_id:1,translation:"迟到旧请求"}));
  assert.equal(orderedSegments(s)[0].translation,"今天学习 RAG。");
  s=applyEvent(s,preview({preview_request_id:2,preview_complete:true,translation:"新译"}));
  assert.equal(orderedSegments(s)[0].translation,"新译");
});

test("timestamp revisions retain an in-flight prefix, while real rewrite hides it", () => {
  let s=applyEvent(applyEvent(initialTranscript('lesson'),partial()),preview({preview_complete:false}));
  for(let i=2;i<=20;i++){
    s=applyEvent(s,partial({source_revision:i,end_ms:i*100}));
    assert.equal(orderedSegments(s)[0].translation,'今天学习 RAG。');
  }
  s=applyEvent(s,partial({source_revision:21,text:'어제는 다른 내용을 배웠습니다.'}));
  assert.equal(orderedSegments(s)[0].translation,'');
  s=applyEvent(s,preview({source_revision:20,preview_complete:true}));
  assert.equal(orderedSegments(s)[0].translation,'');
});

test("identical text must still advance final status and replay sequence", () => {
  let s=applyEvent(initialTranscript('lesson'),e('transcript.final',{text:source,event_seq:1}));
  const sources=s.sources;
  s=applyEvent(s,e('translation.partial',{translation:'same',source_status:'final',event_seq:2}));
  s=applyEvent(s,e('translation.partial',{translation:'same',source_status:'final',event_seq:3}));
  assert.equal(s.lastSeq,3);assert.equal(s.translations['stream:1'].translation_event_seq,3);
  s=applyEvent(s,e('translation.final',{translation:'same',event_seq:4}));
  assert.equal(orderedSegments(s)[0].translation_final,true);
  s=applyEvent(s,e('processing.failed',{task_kind:'translate',message:'late',event_seq:5}));
  assert.equal(s.lastSeq,5);assert.equal(orderedSegments(s)[0].translation_final,true);
  assert.equal(s.sources,sources);
});

test("future preview and its fallback stay hidden until the source revision arrives", () => {
  let s=applyEvent(initialTranscript('lesson'),partial());
  s=applyEvent(s,preview({source_revision:3,preview_request_id:3}));
  assert.equal(orderedSegments(s)[0].translation,'');
  s=applyEvent(s,preview({source_revision:3,preview_request_id:4,preview_complete:false,translation:'今'}));
  assert.equal(orderedSegments(s)[0].translation,'');
  s=applyEvent(s,partial({source_revision:3}));
  assert.equal(orderedSegments(s)[0].translation,'今天学习 RAG。');
});
function partial(fields: Partial<BridgeEvent> = {}) {
  return e("transcript.partial", { text: source, stable_preview: "오늘은 RAG ",
    unstable_tail: "공부합니다.", hypothesis_revision: 2, ...fields });
}
function preview(fields: Partial<BridgeEvent> = {}) {
  return e("translation.partial", { translation: "今天学习 RAG。", preview_source_text: "오늘은 RAG",
    preview_request_id: 1, preview_complete: true, ...fields });
}

test("stable prefix is reversible and never a formal source; old schema still works", () => {
  let s = applyEvent(initialTranscript("lesson"), partial());
  assert.equal(orderedSegments(s)[0].source_final, false);
  s = applyEvent(s, partial({ source_revision: 2, text: "오늘은 AI 배워요.",
    stable_preview: "오늘은 ", unstable_tail: "AI 배워요." }));
  assert.equal(orderedSegments(s)[0].stable_preview, "오늘은 ");
  s = applyEvent(s, e("transcript.final", { source_revision: 3, text: "오늘은 AI 배워요.", event_seq: 5 }));
  assert.equal(orderedSegments(s)[0].stable_preview, undefined);
  assert.equal(orderedSegments(s)[0].source_final, true);
  const old = applyEvent(initialTranscript("lesson"), e("transcript.partial", { text: "legacy" }));
  assert.equal(orderedSegments(old)[0].text, "legacy");
});

test("only completed compatible prefix translations survive a growing tail", () => {
  let s = applyEvent(applyEvent(initialTranscript("lesson"), partial()), preview());
  s = applyEvent(s, partial({ source_revision: 2, text: source + " 다음은", unstable_tail: "공부합니다. 다음은" }));
  assert.equal(orderedSegments(s)[0].translation, "今天学习 RAG。");
  assert.equal(orderedSegments(s)[0].translation_final, false);
  s = applyEvent(s, partial({ source_revision: 3, text: "어제는 AI 공부", stable_preview: "", unstable_tail: "어제는 AI 공부" }));
  assert.equal(orderedSegments(s)[0].translation, "");
  s = applyEvent(s, preview({ source_revision: 2, translation: "过时版本" }));
  assert.equal(orderedSegments(s)[0].translation, "");
});

test("new preview may replace Chinese with shorter text; old request and late tokens lose", () => {
  let s = applyEvent(applyEvent(initialTranscript("lesson"), partial()), preview());
  s = applyEvent(s, preview({ preview_request_id: 2, translation: "新译文" }));
  assert.equal(orderedSegments(s)[0].translation, "新译文");
  s = applyEvent(s, preview({ preview_request_id: 1, translation: "迟到旧请求很长" }));
  s = applyEvent(s, preview({ preview_request_id: 2, translation: "新译文追加乱序", preview_complete: false }));
  assert.equal(orderedSegments(s)[0].translation, "新译文");
  s = applyEvent(s, e("transcript.final", { source_revision: 2, text: source, event_seq: 1 }));
  s = applyEvent(s, e("translation.final", { source_revision: 2, translation: "正式中文", event_seq: 2 }));
  s = applyEvent(s, preview({ source_revision: 2, preview_request_id: 100, translation: "不得覆盖" }));
  assert.equal(orderedSegments(s)[0].translation, "正式中文");
});

test("reconnect retires old previews but still accepts durable historic final translations", () => {
  let s = applyEvent(initialTranscript("lesson"), e("session.state", { state: "recording", event_seq: 1 }));
  s = applyEvent(s, partial());
  s = applyEvent(s, e("session.state", { stream_id: "new", state: "recording", event_seq: 10 }));
  s = applyEvent(s, partial());
  assert.equal(orderedSegments(s).length, 1);
  assert.equal(orderedSegments(s)[0].source_status, "interrupted");
  s = applyEvent(s, e("transcript.final", { text: source, source_revision: 2, event_seq: 11 }));
  s = applyEvent(s, e("translation.partial", { source_revision: 2, source_status: "final", translation: "后台正式任务", event_seq: 12 }));
  assert.equal(orderedSegments(s)[0].translation, "后台正式任务");
  const duplicate = e("session.state", { state: "recording", event_seq: 1 });
  assert.equal(applyEvent(s, duplicate).activeStream, "new");
});

test("mismatched preview is ignored and real/demo provenance is retained", () => {
  let s = applyEvent(initialTranscript("lesson"), partial());
  s = applyEvent(s, preview({ preview_source_text: "unrelated", translation: "错误" }));
  assert.equal(orderedSegments(s)[0].translation, "");
  assert.equal(orderedSegments(s)[0].mode, "real");
  s = applyEvent(s, partial({ sentence_id: "demo", mode: "demo" }));
  assert.deepEqual(new Set(orderedSegments(s).map(v => v.mode)), new Set(["real", "demo"]));
});
