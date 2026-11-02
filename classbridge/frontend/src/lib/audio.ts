export interface AudioInputOptions {
  deviceId?: string;
  processingMode?: "standard" | "natural";
  onSettings?: (settings: AppliedAudioSettings) => void;
}
export type AppliedAudioSettings = Pick<MediaTrackSettings,"echoCancellation"|"noiseSuppression"|"autoGainControl"|"sampleRate"|"channelCount">;
export interface AudioQuality { input_peak:number; peak_window_ms:number; possible_clipping:boolean; }

// A/B selection: "natural" disables *browser* processing, not the microphone's
// hardware DSP. Never add a local noise gate, which can remove quiet syllables.
export function captureConstraints(options: AudioInputOptions = {}): MediaStreamConstraints {
  const processed = options.processingMode !== "natural";
  return {
    audio: {
      channelCount: { ideal: 1 },
      echoCancellation: processed,
      noiseSuppression: processed,
      autoGainControl: processed,
      ...(options.deviceId ? { deviceId: { exact: options.deviceId } } : {}),
    },
  };
}

export class AudioCapture {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private cancelled = false;
  async start(
    onFrame: (frame: ArrayBuffer) => void,
    onLevel: (level: number, quality?: AudioQuality) => void,
    onInterrupt: (reason: string) => void,
    deferred = false,
    options: AudioInputOptions = {},
  ) {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)
      throw new Error("麦克风需要 HTTPS 安全连接（本机 localhost 除外）");
    this.cancelled = false;
    this.context = new AudioContext();
    try {
      await this.context.resume();
      if (this.cancelled) return;
      const stream = await navigator.mediaDevices.getUserMedia(captureConstraints(options));
      if (this.cancelled) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      this.stream = stream;
      const actual=stream.getTracks()[0]?.getSettings?.() || {};
      options.onSettings?.({echoCancellation:actual.echoCancellation,noiseSuppression:actual.noiseSuppression,
        autoGainControl:actual.autoGainControl,sampleRate:actual.sampleRate,channelCount:actual.channelCount});
      for (const t of stream.getTracks())
        t.onended = () => onInterrupt("麦克风设备已断开，采集已停止");
      await this.context.audioWorklet.addModule("/audio/capture-worklet.js");
      if (this.cancelled) return;
      this.node = new AudioWorkletNode(this.context, "classbridge-capture", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
        processorOptions: { deferred },
      });
      this.node.port.onmessage = ({ data }) => {
        if (this.cancelled) return;
        if (data.type === "frame") onFrame(data.frame);
        else if (data.type === "level") onLevel(data.rms, {input_peak:data.input_peak,peak_window_ms:data.peak_window_ms,possible_clipping:data.possible_clipping});
      };
      this.context.createMediaStreamSource(stream).connect(this.node);
      this.node.connect(this.context.destination);
      this.context.onstatechange = () => {
        if (["suspended","interrupted"].includes(String(this.context?.state)) && !this.cancelled)
          onInterrupt("音频设备被系统暂停，采集已停止；回到页面后可手动继续");
      };
    } catch (error) {
      this.stop();
      const name = error instanceof DOMException ? error.name : "";
      throw new Error(
        name === "NotAllowedError"
          ? "麦克风权限被拒绝，请在浏览器网站设置中允许"
          : name === "NotFoundError" || name === "OverconstrainedError"
            ? "选定麦克风已不可用，请改用系统默认麦克风或刷新设备列表"
            : name === "NotReadableError"
              ? "麦克风被占用或无法读取"
              : error instanceof Error
                ? error.message
                : "无法启动麦克风",
      );
    }
  }
  begin() {
    if (!this.cancelled) this.node?.port.postMessage({ type: "begin" });
  }
  stop() {
    this.cancelled = true;
    this.stream?.getTracks().forEach((t) => {
      t.onended = null;
      t.stop();
    });
    this.stream = null;
    this.node?.disconnect();
    this.node = null;
    const context = this.context;
    this.context = null;
    if (context && context.state !== "closed") void context.close();
  }
}
