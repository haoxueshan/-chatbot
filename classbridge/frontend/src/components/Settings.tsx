import { useEffect, useState } from "react";
import {
  BookOpen,
  Check,
  Languages,
  Monitor,
  Moon,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
} from "lucide-react";
import type { Preferences } from "../lib/types";
import { classroomPreset } from "../lib/classroomPreset";
import { asrLanguageLabels, type ASRLanguageMode } from "../lib/asrLanguages";
export function Settings({
  preferences,
  save,
}: {
  preferences: Preferences;
  save: (p: Preferences) => Promise<void>;
}) {
  const [draft, setDraft] = useState(preferences),
    [terms, setTerms] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  useEffect(() => {
    setDraft(preferences);
    setTerms(
      preferences.terms
        .map((t) =>
          typeof t === "string"
            ? t
            : `${t.source || t.term || ""} = ${t.target || t.translation || ""}`,
        )
        .join("\n"),
    );
  }, [preferences]);
  const submit = async () => {
    setBusy(true);
    setMessage("");
    try {
      const parsed = terms
        .split("\n")
        .map((x) => x.trim())
        .filter(Boolean)
        .map((x) => {
          const [source, ...target] = x.split("=");
          return target.length
            ? { source: source.trim(), target: target.join("=").trim() }
            : x;
        });
      await save({ ...draft, terms: parsed });
      setMessage("偏好已保存");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="settings page-scroll">
      <div className="settings-width">
        <div className="page-heading">
          <div>
            <span className="eyebrow">MAKE IT YOURS</span>
            <h1>偏好设置</h1>
            <p>让工作台适应你的阅读与学习习惯。</p>
          </div>
          <button
            className="primary"
            disabled={busy}
            onClick={() => void submit()}
          >
            <Save size={16} />
            {busy ? "保存中…" : "保存偏好"}
          </button>
        </div>
        {message && (
          <div role="status" className="info-box">
            {message}
          </div>
        )}
        <section className="settings-card">
          <div className="settings-title">
            <span className="quick-icon purple">
              <SlidersHorizontal size={21} />
            </span>
            <div>
              <h2>阅读体验</h2>
              <p>中文优先，保持清晰。</p>
            </div>
          </div>
          <div className="settings-row">
            <div>
              <strong>界面主题</strong>
              <small>切换明暗显示，照顾不同的光线环境。</small>
            </div>
            <div className="segmented theme-choice">
              <button
                className={draft.theme === "light" ? "active" : ""}
                onClick={() => setDraft({ ...draft, theme: "light" })}
              >
                <Sun size={15} />
                浅色
              </button>
              <button
                className={draft.theme === "dark" ? "active" : ""}
                onClick={() => setDraft({ ...draft, theme: "dark" })}
              >
                <Moon size={15} />
                深色
              </button>
            </div>
          </div>
          <div className="settings-row">
            <div>
              <strong>中文字幕字号</strong>
              <small>18–44 px，可在大屏与平板舒适阅读。</small>
            </div>
            <div className="range-control">
              <input
                aria-label="中文字幕字号"
                type="range"
                min={18}
                max={44}
                step={2}
                value={draft.subtitle_size}
                onChange={(e) =>
                  setDraft({ ...draft, subtitle_size: Number(e.target.value) })
                }
              />
              <span>{draft.subtitle_size}px</span>
            </div>
          </div>
          <div className="subtitle-preview">
            <small>Learning begins with a question.</small>
            <p style={{ fontSize: draft.subtitle_size }}>
              理解，从一个问题开始。
            </p>
          </div>
          <label className="settings-row">
            <div>
              <strong>默认显示原文</strong>
              <small>韩语和英语原文保留，与中文译文对照。</small>
            </div>
            <input
              className="switch"
              type="checkbox"
              checked={draft.show_original}
              onChange={(e) =>
                setDraft({ ...draft, show_original: e.target.checked })
              }
            />
          </label>
        </section>
        <section className="settings-card">
          <div className="settings-title">
            <span className="quick-icon blue">
              <Languages size={21} />
            </span>
            <div>
              <h2>语言与术语</h2>
              <p>为语音识别提供课堂语言提示，中文翻译单独生成。</p>
            </div>
          </div>
          <button type="button" className="secondary" onClick={() => setDraft(classroomPreset(draft))}>应用韩英远场课堂预设（仍需点击保存）</button>
          <label className="settings-row">
            <div>
              <strong>语音识别语言提示</strong>
              <small>韩英课堂可选“韩语＋英语”；包含中文等语言时选“全部语言自动识别”。保存后下次开始录音生效。</small>
            </div>
            <select
              aria-label="语音识别语言提示"
              value={draft.asr_language_mode || "auto"}
              onChange={(e) => setDraft({ ...draft, asr_language_mode: e.target.value as ASRLanguageMode })}
            >
              {Object.entries(asrLanguageLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <div className="settings-row">
            <div>
              <strong>目标语言</strong>
              <small>第一版固定为简体中文。</small>
            </div>
            <span className="badge blue">简体中文</span>
          </div>
          <label className="terms-label">
            课程术语与人名
            <small>
              每行一个正确的韩语或英语词，也可以写“原文 = 译文”。人名无需填写译文；请按实际课程填写。下次开始录音时生效。
              识别热词含非 ASCII 字符时最多 15 个字符，纯英文最多 7 个单词；超长项仅用于翻译。
            </small>
            <textarea
              rows={6}
              maxLength={12000}
              value={terms}
              onChange={(e) => setTerms(e.target.value)}
              placeholder={
                "작업기억 = 工作记忆\n인지부하 = 认知负荷"
              }
            />
          </label>
          {preferences.asr_terms_status && (
            <div className="info-box" role="status">
              <div>
                <strong>已保存词表：{preferences.asr_terms_status.enabled_count} 个可用识别热词</strong>
                {!preferences.asr_terms_status.enabled_count && <p>当前没有可用热词。请填入本课经常识别错的词或人名的正确原文。</p>}
                {preferences.asr_terms_status.skipped.map((item) => (
                  <p key={item.index}>第 {item.index + 1} 项未单独用作识别热词：{item.reason}</p>
                ))}
              </div>
            </div>
          )}
          <label className="settings-row">
            <div>
              <strong>识别热词强度</strong>
              <small>人名、专业词可试用4；若其他词被错替换，降低强度或移除无关词。空词表时无效。</small>
            </div>
            <select aria-label="识别热词强度" value={draft.asr_hotword_weight ?? 2}
              onChange={(e) => setDraft({ ...draft, asr_hotword_weight: Number(e.target.value) as 2 | 3 | 4 })}>
              <option value={2}>2 · 轻度</option><option value={3}>3 · 标准</option><option value={4}>4 · 加强</option>
            </select>
          </label>
          <label className="terms-label">
            当前课程背景（可选）
            <small>最多400字。填写课程主题和正确原词、韩文人名，长词组也可放在这里。换课时请更新；仅写中文含义对韩语原词帮助有限。</small>
            <textarea aria-label="当前课程背景" rows={4} maxLength={400}
              value={draft.asr_context || ""}
              onChange={(e) => setDraft({ ...draft, asr_context: e.target.value })}
              placeholder="例如：인지심리학 수업. 주요 용어: 작업기억, 인지부하. 请替换为本课真实内容。" />
            <small>{Array.from(draft.asr_context || "").length} / 400 · 示例不会自动加入模型请求</small>
          </label>
          <label className="settings-row">
            <div>
              <strong>上下文辅助校正</strong>
              <small>根据韩语语法、近音词、同一会话前文和已填术语，生成待确认建议。只分析文字，不等于重听音频；每15秒最多安排一句抽查，额外调用文本模型。原文先显示，停止录音后可采纳为新版本。</small>
            </div>
            <input className="switch" type="checkbox" checked={draft.asr_assist_enabled || false}
              onChange={(e) => setDraft({ ...draft, asr_assist_enabled: e.target.checked })} />
          </label>
        </section>
        <section className="settings-card">
          <div className="settings-title">
            <span className="quick-icon orange">
              <ShieldCheck size={21} />
            </span>
            <div>
              <h2>音频与隐私</h2>
              <p>你决定什么值得留下。</p>
            </div>
          </div>
          <label className="settings-row">
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
              <strong>新会话默认保留音频</strong>
              <small>创建会话时仍可更改，仅在真实模式生效。</small>
            </div>
            <input
              className="switch"
              type="checkbox"
              checked={draft.retain_audio}
              onChange={(e) =>
                setDraft({ ...draft, retain_audio: e.target.checked })
              }
            />
          </label>
          <div className="settings-row">
            <div>
              <strong>音频保留期限</strong>
              <small>由服务器管理员配置，到期后台清理。</small>
            </div>
            <span>{draft.audio_retention_days} 天</span>
          </div>
          <div className="info-box">
            <BookOpen size={17} />
            <span>
              默认保存文字，不长期保存原始音频。会后校正生成新版本，并保留旧引用的可追溯性。
            </span>
          </div>
        </section>
        <section className="settings-card">
          <div className="settings-title">
            <span className="quick-icon purple">
              <Monitor size={21} />
            </span>
            <div>
              <h2>模型状态</h2>
              <p>仅显示服务器配置状态，不代表真实 API 已验证。</p>
            </div>
          </div>
          <div className="model-status">
            <span className={`badge ${draft.real_ready ? "green" : "amber"}`}>
              {draft.real_ready ? (
                <>
                  <Check size={13} />
                  已配置 · 尚未验证
                </>
              ) : (
                "真实模式尚未就绪"
              )}
            </span>
            <span className="tiny muted">
              地域：{draft.region || "服务器未报告"}
            </span>
          </div>
          <div className="model-table">
            {Object.entries(draft.models || {}).map(([name, value]) => (
              <div key={name}>
                <span>
                  {{
                    asr: "流式语音识别",
                    translation: "中文翻译",
                    summary: "阶段提取",
                    correction: "上下文辅助校正",
                    answer: "RAG 回答",
                    embedding: "向量模型",
                    rerank: "重排模型",
                  }[name] || name}
                </span>
                <code>{value}</code>
              </div>
            ))}
          </div>
          <div className="config-checks">
            <span>{draft.api_key_configured ? "✓" : "○"} 服务器 API 密钥</span>
            <span>{draft.workspace_configured ? "✓ 业务空间" : draft.real_ready ? "✓ 已使用显式接入地址" : "○ 业务空间或接入地址"}</span>
          </div>
          {draft.configuration_error && <p role="status" className="info-box">{draft.configuration_error.message}</p>}
          <p className="tiny muted">
            DASHSCOPE_API_KEY
            只应在服务器安全环境变量中配置。网页不会收集或保存模型密钥。模型可用性、权限和真实课堂效果需单独验证。
          </p>
        </section>
        <div className="info-box">
          单次录音上限为 105
          分钟，这是应用限制，不是账户消费上限。请保持页面在前台；不保证锁屏或后台录音。
        </div>
        <footer className="page-footer">
          <span>ClassBridge · v1.0</span>
          <span>基于 Minomeet 前端视觉体系 · MIT</span>
        </footer>
      </div>
    </div>
  );
}
