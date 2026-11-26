export interface AudioRuntime {
  browser_buffer_warning_ms: number;
  browser_buffer_max_ms: number;
  server_queue_warning_ms?: number;
  server_queue_high_water_ms?: number;
  server_queue_max_ms?: number;
  archive_queue_max_ms?: number;
  aliyun_batch_ms?: number;
  aliyun_batch_enabled?: boolean;
  recovery_enabled?: boolean;
  recovery_buffer_ms?: number;
}

// Older servers retain the old 2-second safety limit. bufferedAmount also
// includes control messages, so it is an upper-bound estimate, not PCM truth.
export function browserAudioLimits(runtime?: Partial<AudioRuntime>) {
  const warning=runtime?.browser_buffer_warning_ms, max=runtime?.browser_buffer_max_ms;
  if (typeof warning!=="number" || typeof max!=="number" || !Number.isFinite(warning) || !Number.isFinite(max)
    || warning<20 || max>30000 || warning>=max) return {warning:1500,max:2000};
  return {warning,max};
}
