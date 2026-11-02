// Continuous, low-pass windowed-sinc resampling; no MIME relabelling.
export class PCMResampler {
  constructor(inputRate, outputRate = 16000) {
    this.step = inputRate / outputRate;
    this.cutoff = Math.min(1, outputRate / inputRate) * 0.92;
    this.half = 24;
    this.samples = Array(this.half).fill(0);
    this.position = this.half;
  }
  push(channels) {
    if (!channels.length || !channels[0].length) return new Int16Array();
    for (let i = 0; i < channels[0].length; i++) {
      let x = 0;
      for (const c of channels) x += c[i] || 0;
      this.samples.push(x / channels.length);
    }
    const output = [];
    while (this.position + this.half < this.samples.length) {
      let sum = 0,
        weight = 0;
      const center = Math.floor(this.position);
      for (let j = center - this.half + 1; j <= center + this.half; j++) {
        const x = j - this.position;
        const sinc =
          Math.abs(x) < 1e-8
            ? this.cutoff
            : Math.sin(Math.PI * x * this.cutoff) / (Math.PI * x);
        const w = sinc * (0.5 + 0.5 * Math.cos((Math.PI * x) / this.half));
        sum += this.samples[j] * w;
        weight += w;
      }
      const v = Math.max(-1, Math.min(1, sum / weight));
      output.push(Math.round(v < 0 ? v * 32768 : v * 32767));
      this.position += this.step;
    }
    const remove = Math.max(0, Math.floor(this.position) - this.half);
    this.samples.splice(0, remove);
    this.position -= remove;
    return Int16Array.from(output);
  }
}
