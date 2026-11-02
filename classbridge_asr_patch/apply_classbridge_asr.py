#!/usr/bin/env python3
"""Apply tested-scope Korean/English ASR and far-field microphone improvements.

Run from the checked-out haoxueshan/-chatbot repository, or pass --repo PATH.
The script checks *all* source anchors before writing; it never touches .env,
user recordings, database, or model credentials.
"""
from __future__ import annotations

import argparse
from pathlib import Path

PATCHES: dict[str, list[tuple[str, str]]] = {}


def change(path: str, old: str, new: str) -> None:
    PATCHES.setdefault(path, []).append((old, new))


# --- Phase 1: use the already implemented Korean/English hints and vocabulary,
# fix the legacy source->term fallback, offer a classroom preset (not auto-on).
change("backend/app/services/asr_options.py",
    "word = item.get('source',item.get('term','')) if isinstance(item,dict) else item",
    "word = (item.get('source') or item.get('term') or '') if isinstance(item,dict) else item")

change("backend/app/api/settings.py",
    "    asr_assist_enabled: bool = False\n    terms: list[dict | str]",
    "    asr_assist_enabled: bool = False\n    asr_acoustic_profile: Literal['far','near'] = 'far'\n    audio_processing_mode: Literal['standard','natural'] = 'standard'\n    terms: list[dict | str]")

# Official qwen-audio-3.1-asr-flash-streaming VAD names. No custom noise
# threshold or silence threshold is sent, since changes require real audio A/B.
change("backend/app/providers/aliyun.py",
    "language_hints=None, on_ready=None, metrics=None) -> AsyncIterator[dict]:",
    "language_hints=None, vad_model=None, on_ready=None, metrics=None) -> AsyncIterator[dict]:")
change("backend/app/providers/aliyun.py",
    '        params = {"format": "pcm", "sample_rate": 16000, "heartbeat": True}\n        if language_hints:',
    '        params = {"format": "pcm", "sample_rate": 16000, "heartbeat": True}\n'
    '        if vad_model is not None:\n'
    '            if vad_model not in ("near_meeting_16k", "far_field_meeting_16k"):\n'
    '                raise ProviderError("invalid_asr_parameter", "不支持的拾音场景参数。")\n'
    '            params["vad_model"] = vad_model\n'
    '        if language_hints:')

change("backend/app/ws/live.py",
    "        self.asr_language_mode='auto'\n        self.asr_enhancement={}",
    "        self.asr_language_mode='auto'\n        self.asr_acoustic_profile='far'\n        self.asr_enhancement={}")
change("backend/app/ws/live.py",
    'asr_language_mode=self.asr_language_mode,asr_enhancement=self.asr_enhancement,',
    'asr_language_mode=self.asr_language_mode,asr_acoustic_profile=self.asr_acoustic_profile,asr_enhancement=self.asr_enhancement,')
change("backend/app/ws/live.py",
    "                    self.asr_language_mode=preferences.get('asr_language_mode','auto')",
    "                    self.asr_language_mode=preferences.get('asr_language_mode','auto')\n"
    "                    profile=preferences.get('asr_acoustic_profile','far')\n"
    "                    self.asr_acoustic_profile=profile if profile in ('far','near') else 'far'")
change("backend/app/ws/live.py",
    'vocabulary=vocabulary,context=context,language_hints=asr_language_hints(self.asr_language_mode)):await self.consume(event)',
    'vocabulary=vocabulary,context=context,language_hints=asr_language_hints(self.asr_language_mode),\n'
    "                    vad_model='near_meeting_16k' if self.asr_acoustic_profile=='near' else 'far_field_meeting_16k'):await self.consume(event)")

# --- Phase 2: browser microphone device selection and auditable browser DSP.
change("frontend/src/lib/audio.ts",
    'export class AudioCapture {',
    '''export interface AudioInputOptions {
  deviceId?: string;
  processingMode?: "standard" | "natural";
}

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

export class AudioCapture {''')
change("frontend/src/lib/audio.ts",
    '    onLevel: (level: number) => void,',
    '    onLevel: (level: number, peak?: number) => void,')
change("frontend/src/lib/audio.ts",
    '    deferred = false,\n  ) {',
    '    deferred = false,\n    options: AudioInputOptions = {},\n  ) {')
change("frontend/src/lib/audio.ts",
    '''      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: { ideal: 1 },
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });''',
    '      const stream = await navigator.mediaDevices.getUserMedia(captureConstraints(options));')
change("frontend/src/lib/audio.ts",
    'else if (data.type === "level") onLevel(data.rms);',
    'else if (data.type === "level") onLevel(data.rms, data.peak);')
change("frontend/src/lib/audio.ts",
    '          : name === "NotFoundError"\n            ? "未找到可用的麦克风"',
    '          : name === "NotFoundError" || name === "OverconstrainedError"\n            ? "选定麦克风已不可用，请改用系统默认麦克风或刷新设备列表"')

change("frontend/public/audio/capture-worklet.js",
    '      let sum = 0;\n      for (let i = 0; i < channels[0].length; i++) {',
    '      let sum = 0;\n      let peak = 0;\n      for (let i = 0; i < channels[0].length; i++) {')
change("frontend/public/audio/capture-worklet.js",
    '        sum += (x / channels.length) ** 2;',
    '        const value = x / channels.length;\n        sum += value ** 2;\n        peak = Math.max(peak, Math.abs(value));')
change("frontend/public/audio/capture-worklet.js",
    '        rms: Math.sqrt(sum / channels[0].length),',
    '        rms: Math.sqrt(sum / channels[0].length),\n        peak,')

change("frontend/src/lib/types.ts",
    '  asr_language_mode?: import("./asrLanguages").ASRLanguageMode;\n  asr_enhancement?',
    '  asr_language_mode?: import("./asrLanguages").ASRLanguageMode;\n  asr_acoustic_profile?: "far" | "near";\n  asr_enhancement?')
change("frontend/src/lib/types.ts",
    '  asr_hotword_weight?: 2 | 3 | 4;',
    '  asr_hotword_weight?: 2 | 3 | 4;\n  asr_acoustic_profile?: "far" | "near";\n  audio_processing_mode?: "standard" | "natural";')

change("frontend/src/lib/useLive.ts",
    'import { AudioCapture } from "./audio";',
    'import { AudioCapture, type AudioInputOptions } from "./audio";')
change("frontend/src/lib/useLive.ts",
    'export function useLive(session: Session, onSaved: () => void) {',
    'export function useLive(session: Session, onSaved: () => void, audioOptions: AudioInputOptions = {}) {')
change("frontend/src/lib/useLive.ts",
    '  const [level, setLevel] = useState(0);',
    '  const [level, setLevel] = useState(0);\n  const [inputPeak, setInputPeak] = useState(0);\n  const [asrAcousticProfile, setAsrAcousticProfile] = useState<"far" | "near">();')
change("frontend/src/lib/useLive.ts",
    '    setLevel(0);\n    total.current +=',
    '    setLevel(0);\n    setInputPeak(0);\n    total.current +=')
change("frontend/src/lib/useLive.ts",
    '              setAsrLanguageMode(e.asr_language_mode);',
    '              setAsrLanguageMode(e.asr_language_mode);\n              setAsrAcousticProfile(e.asr_acoustic_profile);')
change("frontend/src/lib/useLive.ts",
    '    setAsrLanguageMode(undefined);\n    setAsrEnhancement(undefined);',
    '    setAsrLanguageMode(undefined);\n    setAsrAcousticProfile(undefined);\n    setAsrEnhancement(undefined);')
change("frontend/src/lib/useLive.ts",
    '          setLevel,\n          stop,\n          true,',
    '          (rms, peak) => { setLevel(rms); setInputPeak(peak ?? 0); },\n          stop,\n          true,\n          audioOptions,')
change("frontend/src/lib/useLive.ts",
    '    level,\n    queue,',
    '    level,\n    inputPeak,\n    asrAcousticProfile,\n    queue,')

# Session-local device id stays in localStorage on the browser, not server prefs.
# A user must explicitly choose a microphone. Stale ids return actionable errors.
change("frontend/src/components/SessionView.tsx",
    '  const live = useLive(session, refresh);',
    '''  const [microphoneId, setMicrophoneId] = useState(() => {
    try { return typeof window === "undefined" ? "" : window.localStorage.getItem("classbridge.microphone.v1") || ""; }
    catch { return ""; }
  });
  const [microphones, setMicrophones] = useState<{ deviceId: string; label: string }[]>([]);
  const live = useLive(session, refresh, {
    deviceId: microphoneId,
    processingMode: preferences.audio_processing_mode || "standard",
  });
  const refreshMicrophones = () => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) return;
    void navigator.mediaDevices.enumerateDevices().then((items) =>
      setMicrophones(items.filter((item) => item.kind === "audioinput" && item.deviceId)
        .map((item) => ({ deviceId: item.deviceId, label: item.label }))),
    ).catch(() => {});
  };
  useEffect(() => {
    if (session.mode !== "real" || typeof navigator === "undefined") return;
    refreshMicrophones();
    navigator.mediaDevices?.addEventListener?.("devicechange", refreshMicrophones);
    return () => navigator.mediaDevices?.removeEventListener?.("devicechange", refreshMicrophones);
  }, [session.mode]);
  const chooseMicrophone = (id: string) => {
    setMicrophoneId(id);
    try { window.localStorage.setItem("classbridge.microphone.v1", id); }
    catch { /* private mode/storage restrictions */ }
  };''')
change("frontend/src/components/SessionView.tsx",
    '      <div className="capture-bar">',
    '''      {session.mode === "real" && (
        <div className="info-box" style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
          <label htmlFor="classbridge-microphone">麦克风：</label>
          <select id="classbridge-microphone" aria-label="录音麦克风"
            disabled={live.active || live.settling}
            value={microphoneId}
            onChange={(event) => chooseMicrophone(event.target.value)}>
            <option value="">系统默认麦克风</option>
            {microphoneId && !microphones.some((m) => m.deviceId === microphoneId) &&
              <option value={microphoneId}>此前选择的设备（可能已断开）</option>}
            {microphones.filter((m) => m.deviceId !== "default").map((m, index) =>
              <option key={m.deviceId} value={m.deviceId}>{m.label || `麦克风 ${index + 1}`}</option>)}
          </select>
          <button className="text-button" type="button" onClick={refreshMicrophones}
            disabled={live.active || live.settling}>刷新设备</button>
          <span className="tiny muted">
            {preferences.asr_acoustic_profile === "near" ? "近场" : "远场"}识别 ·
            {preferences.audio_processing_mode === "natural" ? "浏览器原声模式" : "浏览器标准处理"}
          </span>
          {live.inputPeak > 0.98 && <strong role="status">输入峰值接近满幅；若声音失真请降低麦克风增益</strong>}
        </div>
      )}
      <div className="capture-bar">''')

change("frontend/src/components/Settings.tsx",
    '          <label className="settings-row">\n            <div>\n              <strong>语音识别语言提示</strong>',
    '''          <button type="button" className="secondary" onClick={() => setDraft({
            ...draft, asr_language_mode: "ko_en", asr_hotword_weight: 4,
            asr_acoustic_profile: "far", audio_processing_mode: "standard",
          })}>应用韩英远场课堂预设（仍需点击保存）</button>
          <label className="settings-row">
            <div>
              <strong>语音识别语言提示</strong>''')
change("frontend/src/components/Settings.tsx",
    '          <label className="settings-row">\n            <div>\n              <strong>新会话默认保留音频</strong>',
    '''          <label className="settings-row">
            <div>
              <strong>识别拾音场景</strong>
              <small>远距离教授讲话用远场（ASR 默认）；领夹麦或近距离话筒可测试近场。仅在下次开始录音时生效。</small>
            </div>
            <select aria-label="识别拾音场景" value={draft.asr_acoustic_profile || "far"}
              onChange={(e) => setDraft({ ...draft, asr_acoustic_profile: e.target.value as "far" | "near" })}>
              <option value="far">远场课堂 / 会议</option>
              <option value="near">近距离麦克风</option>
            </select>
          </label>
          <label className="settings-row">
            <div>
              <strong>浏览器音频处理</strong>
              <small>标准模式保持原有回声消除、降噪和自动增益；原声模式关闭浏览器的这些处理供 A/B 对比，可能更差，不能消除硬件处理。</small>
            </div>
            <select aria-label="浏览器音频处理" value={draft.audio_processing_mode || "standard"}
              onChange={(e) => setDraft({ ...draft, audio_processing_mode: e.target.value as "standard" | "natural" })}>
              <option value="standard">标准（默认）</option>
              <option value="natural">原声对照</option>
            </select>
          </label>
          <label className="settings-row">
            <div>
              <strong>新会话默认保留音频</strong>''')

# --- Regression tests (test changes apply to existing fixtures).
change("backend/tests/test_core.py",
    "        assert kwargs['language_hints']==['ko','en']",
    "        assert kwargs['language_hints']==['ko','en']\n        assert kwargs['vad_model']=='near_meeting_16k'")
change("backend/tests/test_core.py",
    "'asr_hotword_weight':4,'asr_context':'인지심리학 수업. 작업기억.'}",
    "'asr_hotword_weight':4,'asr_context':'인지심리학 수업. 작업기억.', 'asr_acoustic_profile':'near'}")
change("backend/tests/test_core.py",
    "        assert ready_event.payload['asr_language_mode']=='ko_en'",
    "        assert ready_event.payload['asr_language_mode']=='ko_en'\n        assert ready_event.payload['asr_acoustic_profile']=='near'")
change("backend/tests/test_core.py",
    "    assert client.patch('/api/settings',json={'asr_language_mode':'made-up-language'}).status_code==422",
    "    assert client.patch('/api/settings',json={'asr_language_mode':'made-up-language'}).status_code==422\n"
    "    assert client.patch('/api/settings',json={'asr_acoustic_profile':'unknown'}).status_code==422\n"
    "    assert client.patch('/api/settings',json={'audio_processing_mode':'enhance'}).status_code==422\n"
    "    assert client.patch('/api/settings',json={'asr_acoustic_profile':'near','audio_processing_mode':'natural'}).json()['asr_acoustic_profile']=='near'")
change("backend/tests/test_providers.py",
    'vocabulary={\'RAG\':2},context=context,language_hints=asr_language_hints(mode))]',
    'vocabulary={\'RAG\':2},context=context,language_hints=asr_language_hints(mode),vad_model="far_field_meeting_16k")]')
change("backend/tests/test_providers.py",
    '    assert start["payload"]["parameters"]["sample_rate"] == 16000',
    '    assert start["payload"]["parameters"]["sample_rate"] == 16000\n'
    '    assert start["payload"]["parameters"]["vad_model"] == "far_field_meeting_16k"')
change("frontend/tests/audio.test.ts",
    'import { AudioCapture } from "../src/lib/audio.ts";',
    'import { AudioCapture, captureConstraints } from "../src/lib/audio.ts";')
change("frontend/tests/audio.test.ts",
    'test("48k/44.1k ->16k resampling conserves time, anti-aliases and averages channels",',
    '''test("microphone profile keeps defaults and uses exact device plus optional natural A/B", () => {
  assert.deepEqual(captureConstraints(), { audio: {
    channelCount: { ideal: 1 }, echoCancellation: true,
    noiseSuppression: true, autoGainControl: true,
  }});
  assert.deepEqual(captureConstraints({ deviceId: "usb-mic", processingMode: "natural" }), { audio: {
    channelCount: { ideal: 1 }, echoCancellation: false,
    noiseSuppression: false, autoGainControl: false, deviceId: { exact: "usb-mic" },
  }});
});
test("48k/44.1k ->16k resampling conserves time, anti-aliases and averages channels",''')
change("frontend/tests/settings.test.ts",
    '  assert.ok(html.includes("语音识别语言提示"));',
    '  assert.ok(html.includes("语音识别语言提示"));\n'
    '  assert.ok(html.includes("应用韩英远场课堂预设"));\n'
    '  assert.ok(html.includes("识别拾音场景"));\n'
    '  assert.ok(html.includes("浏览器音频处理"));')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Root of -chatbot checkout or classbridge directory")
    parser.add_argument("--apply", action="store_true", help="Write the changes after validating every target (default: check only)")
    args = parser.parse_args()
    root = args.repo.resolve()
    if (root / "classbridge").is_dir():
        root /= "classbridge"
    updates: dict[Path, str] = {}
    errors = []
    for relative, replacements in PATCHES.items():
        target = root / relative
        if not target.is_file():
            errors.append(f"Missing {relative}")
            continue
        content = target.read_text(encoding="utf-8")
        for old, new in replacements:
            count = content.count(old)
            if count != 1:
                errors.append(f"{relative}: anchor match count {count}: {old[:85]!r}")
            else:
                content = content.replace(old, new, 1)
        updates[target] = content
    if errors:
        raise SystemExit("Source mismatch: nothing written.\n" + "\n".join(errors))
    print(f"Validated {len(updates)} source/test files in {root}")
    for path in updates:
        print("  " + str(path.relative_to(root)))
    if args.apply:
        for path, content in updates.items():
            path.write_text(content, encoding="utf-8")
        print("Applied. Run backend pytest and frontend npm test / npm run build before committing.")
    else:
        print("Dry run only. Add --apply to write files.")


if __name__ == "__main__":
    main()
