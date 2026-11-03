import { translationLanguages, type TargetLanguage } from "../lib/translationLanguages";
import { useState } from "react";
import {
  ArrowRight,
  AudioLines,
  BookOpen,
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
  Settings2,
  Upload,
} from "lucide-react";
import { formatDate, formatTime } from "../lib/api";
import type { Mode, Session } from "../lib/types";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { Badge } from "./ui/badge";
import { Dialog } from "./ui/dialog";

export function Home({
  sessions,
  search,
  setSearch,
  create,
  select,
  library,
  settings,
}: {
  sessions: Session[];
  search: string;
  setSearch: (value: string) => void;
  create: (kind?: string) => void;
  select: (session: Session) => void;
  library: () => void;
  settings: () => void;
}) {
  const total = sessions.reduce(
    (value, session) =>
      value + (session.captured_ms ?? session.duration_ms ?? 0),
    0,
  );
  const realCount = sessions.filter(
    (session) => session.mode === "real",
  ).length;
  return (
    <div className="home page-scroll">
      <div className="page-width">
        <div className="page-heading">
          <div>
            <span className="eyebrow">工作台</span>
            <h1>欢迎回来</h1>
            <p>开始一段记录，或继续整理你的课堂与会议。</p>
          </div>
          <Button variant="secondary" onClick={library}>
            <Upload size={17} />
            导入资料
          </Button>
        </div>
        <section className="dashboard-actions" aria-label="创建会话类型">
          {[
            {
              kind: "classroom",
              icon: GraduationCap,
              title: "新建课堂录音",
              text: "双语字幕与课堂重点",
            },
            {
              kind: "meeting",
              icon: Users,
              title: "新建会议记录",
              text: "讨论内容与行动事项",
            },
            {
              kind: "interview",
              icon: MessagesSquare,
              title: "新建访谈",
              text: "保留原话与对话线索",
            },
          ].map(({ kind, icon: Icon, title, text }) => (
            <button
              className="dashboard-action"
              key={kind}
              onClick={() => create(kind)}
            >
              <span className="quick-icon">
                <Icon size={22} />
              </span>
              <span>
                <strong>{title}</strong>
                <small>{text}</small>
              </span>
              <Plus size={17} />
            </button>
          ))}
        </section>
        <section className="stat-grid" aria-label="会话统计">
          <Card className="stat-card">
            <span>
              <FileText size={16} />
              {search ? "匹配会话" : "已加载会话"}
            </span>
            <strong>
              {sessions.length}
              <small> 个</small>
            </strong>
            <p>来自当前会话列表</p>
          </Card>
          <Card className="stat-card">
            <span>
              <Clock size={16} />
              累计采音时长
            </span>
            <strong>
              {Math.floor(total / 60000)}
              <small> 分钟</small>
            </strong>
            <p>{search ? "当前搜索结果" : "当前列表"} · 不含暂停间隔</p>
          </Card>
          <Card className="stat-card">
            <span>
              <Mic size={16} />
              真实模式会话
            </span>
            <strong>
              {realCount}
              <small> 个</small>
            </strong>
            <p>另有 {sessions.length - realCount} 个模拟演示</p>
          </Card>
        </section>
        <section className="recent-section" aria-label="历史会话">
          <div className="section-heading">
            <div>
              <h2>
                最近会话 <span className="count-pill">{sessions.length}</span>
              </h2>
              <p>打开已保存的字幕、摘要与资料。</p>
            </div>
            <label className="search-field">
              <Search size={17} />
              <Input
                aria-label="搜索会话与字幕"
                placeholder="搜索会话与字幕…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              {search && (
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label="清除搜索"
                  onClick={() => setSearch("")}
                >
                  <X size={14} />
                </Button>
              )}
            </label>
          </div>
          {sessions.length ? (
            <div className="session-list">
              <div className="session-columns" aria-hidden="true">
                <span>会话名称 / 类型</span>
                <span>模式</span>
                <span>状态</span>
              </div>
              {sessions.map((session) => (
                <button
                  className="session-row"
                  key={session.id}
                  onClick={() => select(session)}
                >
                  <span className="session-symbol">
                    {session.kind === "meeting" ? (
                      <Users size={20} />
                    ) : session.kind === "interview" ? (
                      <MessagesSquare size={20} />
                    ) : (
                      <GraduationCap size={20} />
                    )}
                  </span>
                  <span className="session-title">
                    <strong>{session.title}</strong>
                    <small>
                      {formatDate(session.created_at)}
                      <span>·</span>
                      <Clock size={12} />
                      {formatTime(session.captured_ms ?? session.duration_ms)}
                      <span>·</span>
                      {session.kind === "meeting"
                        ? "会议"
                        : session.kind === "interview"
                          ? "访谈"
                          : "课堂"}
                    </small>
                  </span>
                  <Badge className={session.mode === "demo" ? "amber" : "blue"}>
                    {session.mode === "demo" ? "模拟演示" : "真实模式"}
                  </Badge>
                  <span className="row-state">
                    {(
                      {
                        recording: "录音中",
                        stopped: "已停止",
                        idle: "待开始",
                        completed: "已完成",
                        processing: "处理中",
                        failed: "处理失败",
                      } as Record<string, string>
                    )[session.status] || session.status}
                  </span>
                  <ChevronRight size={16} />
                </button>
              ))}
            </div>
          ) : (
            <Card className="empty-state">
              <FileText size={28} />
              <h3>{search ? "未找到相关会话" : "还没有会话"}</h3>
              <p>
                {search
                  ? "试试其他标题或字幕关键词。"
                  : "从模拟演示开始体验，不调用付费 API。"}
              </p>
              {!search && (
                <Button onClick={() => create()}>
                  <Plus size={16} />
                  创建会话
                </Button>
              )}
            </Card>
          )}
        </section>
        <div className="dashboard-links">
          <Button variant="secondary" onClick={library}>
            <BookOpen size={16} />
            资料库与知识来源
            <ArrowRight size={15} />
          </Button>
          <Button variant="ghost" onClick={settings}>
            <Settings2 size={16} />
            语言、麦克风与阅读偏好
          </Button>
        </div>
        <footer className="page-footer">
          <span>
            <ShieldCheck size={14} />
            私人工作空间 · 默认只保存文字
          </span>
          <span>ClassBridge</span>
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
  defaultTarget = "zh-CN",
  retention = 7,
}: {
  kind: string;
  close: () => void;
  submit: (data: {
    title: string;
    kind: string;
    mode: Mode;
    retain_audio: boolean;
    target_language: TargetLanguage;
  }) => Promise<void>;
  defaultRetain?: boolean;
  defaultTarget?: TargetLanguage;
  retention?: number;
}) {
  const [kind, setKind] = useState(initial),
    [title, setTitle] = useState(""),
    [mode, setMode] = useState<Mode>("demo"),
    [retain, setRetain] = useState(defaultRetain),
    [target, setTarget] = useState<TargetLanguage>(defaultTarget),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <Dialog
      title="新建会话"
      description="选择会话类型、模式和音频保留策略"
      close={close}
      busy={busy}
    >
      <div className="modal-title">
        <span className="quick-icon purple">
          <AudioLines size={23} />
        </span>
        <button
          className="icon-button"
          aria-label="关闭"
          disabled={busy}
          onClick={close}
        >
          <X size={20} />
        </button>
      </div>
      <h2 aria-hidden="true">新建会话</h2>
      <p className="muted">先选择会话模式，准备好后再点击开始。</p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy) return;
          if (mode === "demo" && target !== "zh-CN") { setError("模拟演示仅支持简体中文，请选择真实课堂或简体中文。"); return; }
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
              target_language: target,
            });
          } catch (err) {
            setError(err instanceof Error ? err.message : "创建失败");
            setBusy(false);
          }
        }}
      >
        <fieldset disabled={busy} className="new-session-fields">
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
            <Input
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
          <label>
            字幕翻译目标语言
            <select aria-label="字幕翻译目标语言" value={target} onChange={e=>setTarget(e.target.value as TargetLanguage)}>
              {Object.entries(translationLanguages).map(([code,language])=><option key={code} value={code}>{language.label}</option>)}
            </select>
            <small>创建后固定用于本会话，修改偏好不会改变历史会话。</small>
          </label>
          {mode === "demo" && <p role="status">模拟演示仅支持简体中文；其他目标语言请选择真实课堂。模拟模式不调用付费 API。</p>}
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
        </fieldset>
        {error && (
          <div className="error-box" role="alert">
            {error}
          </div>
        )}
        <Button type="submit" className="full" disabled={busy || (mode === "demo" && target !== "zh-CN")}>
          {busy ? "正在创建…" : "创建会话"}
          <ArrowRight size={17} />
        </Button>
      </form>
    </Dialog>
  );
}
