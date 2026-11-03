import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToString } from "react-dom/server";
import { SessionView } from "../src/components/SessionView.tsx";

test("rendered session places the new bilingual caption after historical gaps and hides null headings", () => {
  const html = renderToString(React.createElement(SessionView, {
    session: {
      id: "lesson", title: "回归课堂", mode: "real", status: "stopped", kind: "classroom",
      duration_ms: 1_854_000, captured_ms: 30_000, created_at: "2026-11-01T10:27:00Z", retain_audio: false,
      segments: [{ sentence_id: "sentence-new", stream_id: "stream-new", source_revision: 1, translation_revision: 1,
        start_ms: 1_825_000, end_ms: 1_828_000, text: "A saved sentence.", translation: "最新中文字幕",
        mode: "real", status: "final" }],
      gaps: [{ type: "capture.gap", event_id: "gap", event_seq: 1, session_id: "lesson",
        start_ms: 1_816_000, message: "历史启动失败" }],
      stages: [{ id: "stage", topic: "None", summary: "测试摘要", knowledge_points: [], terms: [],
        decisions: [], action_items: [], source_sentence_ids: [] }],
    },
    preferences: { show_original: true, subtitle_size: 24, asr_language_mode: "ko_en" } as any,
    onActivity() {}, refresh() {}, back() {}, notify() {}, openSession() {}, deleted() {},
  }));
  assert.ok(html.indexOf("历史启动失败") < html.indexOf("最新中文字幕"));
  assert.ok(html.includes("A saved sentence."));
  assert.ok(!html.includes(">None</h3>"));
  assert.ok(html.includes("00:30"));
  assert.ok(html.includes("下次识别提示：韩语＋英语"));
});


test("interrupted source remains visible even with originals hidden and failed Chinese does not hide final source", () => {
  const html=renderToString(React.createElement(SessionView,{
    session:{id:"lesson",title:"回归",mode:"real",status:"stopped",kind:"classroom",duration_ms:1000,
      created_at:"2026-11-03T00:00:00Z",retain_audio:false,
      segments:[{sentence_id:"1",stream_id:"stream",source_revision:1,translation_revision:0,
        text:"공식 원문",translation:"",translation_status:"failed",translation_error:"timeout",
        start_ms:0,end_ms:500,status:"translating",mode:"real"}],
      unconfirmed_segments:[{sentence_id:"2",stream_id:"stream",source_revision:1,translation_revision:0,
        text:"미완성 원문",translation:"",source_status:"interrupted",source_final:false,
        start_ms:600,end_ms:1000,status:"interrupted",mode:"real"}]},
    preferences:{show_original:false,subtitle_size:24} as any,
    onActivity(){},refresh(){},back(){},notify(){},openSession(){},deleted(){}
  }));
  assert.ok(html.includes("识别未完成 · 待确认"));assert.ok(html.includes("미완성 원문"));
  assert.ok(html.includes("对应原文尚未正式确认"));assert.ok(html.includes("翻译失败，原文已保留"));
  assert.ok(html.includes("原文已定稿"));assert.ok(!html.includes("正在理解这一句"));
});
