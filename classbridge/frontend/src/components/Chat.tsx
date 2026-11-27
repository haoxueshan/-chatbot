import { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpen,
  MessageSquare,
  Sparkles,
  LoaderCircle,
} from "lucide-react";
import { post, request } from "../lib/api";
import { useI18n } from "../i18n/I18nProvider";
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
  const { t: text } = useI18n();
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
      setError("failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="chat-panel">
      <div className="chat-scope">
        <label>
          {text("chat.scope")}
          <select
            aria-label={text("chat.scopeLabel")}
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          >
            {sessionId && (
              <>
                <option value="session">{text("chat.session")}</option>
                <option value="recent">{text("chat.recent")}</option>
              </>
            )}
            <option value="documents">{text("chat.documents")}</option>
            <option value="history">{text("chat.history")}</option>
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
              <p className="tiny muted">{text("chat.upload")}</p>
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
            <h3>{text("chat.heading")}</h3>
            <p>
              {text("chat.intro")}
              <br />
              {text("chat.evidence")}
            </p>
            {[
              text("chat.suggestion1"),
              text("chat.suggestion2"),
              text("chat.suggestion3"),
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
              {t.mode === "demo" && <span className="badge amber">{text("chat.demo")}</span>}
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
                        ? text("chat.document", { location: c.location || (c.page ? text("chat.page", { page: c.page }) : text("chat.location")) })
                        : text("chat.source", { revision: c.source_revision || 1 })}
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
            {text("chat.busy")}
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
            {text("chat.failed")}
          </p>
        )}
        <div>
          <textarea
            aria-label={text("chat.input")}
            placeholder={text("chat.placeholder")}
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
            aria-label={text("chat.send")}
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
          {text(mode === "demo" ? "chat.demoHint" : "chat.disclaimer")}
        </small>
      </form>
    </div>
  );
}
