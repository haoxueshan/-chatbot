import type { BridgeEvent, Segment } from "./types";

export type TimelineEntry =
  | { kind: "segment"; time: number; key: string; segment: Segment }
  | { kind: "gap"; time: number; key: string; gap: BridgeEvent; related: BridgeEvent[] };

export function incidentLabel(events: BridgeEvent[]): string {
  if (events.some(e=>e.gap_kind==='audio_missing')) return "采集缺口";
  if (events.some(e=>e.gap_kind==='storage_failed')) return "保存异常";
  if (events.some(e=>e.gap_kind==='asr_result_uncertain')) return "识别结果待确认";
  if (events.some(e=>e.gap_kind==='asr_interrupted')) return "识别中断";
  const kind=events[0]?.gap_kind;
  return kind==='user_paused' ? "录音暂停" : kind==='audio_delayed' ? "音频延迟"
    : kind==='translation_delayed' ? "翻译延迟" : kind==='connection_recovered' ? "连接已恢复，音频未确认恢复"
    : kind==='connection_recovering' ? "连接恢复中" : "采集缺口";
}

export function buildTimeline(segments: Segment[], gaps: BridgeEvent[]): TimelineEntry[] {
  const groups=new Map<string,BridgeEvent[]>();
  gaps.forEach((gap,index)=>{
    const key=gap.incident_id ? `${gap.session_id}:${gap.incident_id}` : gap.event_id || `${index}`;
    const group=groups.get(key) || [];group.push(gap);groups.set(key,group);
  });
  const items: TimelineEntry[] = [
    ...segments.map((segment): TimelineEntry => ({
      kind: "segment", time: segment.start_ms, key: `segment:${segment.stream_id}:${segment.sentence_id}`, segment,
    })),
    ...Array.from(groups,([key,related]): TimelineEntry => ({
      kind: "gap", time: Math.min(...related.map(g=>g.start_ms ?? g.end_ms ?? 0)), key: `gap:${key}`, gap:related[0], related,
    })),
  ];
  return items.sort((a, b) => a.time - b.time || (a.kind === b.kind ? 0 : a.kind === "gap" ? -1 : 1));
}
