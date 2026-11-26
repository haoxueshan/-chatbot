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
}

export function recognitionStatus(h: CaptureHealth): string {
  if (h.last_audio_age_ms === null || h.last_audio_age_ms > 4000)
    return "服务器未持续收到麦克风音频，请检查设备和 VPN 连接。";
  if (h.buffer_state === "DEGRADED") return "正在录音 · 网络波动，正在缓冲音频";
  if (h.buffer_state === "BUFFERING") return "正在录音 · 音频转发稍有延迟";
  if (h.processing_state === "DEGRADED" || h.processing_state === "BUFFERING")
    return "音频持续传输 · 翻译或知识处理暂时延迟";
  if (h.received_audio_ms - h.sent_audio_ms > 1000)
    return "音频正在等待转发到识别服务，字幕可能延迟。";
  if (h.last_transcript_age_ms < 10_000) return "音频持续传输中";
  if (h.input_dbfs < -50)
    return "当前输入音量很低或处于静音；若正在说话，请检查麦克风是否收到声音。";
  return `音频已转发，${Math.floor(h.last_transcript_age_ms / 1000)} 秒未收到新原文；正在等待识别服务返回文本。`;
}
