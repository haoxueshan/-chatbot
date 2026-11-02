import assert from "node:assert/strict";
import { test } from "node:test";
import { recognitionStatus, type CaptureHealth } from "../src/lib/captureHealth.ts";

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
