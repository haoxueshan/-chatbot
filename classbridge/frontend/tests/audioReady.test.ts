import assert from "node:assert/strict";
import { test } from "node:test";
import { AudioCapture } from "../src/lib/audio.ts";

test("a slow upstream startup creates no PCM backlog until the worklet is enabled", async () => {
  const messages: { type: string; frame?: ArrayBuffer }[] = [];
  let Processor: any;
  Object.assign(globalThis, {
    sampleRate: 48_000,
    AudioWorkletProcessor: class {
      port = { onmessage: null, postMessage: (message: any) => messages.push(message) };
    },
    registerProcessor: (_name: string, processor: any) => { Processor = processor; },
  });
  await import("../public/audio/capture-worklet.js");
  const processor = new Processor({ processorOptions: { deferred: true } });
  const channels = [new Float32Array(128).fill(.1)];
  for (let i = 0; i < 2000; i++) processor.process([channels], [[new Float32Array(128)]]);
  assert.equal(messages.filter((m) => m.type === "frame").length, 0);
  assert.equal(processor.pending.length, 0);
  assert.ok(messages.some((m) => m.type === "level"));
  processor.port.onmessage({ data: { type: "begin" } });
  for (let i = 0; i < 100; i++) processor.process([channels], [[new Float32Array(128)]]);
  const frames = messages.filter((m) => m.type === "frame");
  assert.ok(frames.length > 0);
  assert.ok(frames.every((m) => m.frame?.byteLength === 640));
});

test("a late ready callback after cancellation cannot re-enable the microphone", async () => {
  const messages: unknown[] = [];
  let stopped = 0, closed = 0, options: any;
  Object.assign(globalThis, { window: { isSecureContext: true } });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
    mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() { stopped++; },getSettings:()=>({deviceId:'private-id',echoCancellation:false,sampleRate:48000}) }] }) },
  } });
  Object.assign(globalThis, {
    AudioContext: class {
      state = "running";
      audioWorklet = { addModule: async () => {} };
      async resume() {}
      async close() { closed++; }
      createMediaStreamSource() { return { connect() {} }; }
    },
    AudioWorkletNode: class {
      port = { onmessage: null, postMessage: (message: unknown) => messages.push(message) };
      constructor(_context: unknown, _name: string, config: unknown) { options = config; }
      connect() {}
      disconnect() {}
    },
  });
  const capture = new AudioCapture();
  let applied:any;
  await capture.start(() => {}, () => {}, () => {}, true,{onSettings:s=>{applied=s;}});
  assert.equal(applied.echoCancellation,false);
  assert.equal(applied.noiseSuppression,undefined);
  assert.equal(applied.deviceId,undefined);
  assert.equal(options.processorOptions.deferred, true);
  assert.deepEqual(messages, []);
  capture.stop();
  capture.begin();
  assert.deepEqual(messages, []);
  assert.equal(stopped, 1);
  assert.equal(closed, 1);
});
