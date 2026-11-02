import assert from 'node:assert/strict';
import {test} from 'node:test';
import {InputQuality} from '../public/audio/quality.js';
import {classroomPreset} from '../src/lib/classroomPreset.ts';
import {AudioCapture} from '../src/lib/audio.ts';
import type {Preferences} from '../src/lib/types.ts';

test('classroom preset changes a draft and preserves confirmed glossary and context',()=>{
  const saved={asr_language_mode:'auto',asr_context:'실제 강의',terms:['작업기억']} as Preferences;
  const draft=classroomPreset(saved);
  assert.equal(saved.asr_language_mode,'auto');assert.equal(draft.asr_language_mode,'ko_en');
  assert.equal(draft.asr_hotword_weight,4);assert.equal(draft.asr_acoustic_profile,'far');
  assert.equal(draft.audio_processing_mode,'standard');assert.equal(draft.terms,saved.terms);
  assert.equal(draft.asr_context,saved.asr_context);
});
test('peak covers every callback in a 200ms window; isolated spike does not indicate sustained clipping',()=>{
  const monitor=new InputQuality(48000);
  assert.equal(monitor.push([Float32Array.of(1)]),null);
  const reading=monitor.push([new Float32Array(9599).fill(.1)]);
  assert.equal(reading.input_peak,1);assert.equal(reading.peak_window_ms,200);
  assert.equal(reading.possible_clipping,false);
  for(let i=0;i<3;i++){
    const r=monitor.push([new Float32Array(9600).fill(.99)]);
    assert.equal(r.possible_clipping,i===2);assert.ok(Math.abs(r.rms-.99)<.001);
  }
  assert.equal(monitor.push([new Float32Array(9600)]).possible_clipping,false);
  assert.equal(monitor.count,0);
});
test('unavailable exact microphone is rejected with no fallback and context is closed',async()=>{
  let calls=0,closed=0;
  Object.assign(globalThis,{window:{isSecureContext:true},AudioContext:class {
    state='running';async resume(){} async close(){closed++;}
  }});
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:async(c:any)=>{
    calls++;assert.deepEqual(c.audio.deviceId,{exact:'missing'});
    throw new DOMException('missing','OverconstrainedError');
  }}}});
  await assert.rejects(new AudioCapture().start(()=>{},()=>{},()=>{},true,{deviceId:'missing'}),/选定麦克风已不可用/);
  assert.equal(calls,1);assert.equal(closed,1);
});
