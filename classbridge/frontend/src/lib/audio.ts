export class AudioCapture {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private cancelled = false;
  async start(
    onFrame: (frame: ArrayBuffer) => void,
    onLevel: (level: number) => void,
    onInterrupt: (reason: string) => void,
    deferred = false,
  ) {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)
      throw new Error("麦克风需要 HTTPS 安全连接（本机 localhost 除外）");
    this.cancelled = false;
    this.context = new AudioContext();
    try {
      await this.context.resume();
      if (this.cancelled) return;
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: { ideal: 1 },
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      if (this.cancelled) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      this.stream = stream;
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
        else if (data.type === "level") onLevel(data.rms);
      };
      this.context.createMediaStreamSource(stream).connect(this.node);
      this.node.connect(this.context.destination);
      this.context.onstatechange = () => {
        if (this.context?.state === "suspended" && !this.cancelled)
          onInterrupt("音频设备被系统暂停，采集已停止；回到页面后可手动继续");
      };
    } catch (error) {
      this.stop();
      const name = error instanceof DOMException ? error.name : "";
      throw new Error(
        name === "NotAllowedError"
          ? "麦克风权限被拒绝，请在浏览器网站设置中允许"
          : name === "NotFoundError"
            ? "未找到可用的麦克风"
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
