import { useState } from "react";
import {
  ArrowRight,
  AudioLines,
  BookOpen,
  CalendarDays,
  ChevronRight,
  Clock,
  FileText,
  GraduationCap,
  MessagesSquare,
  Mic,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Users,
  X,
} from "lucide-react";
import { formatDate, formatTime } from "../lib/api";
import type { Mode, Session } from "../lib/types";
export function Home({
  sessions,
  search,
  setSearch,
  create,
  select,
  library,
}: {
  sessions: Session[];
  search: string;
  setSearch: (v: string) => void;
  create: (kind?: string) => void;
  select: (s: Session) => void;
  library: () => void;
}) {
  const total = sessions.reduce((v, s) => v + (s.captured_ms ?? s.duration_ms ?? 0), 0);
  return (
    <div className="home page-scroll">
      <div className="page-width">
        <div className="page-heading">
          <div>
            <span className="eyebrow">YOUR LEARNING, CONNECTED</span>
            <h1>让每一刻理解，留下来。</h1>
            <p>把课堂、会议与对话，连接成属于你的知识。</p>
          </div>
          <span className="date-label">
            <CalendarDays size={16} />
            {new Date().toLocaleDateString("zh-CN", {
              month: "long",
              day: "numeric",
              weekday: "long",
            })}
          </span>
        </div>
        <section className="hero">
          <div className="hero-content">
            <span className="hero-pill">
              <span />
              韩语 · 英语 → 简体中文
            </span>
            <h2>
              专注听讲，
              <br />
              剩下的交给 ClassBridge。
            </h2>
            <p>
              实时双语字幕、阶段重点与有来源的 AI 问答，
              <br className="desktop-break" />
              让跨语言学习更从容。
            </p>
            <button className="hero-button" onClick={() => create("classroom")}>
              <Mic size={18} />
              开始一节新课堂
              <ArrowRight size={17} />
            </button>
            <small>
              <ShieldCheck size={13} />
              默认只保存文字 · 音频保留由你决定
            </small>
          </div>
          <div className="hero-art" aria-hidden="true">
            <div className="orb orb-one" />
            <div className="orb orb-two" />
            <div className="illustration-label">
              <AudioLines size={18} />
              从声音，到知识
            </div>
            <div className="illustration-card">
              <div className="mini-card-head">
                <span>CLASSBRIDGE</span>
                <span>字幕示意</span>
              </div>
              <div className="wave-decoration">
                {[
                  14, 27, 20, 39, 52, 32, 64, 42, 28, 49, 35, 20, 32, 17, 26,
                  12,
                ].map((n, i) => (
                  <i key={i} style={{ height: n }} />
                ))}
              </div>
              <div className="illustration-divider" />
              <span className="tiny">이제 함께 배워봅시다.</span>
              <strong>现在，让我们一起学习。</strong>
              <div className="mini-footer">
                <span>原文 + 中文</span>
                <span>
                  <Sparkles size={12} />
                  清晰理解
                </span>
              </div>
            </div>
            <div className="floating-note">
              <BookOpen size={17} />
              <span>每个知识点，都有出处</span>
            </div>
          </div>
        </section>
        <section className="quick-grid" aria-label="创建会话类型">
          {[
            {
              kind: "classroom",
              icon: GraduationCap,
              title: "课堂",
              text: "跟上讲授节奏，梳理知识脉络",
              color: "purple",
            },
            {
              kind: "meeting",
              icon: Users,
              title: "会议",
              text: "捕捉讨论重点，明确下一步",
              color: "blue",
            },
            {
              kind: "interview",
              icon: MessagesSquare,
              title: "访谈",
              text: "保留真实表达，发现关键洞察",
              color: "orange",
            },
          ].map(({ kind, icon: Icon, title, text, color }) => (
            <button
              key={kind}
              className="quick-card"
              onClick={() => create(kind)}
            >
              <span className={`quick-icon ${color}`}>
                <Icon size={23} />
              </span>
              <span>
                <strong>新建{title}</strong>
                <small>{text}</small>
              </span>
              <ChevronRight size={17} />
            </button>
          ))}
        </section>
        <section className="recent-section">
          <div className="section-heading">
            <div>
              <h2>
                最近会话 <span className="count-pill">{sessions.length}</span>
              </h2>
              <p>所有已保存的理解，都可以再次连接。</p>
            </div>
            <label className="search-field">
              <Search size={17} />
              <input
                aria-label="搜索会话与字幕"
                placeholder="搜索会话与字幕…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {search && (
                <button aria-label="清除搜索" onClick={() => setSearch("")}>
                  <X size={14} />
                </button>
              )}
            </label>
          </div>
          {sessions.length ? (
            <div className="session-list">
              {sessions.map((s) => (
                <button
                  className="session-row"
                  key={s.id}
                  onClick={() => select(s)}
                >
                  <span
                    className={`session-symbol ${s.kind === "meeting" ? "blue" : "purple"}`}
                  >
                    {s.kind === "meeting" ? (
                      <Users size={20} />
                    ) : s.kind === "interview" ? (
                      <MessagesSquare size={20} />
                    ) : (
                      <GraduationCap size={20} />
                    )}
                  </span>
                  <span className="session-title">
                    <strong>{s.title}</strong>
                    <small>
                      {formatDate(s.created_at)}
                      <span>·</span>
                      <Clock size={12} />
                      {formatTime(s.captured_ms ?? s.duration_ms)}
                      <span>·</span>
                      {s.kind === "meeting"
                        ? "会议"
                        : s.kind === "interview"
                          ? "访谈"
                          : "课堂"}
                    </small>
                  </span>
                  <span
                    className={`badge ${s.mode === "demo" ? "amber" : "green"}`}
                  >
                    {s.mode === "demo" ? "模拟演示" : "真实会话"}
                  </span>
                  <span className="row-state">
                    {s.status === "recording" ? "录音中" : "已保存"}
                  </span>
                  <ChevronRight size={17} />
                </button>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <span className="empty-icon">
                <FileText size={28} />
              </span>
              <h3>
                {search ? "未找到相关会话" : "你的第一份课堂笔记，即将诞生"}
              </h3>
              <p>
                {search
                  ? "试试其他标题或字幕关键词。"
                  : "创建一个模拟会话，体验双语字幕与知识问答。"}
              </p>
              {!search && (
                <button className="secondary" onClick={() => create()}>
                  <Plus size={16} />
                  创建模拟会话
                </button>
              )}
            </div>
          )}
        </section>
        <div className="home-bottom">
          <div>
            <BookOpen size={20} />
            <span>
              <strong>让讲义也参与理解</strong>
              <small>上传 PDF、PPTX 或 DOCX，让问答有据可依。</small>
            </span>
            <button className="text-button" onClick={library}>
              打开资料库
              <ArrowRight size={15} />
            </button>
          </div>
          <div>
            <Clock size={20} />
            <span>
              <strong>{Math.round(total / 60000)} 分钟</strong>
              <small>已保存的会话时长</small>
            </span>
          </div>
        </div>
        <footer className="page-footer">
          <span>
            <ShieldCheck size={13} />
            私人工作空间 · 音频与资料默认私有
          </span>
          <span>ClassBridge，让理解发生。</span>
        </footer>
      </div>
    </div>
  );
}
export function NewSession({
  kind: initial,
  close,
  submit,
  defaultRetain = false,
  retention = 7,
}: {
  kind: string;
  close: () => void;
  submit: (data: {
    title: string;
    kind: string;
    mode: Mode;
    retain_audio: boolean;
  }) => Promise<void>;
  defaultRetain?: boolean;
  retention?: number;
}) {
  const [kind, setKind] = useState(initial),
    [title, setTitle] = useState(""),
    [mode, setMode] = useState<Mode>("demo"),
    [retain, setRetain] = useState(defaultRetain),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) close();
      }}
    >
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-title"
      >
        <div className="modal-title">
          <span className="quick-icon purple">
            <AudioLines size={23} />
          </span>
          <button className="icon-button" aria-label="关闭" onClick={close}>
            <X size={20} />
          </button>
        </div>
        <h2 id="new-title">开始新的理解</h2>
        <p className="muted">先选择会话模式，准备好后再点击开始。</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              await submit({
                title:
                  title.trim() ||
                  `${kind === "meeting" ? "会议" : kind === "interview" ? "访谈" : "课堂"} · ${new Date().toLocaleDateString("zh-CN")}`,
                kind,
                mode,
                retain_audio: retain,
              });
            } catch (err) {
              setError(err instanceof Error ? err.message : "创建失败");
              setBusy(false);
            }
          }}
        >
          <div className="segmented">
            {[
              ["classroom", "课堂"],
              ["meeting", "会议"],
              ["interview", "访谈"],
            ].map(([k, t]) => (
              <button
                type="button"
                key={k}
                className={kind === k ? "active" : ""}
                onClick={() => setKind(k)}
              >
                {t}
              </button>
            ))}
          </div>
          <label>
            会话名称
            <input
              autoFocus
              maxLength={160}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例如：认知科学 · 第三讲"
            />
          </label>
          <div className="mode-choices">
            <button
              type="button"
              className={mode === "demo" ? "mode-choice chosen" : "mode-choice"}
              onClick={() => setMode("demo")}
            >
              <Sparkles size={20} />
              <strong>模拟演示</strong>
              <small>
                不调用付费 API
                <br />
                不使用麦克风
              </small>
            </button>
            <button
              type="button"
              className={mode === "real" ? "mode-choice chosen" : "mode-choice"}
              onClick={() => setMode("real")}
            >
              <Mic size={20} />
              <strong>真实课堂</strong>
              <small>
                使用麦克风
                <br />
                需服务器配置模型密钥
              </small>
            </button>
          </div>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={retain}
              disabled={mode === "demo"}
              onChange={(e) => setRetain(e.target.checked)}
            />
            <span>
              保留音频用于会后整理
              <small>
                {mode === "demo"
                  ? "模拟模式不保存音频"
                  : `私有保存，保留 ${retention} 天后自动清理。默认仅保存文字。`}
              </small>
            </span>
          </label>
          {error && (
            <div className="error-box" role="alert">
              {error}
            </div>
          )}
          <button className="primary full" disabled={busy}>
            {busy ? "正在创建…" : "创建会话"}
            <ArrowRight size={17} />
          </button>
        </form>
      </section>
    </div>
  );
}
