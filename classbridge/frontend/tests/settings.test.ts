import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToString } from "react-dom/server";
import { Settings } from "../src/components/Settings.tsx";

test("settings displays the saved Korean/English input hint separately from Chinese translation", () => {
  const html = renderToString(React.createElement(Settings, {
    preferences: { theme: "light", subtitle_size: 24, show_original: true, retain_audio: false,
      audio_retention_days: 7, terms: [], asr_language_mode: "ko_en", asr_hotword_weight: 4,
      asr_context: "인지심리학. 작업기억.",
      asr_terms_status: { enabled_count: 0, skipped: [{ index: 0, reason: "超过15字符限制" }] } },
    save: async () => {},
  }));
  assert.match(html, /value="ko_en" selected=""/);
  assert.ok(html.includes("全部语言自动识别"));
  assert.ok(html.includes("语音识别语言提示"));
  assert.ok(html.includes("应用韩英远场课堂预设"));
  assert.ok(html.includes("识别拾音场景"));
  assert.ok(html.includes("浏览器音频处理"));
  assert.ok(html.includes("简体中文"));
  assert.ok(html.includes("인지심리학. 작업기억."));
  assert.match(html, /value="4" selected=""/);
  assert.ok(html.includes("当前没有可用热词"));
  assert.ok(html.includes("超过15字符限制"));
  assert.ok(html.includes("示例不会自动加入模型请求"));
});
