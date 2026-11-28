export interface CaptureHealth {
  received_audio_ms: number;
  sent_audio_ms: number;
  queued_audio_ms: number;
  last_audio_age_ms: number | null;
  last_transcript_age_ms: number;
  input_dbfs: number;
  transcript_events: number;
  buffer_state?: "NORMAL" | "BUFFERING" | "DEGRADED" | "OVERFLOW";
  capture_state?: string;
  asr_state?: string;
  batch_pending_pcm_bytes?: number;
  upstream_inflight_pcm_bytes?: number;
  archived_pcm_bytes?: number;
  archive_written_pcm_bytes?: number;
  archive_pending_pcm_bytes?: number;
  current_send_wait_ms?: number;
  asr_result_queue_size?: number;
  asr_result_queue_peak?: number;
  event_loop_lag_ms?: number;
  event_loop_lag_p95_ms?: number;
  pending_processing_tasks?: number;
  processing_state?: string;
  first_failure_code?: string | null;
  recognition_stall_suspected?: boolean;
  last_provider_heartbeat_age_ms?: number | null;
  last_asr_partial_age_ms?: number | null;
  last_asr_final_age_ms?: number | null;
}

export function recognitionStatusCode(h: CaptureHealth) {
  if (h.last_audio_age_ms === null || h.last_audio_age_ms > 4000)
    return "missing_audio";
  if (h.buffer_state === "DEGRADED") return "network_buffering";
  if (h.buffer_state === "BUFFERING") return "forwarding_delay";
  if (h.processing_state === "DEGRADED" || h.processing_state === "BUFFERING")
    return "processing_delay";
  if (h.received_audio_ms - h.sent_audio_ms > 1000) return "forwarding_queue";
  if (h.last_transcript_age_ms < 10_000) return "streaming";
  if (h.input_dbfs < -50) return "quiet";
  if (h.recognition_stall_suspected) return "recognition_stall_suspected";
  return "awaiting_transcript";
}

// Compatibility for non-localized callers; UI renders the stable code.
export function recognitionStatus(h: CaptureHealth): string {
  const labels = {
    recognition_stall_suspected: "音频和心跳仍在传输，但长时间没有新原文；这是诊断提示，不能确认模型故障。",
    missing_audio: "服务器未持续收到麦克风音频，请检查设备和 VPN 连接。",
    network_buffering: "正在录音 · 网络波动，正在缓冲音频",
    forwarding_delay: "正在录音 · 音频转发稍有延迟",
    processing_delay: "音频持续传输 · 翻译或知识处理暂时延迟",
    forwarding_queue: "音频正在等待转发到识别服务，字幕可能延迟。",
    streaming: "音频持续传输中",
    quiet: "当前输入音量很低或处于静音；若正在说话，请检查麦克风是否收到声音。",
    awaiting_transcript: `音频已转发，${Math.floor(h.last_transcript_age_ms / 1000)} 秒未收到新原文；正在等待识别服务返回文本。`,
  };
  return labels[recognitionStatusCode(h)];
}
