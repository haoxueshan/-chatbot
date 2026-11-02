// Local diagnostics only; never changes or gates PCM samples.
export class InputQuality {
  constructor(rate) { this.rate=rate; this.count=0; this.energy=0; this.peak=0; this.hot=0; this.streak=0; }
  push(channels) {
    if (!channels.length) return null;
    for(let i=0;i<channels[0].length;i++) {
      let mixed=0,peak=0;
      for(const c of channels) { const v=c[i]||0; mixed+=v; peak=Math.max(peak,Math.abs(v)); }
      mixed/=channels.length; this.energy+=mixed*mixed; this.count++;
      this.peak=Math.max(this.peak,peak); if(peak>=.98)this.hot++;
    }
    if(this.count<this.rate*.2)return null;
    this.streak=this.hot/this.count>=.01?this.streak+1:0;
    const result={rms:Math.sqrt(this.energy/this.count),input_peak:this.peak,
      peak_window_ms:1000*this.count/this.rate,possible_clipping:this.streak>=3};
    this.count=0;this.energy=0;this.peak=0;this.hot=0;return result;
  }
}
