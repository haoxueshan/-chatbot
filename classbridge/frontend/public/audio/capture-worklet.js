import { PCMResampler, PCMFramer } from "./pcm.js";
import { InputQuality } from "./quality.js";
class ClassBridgeCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.enabled = !options?.processorOptions?.deferred;
    this.resampler = new PCMResampler(sampleRate);
    this.framer = new PCMFramer();
    this.emitFrame = (frame) => this.port.postMessage({ type: "frame", frame }, [frame]);
    this.meterTicks = 0;
    this.quality = new InputQuality(sampleRate);
    this.port.onmessage = ({ data }) => {
      if (data.type === "begin" && !this.enabled) {
        this.resampler = new PCMResampler(sampleRate);
        this.framer.reset();
        this.enabled = true;
      }
    };
  }
  process(inputs, outputs) {
    for (const channel of outputs[0] || []) channel.fill(0);
    const channels = inputs[0];
    if (!channels?.length) return true;
    if (this.enabled) this.framer.push(this.resampler.push(channels), this.emitFrame);
    const quality=this.quality.push(channels);
    if(quality)this.port.postMessage({type:"level",...quality});
    return true;
  }
}
registerProcessor("classbridge-capture", ClassBridgeCapture);
