import { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpen,
  MessageSquare,
  Sparkles,
  LoaderCircle,
} from "lucide-react";
import { post, request } from "../lib/api";
import type { ChatReply, Citation, Document, Mode } from "../lib/types";
interface Turn extends ChatReply {
  question: string;
}
export function Chat({
  sessionId,
  mode,
  onCitation,
}: {
  sessionId?: string;
  mode: Mode;
  onCitation: (c: Citation) => void;
}) {
  const [question, setQuestion] = useState(""),
    [scope, setScope] = useState(sessionId ? "session" : "history"),
    [turns, setTurns] = useState<Turn[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [documents, setDocuments] = useState<Document[]>([]),
    [selected, setSelected] = useState<string[]>([]);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    request<Document[]>("/documents")
      .then(setDocuments)
      .catch(() => {});
    request<unknown>(
      `/chat?mode=${mode}${sessionId ? `&session_id=${sessionId}` : ""}`,
    )
      .then((result) => {
        if (Array.isArray(result)) {
          setTurns(
            result
              .filter((x) => x.question && x.answer)
              .map((x) => ({
                ...x,
                citations: x.citations || [],
                mode: x.mode || mode,
              })),
          );
        }
      })
      .catch(() => {});
  }, [sessionId, mode]);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [turns, busy]);
  const ask = async (value = question) => {
    if (!value.trim() || busy) return;
    setBusy(true);
    setError("");
    setQuestion("");
    try {
      const answer = await post<ChatReply>("/chat", {
        session_id: sessionId,
        scope,
        document_ids: selected,
        question: value.trim(),
        mode,
      });
      setTurns((old) => [...old, { question: value.trim(), ...answer }]);
    } catch (err) {
      setQuestion(value);
      setError(err instanceof Error ? err.message : "回答失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="chat-panel">
      <div className="chat-scope">
        <label>
          检索范围
          <select
            aria-label="问答检索范围"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          >
            {sessionId && (
              <>
                <option value="session">当前完整会话</option>
                <option value="recent">最近课堂内容</option>
              </>
            )}
            <option value="documents">选定资料</option>
            <option value="history">我的历史会话</option>
          </select>
        </label>
        {scope === "documents" && (
          <div className="doc-picks">
            {documents.length ? (
              documents.map((d) => (
                <label key={d.id}>
                  <input
                    type="checkbox"
                    checked={selected.includes(d.id)}
                    onChange={(e) =>
                      setSelected((old) =>
                        e.target.checked
                          ? [...old, d.id]
                          : old.filter((id) => id !== d.id),
                      )
                    }
                  />
                  {d.name || d.filename}
                </label>
              ))
            ) : (
              <p className="tiny muted">请先在资料库上传讲义。</p>
            )}
          </div>
        )}
      </div>
      <div className="chat-turns">
        {!turns.length && (
          <div className="chat-empty">
            <span className="chat-spark">
              <Sparkles size={26} />
            </span>
            <h3>把问题，交给证据</h3>
            <p>
              结合原文与讲义回答，
              <br />
              每个引用都能回到来源。
            </p>
            {[
              "刚才的核心观点是什么？",
              "解释课堂中提到的关键概念",
              "有哪些需要继续思考的问题？",
            ].map((s) => (
              <button key={s} onClick={() => void ask(s)} disabled={busy}>
                <MessageSquare size={14} />
                {s}
              </button>
            ))}
          </div>
        )}
        {turns.map((t, i) => (
          <div className="chat-turn" key={i}>
            <div className="user-bubble">{t.question}</div>
            <div className="assistant-heading">
              <Sparkles size={15} />
              ClassBridge{" "}
              {t.mode === "demo" && <span className="badge amber">模拟</span>}
            </div>
            <div className="answer-text">{t.answer}</div>
            {!!t.citations?.length && (
              <div className="citation-list">
                {t.citations.map((c, index) => (
                  <button
                    className="citation-card"
                    key={`${c.id}-${index}`}
                    onClick={() => onCitation(c)}
                  >
                    <BookOpen size={13} />
                    <span>
                      [{c.label || `E${index + 1}`}]{" "}
                      {c.kind === "document"
                        ? `资料 · ${c.location || (c.page ? `第 ${c.page} 页` : "原文位置")}`
                        : `原文 · v${c.source_revision || 1}`}
                      <small>{c.quote}</small>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="chat-working">
            <LoaderCircle size={16} className="spin" />
            正在检索证据与整理回答…
          </div>
        )}
        <div ref={end} />
      </div>
      <form
        className="chat-compose"
        onSubmit={(e) => {
          e.preventDefault();
          void ask();
        }}
      >
        {error && (
          <p className="error-box" role="alert">
            {error}
          </p>
        )}
        <div>
          <textarea
            aria-label="输入问题"
            placeholder="关于这节课，你想知道什么？"
            rows={2}
            maxLength={4000}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                void ask();
              }
            }}
          />
          <button
            className="send-button"
            aria-label="发送问题"
            disabled={
              busy ||
              !question.trim() ||
              (scope === "documents" && !selected.length)
            }
          >
            <ArrowUp size={18} />
          </button>
        </div>
        <small>
          {mode === "demo"
            ? "模拟问答 · 不调用付费 API"
            : "回答仅作辅助，请核对原文证据"}
        </small>
      </form>
    </div>
  );
}
