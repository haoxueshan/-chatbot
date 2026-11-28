import assert from 'node:assert/strict';
import {test} from 'node:test';
import {PCMFramer, PCMResampler} from '../public/audio/pcm.js';
import {AudioCapture} from '../src/lib/audio.ts';

for (const count of [0, 100, 320, 740]) test(`framer flush preserves exactly ${count} samples`, () => {
  const framer = new PCMFramer(), frames: ArrayBuffer[] = [];
  const emit = (f: ArrayBuffer) => frames.push(f);
  const input = Int16Array.from({length: count}, (_,i) => i - 100);
  framer.push(input, emit); framer.flush(emit); framer.flush(emit);
  assert.deepEqual(frames.flatMap(f => Array.from(new Int16Array(f))), Array.from(input));
  assert.ok(frames.every(f => f.byteLength > 0 && f.byteLength <= 640));
  assert.equal(framer.used, 0);
});

for (const rate of [16000, 44100, 48000]) test(`${rate}Hz flush is finite, exact length and chunk independent`, () => {
  for (const count of [0, 1, 100, rate, rate + 37]) {
    const input = Float32Array.from({length: count}, (_,i) => .5*Math.sin(i*.13));
    const whole = new PCMResampler(rate), chunked = new PCMResampler(rate);
    const expected = [...whole.push([input]), ...whole.flush()];
    const actual: number[] = [];
    for (let i=0; i<count; i+=128) actual.push(...chunked.push([input.subarray(i,i+128)]));
    actual.push(...chunked.flush());
    assert.deepEqual(actual, expected);
    assert.equal(actual.length, Math.ceil(count*16000/rate));
    assert.equal(chunked.flush().length, 0);
    assert.equal(chunked.push([input]).length, 0);
    assert.equal(chunked.samples.length, 0);
  }
});

test('worklet sends every tail before acknowledgement and cannot restart after flush', async () => {
  let Processor: any;
  const messages: any[] = [];
  Object.assign(globalThis, { sampleRate: 48000,
    AudioWorkletProcessor: class {port = {onmessage: null, postMessage: (m: any) => messages.push(m)};},
    registerProcessor: (_: string, p: any) => {Processor=p;},
  });
  await import('../public/audio/capture-worklet.js');
  const p = new Processor({});
  p.process([[new Float32Array(100).fill(.25)]], [[]]);
  p.port.onmessage({data:{type:'flush',request_id:1}});
  assert.equal(messages[0].type,'frame');
  assert.equal(messages[0].frame.byteLength,68);
  assert.deepEqual(messages[1],{type:'flush-complete',request_id:1,emitted_samples:34});
  p.port.onmessage({data:{type:'begin'}});
  p.process([[new Float32Array(100)]],[[]]);
  p.port.onmessage({data:{type:'flush',request_id:2}});
  assert.equal(messages.filter(m=>m.type==='frame').length,1);
});

for (const ending of ['complete','timeout','cancelled'] as const) test(`AudioCapture finish ${ending} releases resources once`, async () => {
  let node: any, stopped=0, closed=0;
  const sent: any[] = [], received: number[] = [];
  Object.assign(globalThis, {window:{isSecureContext:true},
    AudioContext: class {state='running'; audioWorklet={addModule:async()=>{}};
      async resume() {} async close() {closed++;} createMediaStreamSource(){return {connect(){}};}},
    AudioWorkletNode: class {port={onmessage:null as any,postMessage:(m:any)=>sent.push(m)};
      constructor(){node=this;} connect(){} disconnect(){}},
  });
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:async()=>({
    getTracks:()=>[{stop(){stopped++;}}],
  })}}});
  const c=new AudioCapture();
  await c.start(f=>received.push(f.byteLength),()=>{},()=>{});
  const pending=c.finish(10);
  assert.equal(c.finish(),pending);
  if(ending==='complete') {
    node.port.onmessage({data:{type:'flush-complete',request_id:-1}});
    node.port.onmessage({data:{type:'frame',frame:new ArrayBuffer(200)}});
    node.port.onmessage({data:{type:'flush-complete',request_id:sent[0].request_id,emitted_samples:100}});
  } else if(ending==='cancelled') c.stop();
  assert.equal((await pending).status,ending);
  c.stop();
  assert.equal(stopped,1); assert.equal(closed,1);
  assert.deepEqual(received,ending==='complete'?[200]:[]);
});
