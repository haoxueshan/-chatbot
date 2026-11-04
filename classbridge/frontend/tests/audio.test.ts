import assert from "node:assert/strict";
import { test } from "node:test";
import { PCMResampler, PCMFramer } from "../public/audio/pcm.js";
import { AudioCapture, captureConstraints, audioBufferFits } from "../src/lib/audio.ts";

test("20ms packetizer preserves every sample and reset removes old tail",()=>{
  const framer=new PCMFramer();const frames:ArrayBuffer[]=[];
  const samples=Int16Array.from({length:320*100+17},(_,i)=>(i%65536)-32768);
  for(let i=0;i<samples.length;i+=43)framer.push(samples.subarray(i,i+43),(f:ArrayBuffer)=>frames.push(f));
  assert.equal(frames.length,100);assert.equal(framer.used,17);
  const restored=frames.flatMap(f=>{assert.equal(f.byteLength,640);const v=new DataView(f);return Array.from({length:320},(_,i)=>v.getInt16(i*2,true));});
  assert.deepEqual(restored,Array.from(samples.subarray(0,32000)));
  framer.reset();assert.equal(framer.used,0);
  framer.push(new Int16Array(320),(f:ArrayBuffer)=>assert.ok(new Int16Array(f).every(x=>x===0)));
});
test("browser two-second byte budget includes unsent current frame",()=>{
  assert.equal(audioBufferFits(63360,640),true);
  assert.equal(audioBufferFits(63361,640),false);
  assert.equal(audioBufferFits(64000,640),false);
  assert.equal(audioBufferFits(32000,32000),true);
});

function signal(rate: number, hz: number, seconds = 1) {
  return Float32Array.from(
    { length: rate * seconds },
    (_, i) => 0.5 * Math.sin((2 * Math.PI * hz * i) / rate),
  );
}
const rms = (a: ArrayLike<number>) =>
  Math.sqrt(Array.from(a).reduce((n, x) => n + x * x, 0) / a.length);
test("microphone profile keeps defaults and uses exact device plus optional natural A/B", () => {
  assert.deepEqual(captureConstraints(), { audio: {
    channelCount: { ideal: 1 }, echoCancellation: true,
    noiseSuppression: true, autoGainControl: true,
  }});
  assert.deepEqual(captureConstraints({ deviceId: "usb-mic", processingMode: "natural" }), { audio: {
    channelCount: { ideal: 1 }, echoCancellation: false,
    noiseSuppression: false, autoGainControl: false, deviceId: { exact: "usb-mic" },
  }});
});
test("48k/44.1k ->16k resampling conserves time, anti-aliases and averages channels", () => {
  for (const rate of [48000, 44100]) {
    const mono = signal(rate, 1000);
    const output = new PCMResampler(rate).push([mono]);
    assert.ok(Math.abs(output.length - 16000) < 20);
    const opposite = Float32Array.from(mono, (x) => -x);
    assert.ok(rms(new PCMResampler(rate).push([mono, opposite])) < 1);
    const rejected = new PCMResampler(rate).push([signal(rate, 11000)]);
    assert.ok(
      rms(rejected) / rms(output) < 0.04,
      "high-frequency aliases must be filtered",
    );
  }
});
test("streaming chunks produce the same PCM as a continuous source with bounded state", () => {
  const mono = signal(48000, 1000),
    single = new PCMResampler(48000).push([mono]);
  const processor = new PCMResampler(48000),
    frames: number[] = [];
  for (let i = 0; i < mono.length; i += 128)
    frames.push(...processor.push([mono.slice(i, i + 128)]));
  assert.deepEqual(frames, Array.from(single));
  assert.ok(processor.samples.length < 60);
});
test("stop while microphone permission is pending releases a late device grant", async () => {
  let grant!: (value: unknown) => void,
    stopped = 0,
    closed = 0;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { isSecureContext: true },
  });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      mediaDevices: {
        getUserMedia: () =>
          new Promise((r) => {
            grant = r;
          }),
      },
    },
  });
  Object.defineProperty(globalThis, "AudioContext", {
    configurable: true,
    value: class {
      state = "running";
      async resume() {}
      async close() {
        closed++;
      }
    },
  });
  const capture = new AudioCapture();
  const pending = capture.start(
    () => assert.fail("no frame after stop"),
    () => {},
    () => {},
  );
  await new Promise((resolve) => setImmediate(resolve));
  capture.stop();
  grant({
    getTracks: () => [
      {
        stop: () => {
          stopped++;
        },
      },
    ],
  });
  await pending;
  assert.equal(stopped, 1);
  assert.equal(closed, 1);
});
test("permission denial closes the audio context and returns an actionable message", async () => {
  let closed = 0;
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      mediaDevices: {
        getUserMedia: async () => {
          throw new DOMException("denied", "NotAllowedError");
        },
      },
    },
  });
  Object.defineProperty(globalThis, "AudioContext", {
    configurable: true,
    value: class {
      state = "running";
      async resume() {}
      async close() {
        closed++;
      }
    },
  });
  await assert.rejects(
    new AudioCapture().start(
      () => {},
      () => {},
      () => {},
    ),
    /权限被拒绝/,
  );
  assert.equal(closed, 1);
});
