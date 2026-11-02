import { PCMResampler } from "./pcm.js";
class ClassBridgeCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.enabled = !options?.processorOptions?.deferred;
    this.resampler = new PCMResampler(sampleRate);
    this.pending = [];
    this.meterTicks = 0;
    this.port.onmessage = ({ data }) => {
      if (data.type === "begin" && !this.enabled) {
        this.resampler = new PCMResampler(sampleRate);
        this.pending = [];
        this.enabled = true;
      }
    };
  }
  process(inputs, outputs) {
    for (const channel of outputs[0] || []) channel.fill(0);
    const channels = inputs[0];
    if (!channels?.length) return true;
    const pcm = this.enabled ? this.resampler.push(channels) : [];
    for (const x of pcm) this.pending.push(x);
    while (this.pending.length >= 320) {
      const frame = new ArrayBuffer(640);
      const view = new DataView(frame);
      for (let i = 0; i < 320; i++) view.setInt16(i * 2, this.pending[i], true);
      this.pending.splice(0, 320);
      this.port.postMessage({ type: "frame", frame }, [frame]);
    }
    if (++this.meterTicks >= 8) {
      let sum = 0;
      for (let i = 0; i < channels[0].length; i++) {
        let x = 0;
        for (const c of channels) x += c[i] || 0;
        sum += (x / channels.length) ** 2;
      }
      this.port.postMessage({
        type: "level",
        rms: Math.sqrt(sum / channels[0].length),
      });
      this.meterTicks = 0;
    }
    return true;
  }
}
registerProcessor("classbridge-capture", ClassBridgeCapture);
