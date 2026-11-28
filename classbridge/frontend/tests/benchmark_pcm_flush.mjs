// Deterministic offline comparison against the requested reference commit.
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
import {PCMFramer,PCMResampler} from '../public/audio/pcm.js';
const baselineSource=execFileSync('git',['show','62d269f1ecab297b2bed53ef6c383b7e895b7729:classbridge/frontend/public/audio/pcm.js'],{encoding:'utf8'});
const baseline=await import(`data:text/javascript;base64,${Buffer.from(baselineSource).toString('base64')}`);
const reports=[];
for(const rate of [16000,44100,48000]) {
  const input=Float32Array.from({length:rate+100},(_,i)=>.3*Math.sin(i*.13));
  const measure=(Resampler,Framer,flush)=>{
    const r=new Resampler(rate),f=new Framer();let bytes=0,frames=0;
    const emit=frame=>{bytes+=frame.byteLength;frames++;};
    for(let i=0;i<input.length;i+=128) f.push(r.push([input.subarray(i,i+128)]),emit);
    if(flush){f.push(r.flush(),emit);f.flush(emit);f.flush(emit);}
    return {bytes,frames};
  };
  const before=measure(baseline.PCMResampler,baseline.PCMFramer,false);
  const after=measure(PCMResampler,PCMFramer,true);
  const expected=Math.ceil(input.length*16000/rate)*2;
  assert.equal(after.bytes,expected);
  reports.push({input_rate:rate,input_samples:input.length,expected_bytes:expected,before,after,restored_bytes:after.bytes-before.bytes});
}
console.log(JSON.stringify(reports,null,2));
