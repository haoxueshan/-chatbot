import { translationLanguageLabel, translationDirection } from "../lib/translationLanguages";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown,
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  Download,
  Expand,
  Eye,
  EyeOff,
  FileText,
  Focus,
  Languages,
  LoaderCircle,
  MessageSquare,
  Mic,
  PanelRightClose,
  PanelRightOpen,
  RefreshCw,
  Sparkles,
  Square,
  Trash2,
  Volume2,
  Wifi,
  X,
} from "lucide-react";
import { formatDate, formatTime, post, request } from "../lib/api";
import { useLive } from "../lib/useLive";
import { buildTimeline } from "../lib/timeline";
import { recognitionStatus } from "../lib/captureHealth";
import { asrLanguageLabels } from "../lib/asrLanguages";
import type { Citation, Preferences, Session, Stage } from "../lib/types";
import { Chat } from "./Chat";
import { DocumentPreview, Library } from "./Library";

function sourceReferences(
  item: unknown,
): { sentence_id: string; source_revision: number }[] {
  if (!item || typeof item !== "object") return [];
  const value = (item as Record<string, unknown>).sources;
  if (!Array.isArray(value)) return [];
  return value.filter(
    (source): source is { sentence_id: string; source_revision: number } =>
      source != null &&
      typeof source.sentence_id === "string" &&
      typeof source.source_revision === "number",
  );
}
function readable(item: unknown): string {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return "";
  const v = item as Record<string, unknown>;
  const text = String(
    v.text ||
      v.summary ||
      v.description ||
      v.term ||
      v.title ||
      v.topic ||
      v.content ||
      "",
  );
  const meaning = v.definition || v.meaning;
  return `${text}${meaning ? `：${meaning}` : ""}${v.owner ? ` · 负责人：${v.owner}` : ""}${v.due_original ? ` · 日期原话：${v.due_original}（${v.due_basis || "待确认"}）` : ""}`;
}
function StagePanel({
  stages,
  generate,
  busy,
  jump,
}: {
  stages: Stage[];
  generate: () => void;
  busy: boolean;
  jump: (id: string, revision?: number) => void;
}) {
  return (
    <div className="stage-panel">
      <div className="panel-intro">
        <span className="eyebrow">让重点，自然浮现</span>
        <p>每三分钟从稳定原文中提取。每个结论都保留来源版本。</p>
        <button className="secondary full" disabled={busy} onClick={generate}>
          {busy ? (
            <LoaderCircle size={15} className="spin" />
          ) : (
            <RefreshCw size={15} />
          )}
          生成当前阶段重点
        </button>
      </div>
      {stages.length ? (
        stages.map((s, index) => (
          <article className="stage-card" key={s.id}>
            <div className="stage-number">
              <span>{String(index + 1).padStart(2, "0")}</span>
              <small>阶段重点</small>
            </div>
            <h3>{s.topic && !/^(none|null|undefined)$/i.test(s.topic.trim()) ? s.topic : `阶段 ${index + 1}`}</h3>
            <p>{s.summary}</p>
            {s.superseded && <p className="info-box">历史阶段 · 来源已更新，以上结论基于旧版本，请核对新版阶段；原句引用仍可查看。</p>}
            {[
              ["知识点", s.knowledge_points],
              ["术语", s.terms],
              ["明确决议", s.decisions],
              ["行动项", s.action_items],
            ].map(
              ([label, items]) =>
                Array.isArray(items) &&
                !!items.length && (
                  <div className="stage-items" key={String(label)}>
                    <h4>{String(label)}</h4>
                    <ul>
                      {items.map((v, i) => (
                        <li key={i}>
                          {readable(v)}
                          {sourceReferences(v).length > 0 && (
                            <div className="source-chips">
                              {sourceReferences(v).map(
                                (source: {
                                  sentence_id: string;
                                  source_revision: number;
                                }) => (
                                  <button
                                    key={`${source.sentence_id}:${source.source_revision}`}
                                    onClick={() =>
                                      jump(
                                        source.sentence_id,
                                        source.source_revision,
                                      )
                                    }
                                  >
                                    <BookOpen size={11} /> 原句 v
                                    {source.source_revision}
                                  </button>
                                ),
                              )}
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                ),
            )}
            {!!s.source_sentence_ids?.length && (
              <div className="source-chips">
                {s.source_sentence_ids.map((id, i) => (
                  <button
                    onClick={() =>
                      jump(
                        id,
                        s.sources?.find((source) => source.sentence_id === id)
                          ?.source_revision,
                      )
                    }
                    key={id}
                  >
                    <BookOpen size={11} />
                    来源 {i + 1}
                  </button>
                ))}
              </div>
            )}
          </article>
        ))
      ) : (
        <div className="empty-state compact">
          <Sparkles size={29} />
          <h3>先听懂，再提炼</h3>
          <p>会话开始后，稳定原文会形成阶段重点。也可以手动生成。</p>
        </div>
      )}
      <div className="panel-footnote">
        未明确提及的负责人和日期保留为空；相对日期以原话为准。
      </div>
    </div>
  );
}

export function SessionView({
  session,
  preferences,
  onActivity,
  refresh,
  back,
  notify,
  openSession,
  deleted,
}: {
  session: Session;
  preferences: Preferences;
  onActivity: (active: boolean) => void;
  refresh: () => void;
  back: () => void;
  notify: (m: string) => void;
  openSession: (id: string) => void;
  deleted: () => void;
}) {
  const [microphoneId, setMicrophoneId] = useState(() => {
    try { return typeof window === "undefined" ? "" : window.localStorage.getItem("classbridge.microphone.v1") || ""; }
    catch { return ""; }
  });
  const [microphones, setMicrophones] = useState<{ deviceId: string; label: string }[]>([]);
  const [deviceError,setDeviceError]=useState("");
  const deviceGeneration=useRef(0);
  const devicesMounted=useRef(true);
  const live = useLive(session, refresh, {
    deviceId: microphoneId,
    processingMode: preferences.audio_processing_mode || "standard",
  });
  const refreshMicrophones = () => {
    const generation=++deviceGeneration.current;
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) {
      setDeviceError("浏览器暂不支持设备列表；请使用安全连接，可选择系统默认麦克风。");return;
    }
    void navigator.mediaDevices.enumerateDevices().then((items) => {
      if(!devicesMounted.current || generation!==deviceGeneration.current)return;
      setMicrophones(items.filter((item) => item.kind === "audioinput" && item.deviceId)
        .map((item) => ({ deviceId: item.deviceId, label: item.label })));
      setDeviceError("");
    }).catch(() => {if(devicesMounted.current && generation===deviceGeneration.current)setDeviceError("无法读取麦克风列表，请检查浏览器权限并重试；没有自动切换设备。");});
  };
  useEffect(() => {
    if (session.mode !== "real" || typeof navigator === "undefined") return;
    devicesMounted.current=true;
    refreshMicrophones();
    navigator.mediaDevices?.addEventListener?.("devicechange", refreshMicrophones);
    return () => {devicesMounted.current=false;deviceGeneration.current++;navigator.mediaDevices?.removeEventListener?.("devicechange", refreshMicrophones);};
  }, [session.mode]);
  useEffect(()=>{if(session.mode==="real" && live.active)refreshMicrophones();},[live.preparing,live.active]);
  const chooseMicrophone = (id: string) => {
    if(live.active || live.settling)return;
    setMicrophoneId(id);
    try { window.localStorage.setItem("classbridge.microphone.v1", id); }
    catch { /* private mode/storage restrictions */ }
  };
  const timeline = useMemo(() => buildTimeline(live.segments, live.gaps), [live.segments, live.gaps]);
  const [tab, setTab] = useState<"subtitles" | "summary" | "chat">("subtitles"),
    [sideTab, setSideTab] = useState<"summary" | "chat">("summary"),
    [sidebar, setSidebar] = useState(true),
    [showOriginal, setShowOriginal] = useState(preferences.show_original),
    [focus, setFocus] = useState(false),
    [following, setFollowing] = useState(true),
    [selectedSource, setSelectedSource] = useState<Citation | null>(null),
    [busy, setBusy] = useState(false),
    [exporting, setExporting] = useState(false),
    [exportBusy, setExportBusy] = useState(false),
    [documentsOpen, setDocumentsOpen] = useState(false);
  const list = useRef<HTMLDivElement>(null),
    end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    onActivity(live.active || live.settling);
    return () => onActivity(false);
  }, [live.active, live.settling, onActivity]);
  useEffect(() => {
    if (following && list.current)
      list.current.scrollTo({ top: list.current.scrollHeight, behavior: "auto" });
  }, [timeline, following]);
  useEffect(() => {
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);
  const jump = (sentenceId: string) => {
    setTab("subtitles");
    setFollowing(false);
    setTimeout(() => {
      const target = document.getElementById(`sentence-${sentenceId}`);
      target?.scrollIntoView({ behavior: "smooth", block: "center" });
      target?.classList.add("highlight-source");
      setTimeout(() => target?.classList.remove("highlight-source"), 5000);
    }, 80);
  };
  const citation = (c: Citation) => {
    setSelectedSource(c);
    if (
      c.kind === "sentence" &&
      (!c.session_id || c.session_id === session.id) &&
      c.sentence_id
    )
      jump(c.sentence_id);
  };
  const jumpEvidence = async (id: string, revision?: number) => {
    jump(id);
    if (revision) {
      try {
        const versions = await request<
          { text: string; source_revision: number }[]
        >(`/sessions/${session.id}/versions/${encodeURIComponent(id)}`);
        const source = versions.find((v) => v.source_revision === revision);
        if (source)
          setSelectedSource({
            id,
            kind: "sentence",
            sentence_id: id,
            session_id: session.id,
            source_revision: revision,
            quote: source.text,
          });
      } catch (e) {
        notify(e instanceof Error ? e.message : "无法读取来源版本");
      }
    }
  };
  const summarize = async () => {
    setBusy(true);
    try {
      await post(`/sessions/${session.id}/summarize`);
      notify("已提交阶段提取任务");
      refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : "提取失败");
    } finally {
      setBusy(false);
    }
  };
  const audioAvailable =
    ["available", "ready", "saved"].includes(session.audio_status || "") ||
    !!session.audio_assets?.length;
  const downloadReport = async (format: string) => {
    setExporting(false);
    setExportBusy(true);
    try {
      const job = await post<{ task_id: string }>(
        `/sessions/${session.id}/exports`,
        { format },
      );
      notify("已提交后台导出任务");
      for (let i = 0; i < 60; i++) {
        const state = await request<{
          status: string;
          error?: string;
          download_url?: string;
        }>(`/sessions/${session.id}/exports/${job.task_id}`);
        if (state.status === "completed" && state.download_url) {
          const a = document.createElement("a");
          a.href = state.download_url;
          a.download = "";
          a.click();
          notify("报告已生成");
          return;
        }
        if (state.status === "failed")
          throw new Error(state.error || "导出失败");
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      notify("导出仍在后台处理，完成后可从后台任务列表下载。");
      refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : "导出失败");
    } finally {
      setExportBusy(false);
    }
  };
  const target = session.target_language || "zh-CN";
  const targetLabel = translationLanguageLabel(target);
  return (
    <div className={`session-view ${focus ? "focus-mode" : ""}`}>
      <div className="session-heading">
        <div>
          <button
            className="back-link"
            onClick={back}
            disabled={live.active || live.settling}
          >
            <ChevronLeft size={14} />
            全部会话
          </button>
          <h1>{session.title}</h1>
          <div className="session-meta">
            <span>{formatDate(session.created_at)}</span>
            <span>·</span>
            <span>
              <Languages size={13} />
              {session.mode === "demo" ? `韩语 / 英语 → ${targetLabel}` : (
                live.active
                  ? `当前识别提示：${live.preparing ? "准备中" : live.asrLanguageMode ? asrLanguageLabels[live.asrLanguageMode] : "服务端未报告"} → ${targetLabel}`
                  : `下次识别提示：${asrLanguageLabels[preferences.asr_language_mode || "auto"]} → ${targetLabel}`
              )}
            </span>
            {live.active && live.translationTarget && <span>服务端目标：{translationLanguageLabel(live.translationTarget)}</span>}
            <span
              className={`badge ${session.mode === "demo" ? "amber" : "blue"}`}
            >
              {session.mode === "demo" ? "模拟演示" : "真实模式"}
            </span>
          </div>
        </div>
        <div className="session-tools">
          <button
            className="icon-button"
            title="本会话资料"
            aria-label="本会话资料"
            disabled={live.active || live.settling}
            onClick={() => setDocumentsOpen(true)}
          >
            <BookOpen size={17} />
          </button>
          <button
            className="icon-button danger"
            title="删除会话"
            aria-label="删除会话"
            disabled={live.active || live.settling}
            onClick={async () => {
              if (
                confirm(
                  "确定删除整个会话？字幕、音频、资料及派生内容将被删除。",
                )
              ) {
                try {
                  await request(`/sessions/${session.id}`, {
                    method: "DELETE",
                  });
                  deleted();
                } catch (e) {
                  notify(e instanceof Error ? e.message : "删除失败");
                }
              }
            }}
          >
            <Trash2 size={17} />
          </button>
          <div className="dropdown">
            <button
              className="secondary"
              disabled={exportBusy}
              onClick={() => setExporting(!exporting)}
            >
              <Download size={15} />
              <span>{exportBusy ? "生成中" : "导出"}</span>
              <ChevronDown size={13} />
            </button>
            {exporting && (
              <div className="dropdown-menu">
                {[
                  ["md", "Markdown"],
                  ["txt", "纯文本 TXT"],
                  ["pdf", "PDF 报告"],
                ].map(([value, label]) => (
                  <a
                    key={value}
                    download
                    href={`/api/sessions/${session.id}/export?format=${value}`}
                    onClick={(event) => {
                      event.preventDefault();
                      void downloadReport(value);
                    }}
                  >
                    {label}
                  </a>
                ))}
              </div>
            )}
          </div>
          <button
            className="icon-button"
            title={focus ? "退出专注" : "专注阅读"}
            aria-label="切换专注阅读"
            onClick={() => setFocus(!focus)}
          >
            {focus ? <Expand size={18} /> : <Focus size={18} />}
          </button>
          <button
            className="icon-button desktop-side-toggle"
            title={sidebar ? "收起侧栏" : "展开侧栏"}
            aria-label="切换侧栏"
            onClick={() => setSidebar(!sidebar)}
          >
            {sidebar ? (
              <PanelRightClose size={18} />
            ) : (
              <PanelRightOpen size={18} />
            )}
          </button>
        </div>
      </div>
      <div
        className={`mode-banner ${session.mode === "demo" ? "demo" : "real"}`}
      >
        <span>
          {session.mode === "demo" ? <Sparkles size={15} /> : <Mic size={15} />}
          <strong>
            {session.mode === "demo"
              ? "模拟演示，不调用付费 API"
              : "真实语音理解"}
          </strong>
          {live.active && !live.preparing && live.translationTarget && (
            <small>本次翻译：{translationLanguageLabel(live.translationTarget)}</small>
          )}
          {session.mode === "real" && live.active && !live.preparing && live.asrEnhancement && (
            <small>本次热词 {live.asrEnhancement.hotword_count} 项 · 课程背景 {live.asrEnhancement.context_chars} 字</small>
          )}
          <span>
            {session.mode === "demo"
              ? "演示字幕带模拟标记，不使用麦克风。"
              : "保持页面在前台，不保证锁屏或后台录音。"}
          </span>
        </span>
        <span className="saved-indicator">
          <Check size={14} />
          稳定字幕自动保存
        </span>
      </div>
      {live.preparing && (
        <div className="mode-banner real" role="status">
          正在准备识别服务，请稍候再说话；准备完成后开始采音计时。
        </div>
      )}
      {live.active && !live.preparing && live.health && (
        <details className="info-box capture-health">
          <summary role="status">{recognitionStatus(live.health)}</summary>
          <p className="tiny muted">
            服务器已收到 {(live.health.received_audio_ms / 1000).toFixed(1)} 秒音频 ·
            已向识别服务发送 {(live.health.sent_audio_ms / 1000).toFixed(1)} 秒 ·
            待转发 {live.health.queued_audio_ms} 毫秒 ·
            输入电平 {live.health.input_dbfs} dBFS
          </p>
          <p className="tiny muted">电平表示声音强弱，不能据此判断是否有人说话。已发送也不代表模型已完成识别。</p>
        </details>
      )}
      {live.notice && (
        <div className="session-notice" role="alert">
          <span>{live.notice}</span>
          <button
            className="icon-button"
            aria-label="关闭提示"
            onClick={() => live.setNotice("")}
          >
            <X size={15} />
          </button>
        </div>
      )}
      <div className="mobile-tabs">
        {[
          ["subtitles", "双语字幕", FileText],
          ["summary", "阶段重点", Sparkles],
          ["chat", "AI 问答", MessageSquare],
        ].map(([key, label, Icon]) => {
          const I = Icon as typeof FileText;
          return (
            <button
              key={String(key)}
              className={tab === key ? "active" : ""}
              onClick={() => setTab(key as typeof tab)}
            >
              <I size={16} />
              {String(label)}
            </button>
          );
        })}
      </div>
      <div
        className={`session-body ${!sidebar ? "side-collapsed" : ""} mobile-${tab}`}
      >
        <section className="subtitle-panel">
          <div className="subtitle-toolbar">
            <h2>
              <AudioMark />
              双语字幕<span>{live.segments.length} 个片段</span>
            </h2>
            <button
              className="text-button"
              aria-label={showOriginal ? "隐藏原文" : "显示原文"}
              onClick={() => setShowOriginal(!showOriginal)}
            >
              {showOriginal ? <Eye size={15} /> : <EyeOff size={15} />}
              <span>{showOriginal ? "显示原文" : "隐藏原文"}</span>
            </button>
          </div>
          <div
            className="subtitle-list"
            role="region"
            aria-label="双语字幕记录"
            tabIndex={0}
            ref={list}
            onScroll={() => {
              const el = list.current;
              if (el)
                setFollowing(
                  el.scrollHeight - el.scrollTop - el.clientHeight < 80,
                );
            }}
          >
            {!live.segments.length && (
              <div className="subtitle-empty">
                <span className="empty-mic">
                  <Mic size={35} />
                </span>
                <span className="eyebrow">READY WHEN YOU ARE</span>
                <h2>准备好，听见新知识。</h2>
                <p>
                  {session.mode === "demo"
                    ? "点击下方「开始模拟」，体验韩英课堂的双语字幕。"
                    : "点击「开始录音」后申请麦克风权限，原文与译文将在这里实时出现。"}
                </p>
                <div>
                  <span>
                    <Languages size={16} />
                    保留韩英原文
                  </span>
                  <span>
                    <BookOpen size={16} />
                    引用回到来源
                  </span>
                </div>
              </div>
            )}
            {timeline.map((item) => {
              if (item.kind === "gap") return (
                <div className="gap-marker" key={item.key}>
                  {formatTime(item.time)} · 采集缺口 · {item.gap.message || "此时段音频不可恢复"}
                </div>
              );
              const s = item.segment;
              return (
              <article
                className={`subtitle-segment ${!s.source_final ? "is-partial" : ""}`}
                id={`sentence-${s.sentence_id}`}
                key={item.key}
              >
                <div className="segment-meta">
                  <span className="segment-time">
                    {formatTime(s.start_ms)}
                    <span>—</span>
                    {formatTime(s.end_ms)}
                  </span>
                  <span className="segment-status">
                    {s.source_status === "interrupted" ? "识别未完成 · 待确认" : s.source_final ? (
                      <><Check size={12} />原文已定稿</>
                    ) : "识别中 · 临时字幕"}
                  </span>
                  {s.mode === "demo" && <span className="demo-mark">模拟</span>}
                  <span className="revision">v{s.source_revision}</span>
                  {s.speaker != null && (
                    <button
                      className="text-button"
                      disabled={live.active || live.settling}
                      title="说话人编号不等于真实姓名，点击人工映射"
                      onClick={async () => {
                        const name = prompt(
                          `为说话人 ${s.speaker} 设置显示名称（人工确认）`,
                          session.speaker_names?.[s.speaker!] || "",
                        );
                        if (name !== null) {
                          try {
                            await request(`/sessions/${session.id}/speakers`, {
                              method: "PATCH",
                              body: JSON.stringify({
                                mapping: {
                                  ...session.speaker_names,
                                  [s.speaker!]: name,
                                },
                              }),
                            });
                            refresh();
                          } catch (e) {
                            notify(e instanceof Error ? e.message : "映射失败");
                          }
                        }
                      }}
                    >
                      {session.speaker_names?.[s.speaker] ||
                        `说话人 ${s.speaker}`}
                    </button>
                  )}
                </div>
                {(showOriginal || s.source_status === "interrupted") && (
                  <p className="source-text" lang="und">
                    {!s.source_final && s.stable_preview !== undefined ? <>
                      <span className="stable-source-preview" title="相对稳定预览，仍可被识别服务修订">{s.stable_preview}</span>
                      <span className="unstable-source-tail" title="正在变化的原文">{s.unstable_tail}</span>
                    </> : s.text || "等待原文…"}
                  </p>
                )}
                <p
                  lang={target}
                  dir={translationDirection(target)}
                  className={`translation-text ${!s.translation_final ? "temporary" : ""}`}
                  style={{ fontSize: preferences.subtitle_size || 24 }}
                >
                  {s.source_status === "interrupted" ? "对应原文尚未正式确认" : s.translation_status === "failed" ? "翻译失败，原文已保留" : s.translation || (
                    <span className="translation-waiting">
                      <span className="typing-dots">•••</span> 正在翻译为{targetLabel}…
                    </span>
                  )}
                </p>
                {s.translation_final && <small className="translation-status">{targetLabel}翻译已完成</small>}
                {s.translation && !s.translation_final && s.translation_status !== "failed" && (
                  <small className="temporary-label">
                    {s.source_final ? `正在翻译为${targetLabel}… · 当前为临时译文` : s.preview_source_text ? "临时翻译预览 · 仅对应已翻译部分，可被替换" : "临时译文 · 会随原文修订"}
                  </small>
                )}
                {s.provenance === "user_correction" && <button className="text-button" onClick={() => void jumpEvidence(s.sentence_id, s.source_revision - 1)}>
                  已人工采纳校正 · 查看校正前原文 v{s.source_revision - 1}
                </button>}
              </article>
              );
            })}
            <div ref={end} className="subtitle-bottom" />
          </div>
          {!following && !!live.segments.length && (
            <button
              className="follow-button"
              onClick={() => {
                setFollowing(true);
                end.current?.scrollIntoView({ behavior: "smooth" });
              }}
            >
              <ArrowDown size={14} />
              回到最新
            </button>
          )}
          <div className="subtitle-footer">
            <span>
              <Check size={13} />
              已保存的内容可刷新恢复
            </span>
            <div>
              <button
                className="text-button"
                disabled={live.active || live.settling || !live.segments.length}
                onClick={async () => {
                  if (
                    confirm("确定清空此会话的字幕与派生内容？此操作不可撤销。")
                  ) {
                    try {
                      const result = await request<{event_seq?:number}>(`/sessions/${session.id}/segments`, {
                        method: "DELETE",
                      });
                      live.clear(result.event_seq);
                      refresh();
                    } catch (e) {
                      notify(e instanceof Error ? e.message : "清空失败");
                    }
                  }
                }}
              >
                <Trash2 size={13} />
                清空
              </button>
            </div>
          </div>
        </section>
        <aside className="insight-sidebar">
          <div className="insight-tabs">
            <button
              className={sideTab === "summary" ? "active" : ""}
              onClick={() => setSideTab("summary")}
            >
              <Sparkles size={16} />
              阶段重点
            </button>
            <button
              className={sideTab === "chat" ? "active" : ""}
              onClick={() => setSideTab("chat")}
            >
              <MessageSquare size={16} />
              AI 问答
            </button>
          </div>
          <div
            className={`summary-container ${sideTab === "summary" ? "side-active" : ""}`}
          >
            <StagePanel
              stages={session.stages || []}
              busy={busy}
              generate={() => void summarize()}
              jump={(id, revision) => void jumpEvidence(id, revision)}
            />
          </div>
          <div
            className={`chat-container ${sideTab === "chat" ? "side-active" : ""}`}
          >
            <Chat
              sessionId={session.id}
              mode={session.mode}
              onCitation={citation}
            />
          </div>
        </aside>
      </div>
      {session.mode === "real" && (
        <details className="microphone-options">
          <summary>麦克风与拾音设置 · {live.asrAcousticProfile === "near" ? "本次近场" : live.asrAcousticProfile === "far" ? "本次远场" : "等待识别场景确认"}</summary>
          <div className="microphone-controls">
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
            本次识别：{live.asrAcousticProfile === "near" ? "近场" : live.asrAcousticProfile === "far" ? "远场" : "尚未收到服务端确认"} ·
            下次请求：{preferences.audio_processing_mode === "natural" ? "浏览器原声模式" : "浏览器标准处理"}
          </span>
          {deviceError && <span role="status">{deviceError}</span>}
          {live.appliedAudio && <span className="tiny muted">浏览器实际报告：{([['echoCancellation','回声消除'],['noiseSuppression','降噪'],['autoGainControl','自动增益']] as const).map(([key,label])=>`${label}${live.appliedAudio?.[key]===undefined?'未报告':live.appliedAudio[key]?'开':'关'}`).join(' · ')}（硬件处理未知）</span>}
          {live.active && live.audioQuality && <span className="tiny muted">峰值 {live.inputPeak.toFixed(2)} / {Math.round(live.audioQuality.peak_window_ms)}ms窗口 · 电平不是识别置信度</span>}
          {live.active && live.audioQuality?.possible_clipping && <strong role="status">输入连续接近满幅，可能削波；请检查设备增益</strong>}
          </div>
        </details>
      )}
      <div className="capture-bar" aria-label="录音控制">
        <div className="capture-left">
          <span
            className={`connection-dot ${live.connection === "已连接" ? "connected" : ""}`}
          />
          <div>
            <strong>{live.connection}</strong>
            <small>
              <Wifi size={11} />
              发送队列 {live.queue} 帧
            </small>
          </div>
          <div className="capture-divider" />
          <span className="capture-time" title="累计采音时长，不含暂停间隔；字幕保留原始时间轴">
            {formatTime(live.elapsed)}
            <small>/ 105:00</small>
          </span>
          {session.mode === "real" && (
            <div
              className="volume-meter"
              title={`真实麦克风音量 ${Math.round(live.level * 100)}%`}
            >
              <Volume2 size={16} />
              <div>
                <i style={{ width: `${Math.min(100, live.level * 400)}%` }} />
              </div>
            </div>
          )}
        </div>
        <div className="capture-main">
          {live.active ? (
            <button className="stop-button" onClick={() => live.stop()}>
              <Square size={16} fill="currentColor" />
              {live.preparing ? "取消准备" : `停止${session.mode === "demo" ? "模拟" : "录音"}`}
            </button>
          ) : (
            <button
              className="primary capture-start"
              disabled={
                live.settling ||
                live.connection !== "已连接" ||
                live.elapsed >= 105 * 60 * 1000
              }
              onClick={() => void live.start()}
            >
              {session.mode === "demo" ? (
                <Sparkles size={18} />
              ) : (
                <Mic size={18} />
              )}
              <span>{session.mode === "demo" ? "开始模拟" : "开始录音"}</span>
            </button>
          )}
          {live.connection !== "已连接" && !live.active && (
            <button className="secondary" onClick={live.retry}>
              重新连接
            </button>
          )}
        </div>
        <div className="capture-right">
          <span>
            {session.retain_audio
              ? session.mode === "demo"
                ? "模拟不保存音频"
                : `音频保留 ${preferences.audio_retention_days} 天`
              : "仅保存文字"}
          </span>
          <button
            className="text-button"
            disabled={live.active || live.settling || !audioAvailable}
            title={
              audioAvailable
                ? "使用保留音频生成独立新版本"
                : "没有可用音频；请在创建真实会话前开启音频保留"
            }
            onClick={async () => {
              try {
                await post(`/sessions/${session.id}/reprocess`);
                notify("会后校正任务已提交，新版本不会覆盖旧引用");
                refresh();
              } catch (e) {
                notify(e instanceof Error ? e.message : "无法进行会后校正");
              }
            }}
          >
            <RefreshCw size={12} />
            会后校正
          </button>
        </div>
      </div>
      {!!Object.keys(live.latency).length && (
        <div className="latency-strip">
          {session.mode === "demo"
            ? "模拟时序（非真实延迟）："
            : "服务端测量（不含浏览器绘制）：原文/预览首字距语音起点；正式结果距语音终点；排队/模型为独立耗时"}
          {Object.entries(live.latency)
            .filter(
              ([key, value]) =>
                [
                  "source_first_ms",
                  "source_final_ms",
                  "translation_first_ms",
                  "translation_final_ms",
                  "preview_first_ms",
                  "translation_queue_ms",
                  "translation_model_first_ms",
                  "translation_model_final_ms",
                ].includes(key) && typeof value === "number",
            )
            .map(([key, value]) => (
              <span key={key}>
                {(
                  {
                    source_first_ms: "原文首字",
                    source_final_ms: "原文定稿",
                    translation_first_ms: "译文首字",
                    translation_final_ms: "译文定稿",
                    preview_first_ms: "临时译文首字",
                    translation_queue_ms: "后台排队",
                    translation_model_first_ms: "模型首字耗时",
                    translation_model_final_ms: "模型完成耗时",
                  } as Record<string, string>
                )[key] || key}{" "}
                {Math.max(0, Math.round(Number(value)))}ms
              </span>
            ))}
        </div>
      )}
      {!!session.tasks?.some(
        (t) =>
          t.kind === "export" || t.status === "failed" || t.status === "retry",
      ) && (
        <details className="task-status">
          <summary>
            后台任务与导出 ·{" "}
            {
              session.tasks.filter(
                (t) => t.status === "failed" || t.status === "retry",
              ).length
            }{" "}
            项需要关注
          </summary>
          {session.tasks
            .filter(
              (t) =>
                t.kind === "export" ||
                t.status === "failed" ||
                t.status === "retry",
            )
            .map((t) => (
              <p key={t.id}>
                {(
                  {
                    translate: "翻译",
                    index_segment: "字幕索引",
                    summarize: "阶段提取",
                    reprocess: "会后校正",
                    export: "导出",
                  } as Record<string, string>
                )[t.kind] || t.kind}{" "}
                ·{" "}
                {(
                  {
                    retry: "有限重试中",
                    failed: "失败",
                    completed: "已完成",
                    pending: "排队中",
                    running: "处理中",
                  } as Record<string, string>
                )[t.status] || t.status}
                {t.error && `：${t.error}`}
                {t.kind === "export" && t.status === "completed" && (
                  <a
                    className="text-button"
                    href={`/api/sessions/${session.id}/exports/${t.id}/file`}
                    download
                  >
                    下载报告
                  </a>
                )}
              </p>
            ))}
        </details>
      )}
      {selectedSource?.kind === "document" && selectedSource.document_id && (
        <DocumentPreview
          documentId={selectedSource.document_id}
          chunkId={selectedSource.chunk_id}
          page={selectedSource.page}
          quote={selectedSource.quote}
          close={() => setSelectedSource(null)}
        />
      )}
      {documentsOpen && (
        <div className="modal-backdrop">
          <section
            className="modal session-documents"
            role="dialog"
            aria-modal="true"
            aria-label="本会话资料"
          >
            <div className="modal-title">
              <h2>本会话资料</h2>
              <button
                className="icon-button"
                aria-label="关闭会话资料"
                onClick={() => setDocumentsOpen(false)}
              >
                <X size={20} />
              </button>
            </div>
            <Library
              sessionId={session.id}
              defaultMode={session.mode}
              notify={notify}
            />
          </section>
        </div>
      )}
      {selectedSource?.kind === "sentence" && (
        <div className="source-popover" role="dialog" aria-label="原文引用">
          <div>
            <strong>
              原文证据 · 版本 {selectedSource.source_revision || 1}
            </strong>
            <button
              className="icon-button"
              aria-label="关闭引用"
              onClick={() => setSelectedSource(null)}
            >
              <X size={16} />
            </button>
          </div>
          <blockquote>{selectedSource.quote}</blockquote>
          {selectedSource.session_id &&
            selectedSource.session_id !== session.id && (
              <button
                className="text-button"
                disabled={live.active || live.settling}
                onClick={() => {
                  openSession(selectedSource.session_id!);
                  setSelectedSource(null);
                }}
              >
                打开来源会话
              </button>
            )}
        </div>
      )}
    </div>
  );
}
function AudioMark() {
  return (
    <span className="audio-mark">
      <i />
      <i />
      <i />
      <i />
    </span>
  );
}
