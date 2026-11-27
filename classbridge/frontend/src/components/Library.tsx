import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  CheckCircle2,
  ExternalLink,
  FileText,
  LoaderCircle,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { request } from "../lib/api";
import { Dialog } from "./ui/dialog";
import type { Document, Mode } from "../lib/types";
import { useI18n } from "../i18n/I18nProvider";
import { formatNumber } from "../i18n";
export function Library({
  notify,
  sessionId,
  defaultMode = "demo",
}: {
  notify: (s: string) => void;
  sessionId?: string;
  defaultMode?: Mode;
}) {
  const { t, language } = useI18n();
  const [documents, setDocuments] = useState<Document[]>([]),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [mode, setMode] = useState<Mode>(defaultMode),
    [selected, setSelected] = useState<Document | null>(null),
    [query, setQuery] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const reload = () =>
    request<Document[]>(
      `/documents${sessionId ? `?session_id=${sessionId}` : ""}`,
    )
      .then(setDocuments)
      .catch((e) => notify(e.message))
      .finally(() => setLoading(false));
  useEffect(() => {
    void reload();
    const timer = setInterval(() => {
      void reload();
    }, 5000);
    return () => clearInterval(timer);
  }, []);
  const upload = async (file?: File) => {
    if (!file) return;
    if (!/\.(pdf|pptx|docx)$/i.test(file.name)) {
      notify(t("library.unsupported"));
      return;
    }
    if (file.size > 40 * 1024 * 1024) {
      notify(t("library.tooLarge"));
      return;
    }
    setBusy(true);
    try {
      const data = new FormData();
      data.append("file", file);
      data.append("mode", mode);
      if (sessionId) data.append("session_id", sessionId);
      await request("/documents", { method: "POST", body: data });
      notify(t("library.uploaded"));
      await reload();
    } catch (e) {
      notify(t("common.error"));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  return (
    <div className="library page-scroll">
      <div className="page-width">
        <div className="page-heading">
          <div>
            <span className="eyebrow">{t("library.source")}</span>
            <h1>{t("navigation.library")}</h1>
            <p>{t("library.intro")}</p>
          </div>
          <Button onClick={() => input.current?.click()} disabled={busy}>
            <Upload size={17} />
            {t(busy ? "library.uploading" : "library.upload")}
          </Button>
        </div>
        <input
          ref={input}
          type="file"
          accept=".pdf,.pptx,.docx"
          hidden
          onChange={(e) => void upload(e.target.files?.[0])}
        />
        <section
          className="upload-zone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (!busy) void upload(e.dataTransfer.files[0]);
          }}
        >
          <span className="empty-icon">
            <Upload size={27} />
          </span>
          <h3>{t("library.addSource")}</h3>
          <p>
            {t("library.drop")}
            <button
              className="inline-link"
              onClick={() => input.current?.click()}
              disabled={busy}
            >
              {t("library.choose")}
            </button>
          </p>
          <small>{t("library.formats")}</small>
          <label className="upload-mode">
            {t("library.mode")}
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as Mode)}
            >
              <option value="demo">{t("library.demo")}</option>
              <option value="real">{t("library.real")}</option>
            </select>
          </label>
        </section>
        <div className="section-heading">
          <h2>
            {t("library.all")} <span className="count-pill">{formatNumber(language, documents.length)}</span>
          </h2>
          <label className="search-field">
            <Search size={16} />
            <Input
              aria-label={t("library.search")}
              placeholder={t("library.searchPlaceholder")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
        </div>
        {loading ? (
          <div className="loading">
            <LoaderCircle className="spin" />
            {t("library.loading")}
          </div>
        ) : documents.length ? (
          <div className="document-grid">
            {documents
              .filter((d) =>
                (d.name || d.filename || "")
                  .toLowerCase()
                  .includes(query.toLowerCase()),
              )
              .map((d) => (
                <Card className="document-card" key={d.id}>
                  <div>
                    <span className="file-type">
                      <FileText size={23} />
                      {(d.name || d.filename || "FILE")
                        .split(".")
                        .pop()
                        ?.toUpperCase()}
                    </span>
                    <button
                      className="icon-button danger"
                      title={t("library.delete")}
                      aria-label={t("library.deleteNamed", { name: d.name || d.filename || "" })}
                      onClick={async () => {
                        if (
                          confirm(
                            t("library.deleteConfirm"),
                          )
                        ) {
                          try {
                            await request(`/documents/${d.id}`, {
                              method: "DELETE",
                            });
                            await reload();
                          } catch (e) {
                            notify(t("common.error"));
                          }
                        }
                      }}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                  <h3>{d.name || d.filename}</h3>
                  <p className="tiny muted">
                    {d.page_count
                      ? t("library.pages", { count: d.page_count })
                      : t("library.paragraphIndex")}{" "}
                    · v{d.version || 1}
                  </p>
                  <span
                    className={`badge ${d.status === "failed" ? "red" : ["ready", "ready_keyword"].includes(d.status) ? "green" : "blue"}`}
                  >
                    {["ready", "ready_keyword"].includes(d.status) ? (
                      <CheckCircle2 size={12} />
                    ) : (
                      <LoaderCircle
                        size={12}
                        className={d.status === "failed" ? "" : "spin"}
                      />
                    )}
                    {{
                      ready:
                        d.index_mode === "demo"
                          ? t("library.demoReady")
                          : t("library.ready"),
                      ready_keyword: t("library.keywordReady"),
                      pending: t("library.pending"),
                      parsing: t("library.parsing"),
                      failed: t("library.failed"),
                    }[d.status] || d.status}
                  </span>
                  {d.error && <p className="error-note">{t("library.failed")}</p>}
                  <button
                    className="document-open"
                    onClick={() => setSelected(d)}
                  >
                    <BookOpen size={15} />
                    {t("library.view")}
                    <ExternalLink size={13} />
                  </button>
                </Card>
              ))}
          </div>
        ) : (
          <div className="empty-state compact">
            <BookOpen size={26} />
            <p>{t("library.empty")}</p>
          </div>
        )}
        <div className="info-box">
          {t("library.limits")}
        </div>
      </div>
      {selected && (
        <DocumentPreview
          documentId={selected.id}
          close={() => setSelected(null)}
        />
      )}
    </div>
  );
}
export function DocumentPreview({
  documentId,
  chunkId,
  page,
  quote,
  close,
}: {
  documentId: string;
  chunkId?: string;
  page?: number;
  quote?: string;
  close: () => void;
}) {
  const { t } = useI18n();
  const [doc, setDoc] = useState<Document | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    request<Document>(`/documents/${documentId}`)
      .then(setDoc)
      .catch((e) => setError(e.message));
  }, [documentId]);
  useEffect(() => {
    if (doc && (chunkId || page || quote))
      setTimeout(
        () =>
          document
            .getElementById(
              `document-chunk-${doc.chunks?.find((c) => (chunkId ? c.id === chunkId : quote ? c.text === quote : c.page === page))?.id}`,
            )
            ?.scrollIntoView({ block: "center" }),
        60,
      );
  }, [doc, chunkId, page, quote]);
  return (
    <Dialog title={t("library.preview")} className="document-preview" close={close}>
        <div className="modal-title">
          <h2>{doc?.name || doc?.filename || t("library.documentSource")}</h2>
          <button className="icon-button" aria-label={t("library.closePreview")} onClick={close}>
            <X size={20} />
          </button>
        </div>
        <p className="tiny muted">
          {t("library.version", { version: doc?.version || 1 })}
          {page ? ` · ${t("library.page", { page })}` : ""}
        </p>
        {error && <p className="error-box">{t("common.error")}</p>}
        {!doc && !error && (
          <div className="loading">
            <LoaderCircle className="spin" />
            {t("library.loadingSource")}
          </div>
        )}
        {quote && <blockquote className="source-quote">{quote}</blockquote>}
        <div className="document-chunks">
          {doc?.chunks?.map((chunk, i) => (
            <article
              id={`document-chunk-${chunk.id}`}
              className={
                (
                  chunkId
                    ? chunk.id === chunkId
                    : quote
                      ? chunk.text === quote
                      : !!page && page === chunk.page
                )
                  ? "highlight-source"
                  : ""
              }
              key={chunk.id || i}
            >
              <span className="eyebrow">
                {chunk.location ||
                  (chunk.page
                    ? t("library.page", { page: chunk.page })
                    : t("library.paragraph", { count: i + 1 }))}{" "}
                · {t("library.position", { position: chunk.position || 0 })}
              </span>
              <p>{chunk.text}</p>
            </article>
          ))}
          {doc && !doc.chunks?.length && (
            <p className="muted">
              {t(doc.error ? "library.failed" : "library.noText")}
            </p>
          )}
        </div>
        <a
          className="secondary"
          target="_blank"
          rel="noreferrer"
          href={`/api/documents/${documentId}/file${page ? `#page=${page}` : ""}`}
        >
          <ExternalLink size={15} />
          {t("library.openFile")}
        </a>
    </Dialog>
  );
}
