// Pure reducer replay against the reviewed Git baseline; no browser/API calls.
// Run: node --import tsx tests/benchmark_subtitles.ts
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { transpileModule, ModuleKind } from "typescript";
const baseline="b6429189ceb32cfb50239b15b7af7661815cf62c";
async function load(source:string){
  const js=transpileModule(source,{compilerOptions:{module:ModuleKind.ESNext}}).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
}
function replay(api:any){
  let id=0;
  const event=(type:string,extra:any={})=>({type,session_id:'mock',stream_id:'stream',sentence_id:'1',source_revision:1,translation_revision:1,event_seq:0,event_id:`event-${++id}`,start_ms:0,end_ms:1000,mode:'real',...extra});
  const source='오늘은 인공지능을 공부합니다.';
  const original=event('transcript.partial',{text:source});
  const preview=event('translation.partial',{translation:'今天学习人工智能。',preview_source_text:source,preview_request_id:1,preview_complete:true});
  let state=api.applyEvent(api.initialTranscript('mock'),original);
  state=api.applyEvent(state,preview);
  let updates=0;
  for(let i=0;i<20;i++){
    const next=api.applyEvent(state,{...preview,event_id:`repeat-${i}`});
    if(next.translations!==state.translations)updates++;
    state=next;
  }
  state=api.applyEvent(api.initialTranscript('mock'),original);
  state=api.applyEvent(state,{...preview,preview_complete:false});
  let blanks=0;
  for(let i=1;i<20;i++){
    state=api.applyEvent(state,event('transcript.partial',{text:source,source_revision:i+1,end_ms:1000+i*100}));
    if(!api.orderedSegments(state)[0].translation)blanks++;
  }
  state=api.applyEvent(state,event('transcript.final',{text:source,source_revision:21,event_seq:1}));
  state=api.applyEvent(state,event('translation.final',{translation:'完整正式译文',source_revision:21,event_seq:2}));
  state=api.applyEvent(state,event('translation.partial',{translation:'迟到',source_revision:21}));
  const restored=api.initialTranscript('mock',api.orderedSegments(state));
  return {asr_partials:20,effective_source_changes:1,equivalent_ui_updates:updates,timestamp_blank_frames:blanks,
    final_intact:api.orderedSegments(restored)[0].translation==='完整正式译文'};
}
const old=execFileSync('git',['show',`${baseline}:classbridge/frontend/src/lib/events.ts`],{encoding:'utf8'});
const current=readFileSync(new URL('../src/lib/events.ts',import.meta.url),'utf8');
console.log(JSON.stringify({baseline, before:replay(await load(old)),after:replay(await load(current))},null,2));
