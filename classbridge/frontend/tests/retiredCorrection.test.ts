import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { applyEvent, initialTranscript, orderedSegments } from "../src/lib/events.ts";
import type { BridgeEvent } from "../src/lib/types.ts";

test("retired suggestion replay is ignored while cursor and formal versions remain valid", () => {
  const base = {session_id:"lesson",stream_id:"s",sentence_id:"1",source_revision:1,mode:"real" as const};
  let state=applyEvent(initialTranscript("lesson"),{...base,type:"transcript.final",event_seq:1,event_id:"a",text:"ASR 原文"});
  const before=orderedSegments(state);
  const legacy={...base,type:"segment.suggestion",event_id:"old",event_seq:2,suggestion:{suggested_text:"不应显示"}};
  state=applyEvent(state,legacy as BridgeEvent);
  assert.deepEqual(orderedSegments(state),before);
  assert.equal(state.lastSeq,2);
  state=applyEvent(state,{...base,type:"translation.final",event_id:"b",event_seq:3,translation_revision:1,translation:"正式翻译"});
  assert.equal(orderedSegments(state)[0].text,"ASR 原文");
  assert.equal(orderedSegments(state)[0].translation,"正式翻译");
  assert.equal(state.lastSeq,3);
});

test("removed UI entrypoints stay absent and audio reprocessing plus preview remain", () => {
  const read=(p:string)=>readFileSync(new URL(p,import.meta.url),"utf8");
  const settings=read("../src/components/Settings.tsx");
  const session=read("../src/components/SessionView.tsx");
  assert.doesNotMatch(settings,/上下文辅助校正|asr_assist_enabled|correction:/);
  assert.doesNotMatch(session,/CorrectionCard|推测校正|\/corrections\//);
  assert.match(settings,/asr_context/);
  assert.match(session,/\/reprocess/);
  assert.match(session,/stable_preview/);
  assert.match(session,/user_correction/); // historical version provenance remains traceable
});
