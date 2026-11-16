import assert from "node:assert/strict";
import { test } from "node:test";
import { applyEvent, initialTranscript, orderedSegments } from "../src/lib/events.ts";
import type { BridgeEvent } from "../src/lib/types.ts";
import { translationLanguages, translationDirection, type TargetLanguage } from "../src/lib/translationLanguages.ts";

function e(type: string, fields: Partial<BridgeEvent> = {}): BridgeEvent {
  return { type, session_id: "lesson", stream_id: "stream", sentence_id: "1",
    source_revision: 1, translation_revision: 1, event_id: crypto.randomUUID(),
    event_seq: 0, start_ms: 0, end_ms: 1000, mode: "real", ...fields };
}
const source = "오늘은 RAG 공부합니다.";

test('first request remains streaming; timestamp-only source versions never clear its completed result',()=>{
  let s=applyEvent(initialTranscript('lesson'),partial());
  for (const text of ['今','今天','今天我们学习人工智能。']) {
    s=applyEvent(s,preview({translation:text,preview_complete:false,preview_source_text:source}));
    assert.equal(orderedSegments(s)[0].translation,text);
  }
  s=applyEvent(s,preview({translation:'今天我们学习人工智能。',preview_source_text:source}));
  const translations=s.translations;
  for (let i=2;i<=21;i++) {
    s=applyEvent(s,partial({source_revision:i,start_ms:i,end_ms:1000+i}));
    const segment=orderedSegments(s)[0];
    assert.equal(segment.translation,'今天我们学习人工智能。');
    assert.equal(segment.text,source);
    assert.equal(segment.start_ms,i);
    assert.equal(segment.end_ms,1000+i);
    assert.equal(s.sources['stream:1'].text_revision,1);
    assert.equal(s.translations,translations);
  }
});

for (const language of Object.keys(translationLanguages) as TargetLanguage[]) {
  test(`${language}: 30 seconds of growth buffers replacements and restores one authoritative final`,()=>{
    let s=initialTranscript('lesson',[],[],language);
    const text=language==='ko' ? 'I have a question.' : source;
    s=applyEvent(s,partial({text,target_language:language}));
    s=applyEvent(s,preview({target_language:language,preview_source_text:text,translation:'complete-1'}));
    let displayed='complete-1',request=1,changes=0;
    // Six bounded replacements in this fixture; backend budget is tested separately.
    for(let second=2;second<=30;second++) {
      const grown=text+' '+('next '.repeat(second)).trim();
      s=applyEvent(s,partial({text:grown,source_revision:second,end_ms:second*1000}));
      if (second%5) { assert.equal(orderedSegments(s)[0].translation,displayed);continue; }
      request++;
      for(const token of ['', '中', 'unfinished text much longer than previous completed snapshot']) {
        const sources=s.sources;
        s=applyEvent(s,preview({target_language:language,source_revision:second,preview_request_id:request,
          preview_source_text:grown,preview_complete:false,translation:token}));
        assert.equal(s.sources,sources);
        assert.equal(orderedSegments(s)[0].translation,displayed);
        const fallback=s.translations['stream:1'].fallback_preview!;
        assert.ok(fallback.preview_complete);
        assert.ok(!('fallback_preview' in fallback));
        const identity=s.translations;
        // Wrong language, old version and old request cannot replace either buffer.
        for(const invalid of [
          {target_language:language==='en' ? 'ja' as const : 'en' as const},
          {source_revision:second-1}, {preview_request_id:request-1}, {stream_id:'old-stream'},
        ]) s=applyEvent(s,preview({target_language:language,source_revision:second,preview_source_text:grown,
          preview_request_id:request,translation:'invalid',...invalid}));
        // Foreign-stream metadata can be buffered as an orphan, but never changes this sentence.
        assert.equal(s.translations['stream:1'],identity['stream:1']);
        assert.equal(orderedSegments(s)[0].translation,displayed);
      }
      displayed=`complete-${request}`;changes++;
      const complete=preview({target_language:language,source_revision:second,preview_source_text:grown,
        preview_request_id:request,translation:displayed});
      s=applyEvent(s,complete);
      assert.equal(orderedSegments(s)[0].translation,displayed);
      assert.equal(s.translations['stream:1'].fallback_preview,undefined);
      const translations=s.translations;
      s=applyEvent(s,{...complete,event_id:crypto.randomUUID()});
      assert.equal(s.translations,translations);
    }
    assert.equal(changes,6);
    const finalText=s.sources['stream:1'].text;
    s=applyEvent(s,e('transcript.final',{text:finalText,source_revision:31,event_seq:10,target_language:language}));
    assert.equal(orderedSegments(s)[0].translation,displayed);
    s=applyEvent(s,e('translation.final',{translation:displayed,source_revision:31,event_seq:11,target_language:language}));
    s=applyEvent(s,preview({source_revision:31,preview_request_id:request+1,preview_source_text:finalText,
      preview_complete:false,translation:'late',target_language:language}));
    const segment=orderedSegments(s)[0];
    assert.equal(segment.translation_final,true);
    assert.equal(segment.translation,displayed);
    const restored=orderedSegments(initialTranscript('lesson',[segment],[],language))[0];
    assert.equal(restored.translation,displayed);
    assert.equal(restored.target_language,language);
    assert.equal(translationDirection(language),language==='ar' ? 'rtl' : 'ltr');
  });
}

test('incompatible rewrite invalidates fallback immediately and streams the new request',()=>{
  let s=applyEvent(applyEvent(initialTranscript('lesson'),partial()),preview());
  s=applyEvent(s,preview({preview_request_id:2,preview_complete:false,translation:'new partial'}));
  const rewritten='어제는 인공지능을 공부하지 않았습니다.';
  s=applyEvent(s,partial({text:rewritten,source_revision:2}));
  assert.equal(orderedSegments(s)[0].translation,'');
  const sources=s.sources;
  s=applyEvent(s,preview({source_revision:2,preview_request_id:2,translation:'stale'}));
  assert.equal(orderedSegments(s)[0].translation,'');
  for (const text of ['昨天','昨天没有学习']) {
    s=applyEvent(s,preview({source_revision:2,preview_request_id:3,preview_source_text:rewritten,
      preview_complete:false,translation:text}));
    assert.equal(orderedSegments(s)[0].translation,text);
    assert.equal(s.sources,sources);
    assert.equal(s.translations['stream:1'].fallback_preview,undefined);
  }
});

test('replacement stays buffered even when its first or later tokens exceed the completed preview',()=>{
  for (const tokens of [['更长的新请求首个中间文本'],['今','今天这段新译文已经比旧译文长很多']]) {
    let s=applyEvent(applyEvent(initialTranscript('lesson'),partial()),preview({translation:'旧完整译文'}));
    const grown=source+' 다음으로 모델을 살펴보겠습니다.';
    s=applyEvent(s,partial({text:grown,source_revision:2}));
    const sources=s.sources;
    for (const text of tokens) {
      s=applyEvent(s,preview({source_revision:2,preview_source_text:grown,preview_request_id:2,preview_complete:false,translation:text}));
      assert.equal(orderedSegments(s)[0].translation,'旧完整译文');
      assert.equal(s.translations['stream:1'].preview_request_id,2);
      assert.equal(s.translations['stream:1'].text,text);
      assert.equal(s.sources,sources);
    }
    // A valid completion may be shorter than the last buffered streaming token.
    const complete=preview({source_revision:2,preview_source_text:grown,preview_request_id:2,preview_complete:true,translation:'新完整译文'});
    s=applyEvent(s,complete);
    assert.equal(orderedSegments(s)[0].translation,'新完整译文');
    assert.equal(orderedSegments(s)[0].translation_final,false);
    assert.equal(s.translations['stream:1'].fallback_preview,undefined);
    const translations=s.translations;
    s=applyEvent(s,{...complete,event_id:crypto.randomUUID()});
    assert.equal(s.translations,translations);
  }
});

for (const failedRequest of [undefined,3]) test(`failed replacement retains a flat snapshot and request identity (${failedRequest ?? 'unlabelled'})`,()=>{
  let s=applyEvent(applyEvent(initialTranscript('lesson'),partial()),preview());
  s=applyEvent(s,preview({preview_request_id:2,preview_complete:false,translation:'新'}));
  const sources=s.sources;
  s=applyEvent(s,e('processing.failed',{task_kind:'translate',message:'mock network failure',event_seq:5,
    ...(failedRequest ? {preview_request_id:failedRequest,preview_source_text:source,preview_complete:false} : {})}));
  assert.equal(s.sources,sources);
  assert.equal(orderedSegments(s)[0].translation,'今天学习 RAG。');
  assert.equal(orderedSegments(s)[0].translation_final,false);
  assert.equal(orderedSegments(s)[0].translation_status,'failed');
  assert.equal(s.translations['stream:1'].preview_request_id,failedRequest ?? 2);
  s=applyEvent(s,preview({preview_request_id:1,translation:'旧请求迟到'}));
  assert.equal(orderedSegments(s)[0].translation,'今天学习 RAG。');
  s=applyEvent(s,partial({source_revision:2,text:'어제는 공부하지 않았습니다.'}));
  assert.equal(orderedSegments(s)[0].translation,'');
});

test('neutral period changes retain completed preview; rewrite and final still require exact source',()=>{
  let s=applyEvent(applyEvent(initialTranscript('lesson'),partial()),preview({preview_source_text:source}));
  s=applyEvent(s,partial({text:source.slice(0,-1),source_revision:2}));
  assert.equal(orderedSegments(s)[0].translation,'今天学习 RAG。');
  s=applyEvent(s,e('transcript.final',{text:source.slice(0,-1),source_revision:3,event_seq:1}));
  assert.equal(orderedSegments(s)[0].translation,'');
  s=applyEvent(s,preview({preview_source_text:source,source_revision:3}));
  assert.equal(orderedSegments(s)[0].translation,'');
});

for (const complete of [false,true]) test(`exact preview survives source final; complete=${complete}`,()=>{
  let s=applyEvent(applyEvent(initialTranscript('lesson'),partial()),preview({preview_source_text:source,preview_complete:complete}));
  s=applyEvent(s,e('transcript.final',{text:source,source_revision:2,event_seq:1}));
  assert.equal(orderedSegments(s)[0].translation,'今天学习 RAG。');
  assert.equal(orderedSegments(s)[0].translation_final,false);
  const sources=s.sources;
  s=applyEvent(s,preview({source_revision:2,preview_source_text:source,preview_complete:true,translation:'完整译文'}));
  assert.equal(s.sources,sources);
  assert.equal(orderedSegments(s)[0].translation,'完整译文');
  s=applyEvent(s,e('translation.final',{source_revision:2,translation:'完整译文',event_seq:2}));
  s=applyEvent(s,preview({source_revision:2,preview_source_text:source,preview_request_id:9,translation:'旧'}));
  assert.equal(orderedSegments(s)[0].translation,'完整译文');
  assert.equal(orderedSegments(s)[0].translation_final,true);
});

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
