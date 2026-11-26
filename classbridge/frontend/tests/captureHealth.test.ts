import assert from "node:assert/strict";
import { test } from "node:test";
import { recognitionStatus, type CaptureHealth } from "../src/lib/captureHealth.ts";
import { browserAudioLimits } from "../src/lib/audioRuntime.ts";
import { audioBufferFits } from "../src/lib/audio.ts";

const healthy: CaptureHealth = {
  received_audio_ms: 15000, sent_audio_ms: 15000, queued_audio_ms: 0,
  last_audio_age_ms: 20, last_transcript_age_ms: 14000,
  input_dbfs: -22, transcript_events: 0,
};
test("missing text distinguishes missing audio, forwarding backlog, quiet input and no ASR text", () => {
  assert.match(recognitionStatus({ ...healthy, last_audio_age_ms: null }), /未持续收到/);
  assert.match(recognitionStatus({ ...healthy, last_audio_age_ms: 5000 }), /VPN/);
  assert.match(recognitionStatus({ ...healthy, sent_audio_ms: 13000 }), /等待转发/);
  assert.match(recognitionStatus({ ...healthy, input_dbfs: -65 }), /音量很低或处于静音/);
  assert.match(recognitionStatus(healthy), /14 秒未收到新原文/);
  assert.equal(recognitionStatus({ ...healthy, last_transcript_age_ms: 150 }), "音频持续传输中");
});

test("runtime buffer contract validates limits and retains older-server safety",()=>{
  assert.deepEqual(browserAudioLimits(),{warning:1500,max:2000});
  for(const max of [Infinity,NaN,40000,-1]) assert.equal(browserAudioLimits({browser_buffer_warning_ms:100,browser_buffer_max_ms:max}).max,2000);
  const limit=browserAudioLimits({browser_buffer_warning_ms:1500,browser_buffer_max_ms:8000});
  assert.deepEqual(limit,{warning:1500,max:8000});
  assert.equal(audioBufferFits(3000*32,640,limit.max),true);
  assert.equal(audioBufferFits(8000*32-640,640,limit.max),true);
  assert.equal(audioBufferFits(8000*32,640,limit.max),false);
  assert.match(recognitionStatus({...healthy,buffer_state:'BUFFERING'}),/稍有延迟/);
  assert.match(recognitionStatus({...healthy,buffer_state:'DEGRADED'}),/缓冲音频/);
  assert.match(recognitionStatus({...healthy,processing_state:'DEGRADED'}),/翻译或知识处理/);
});
