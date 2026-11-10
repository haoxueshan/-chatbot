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
export function Library({
  notify,
  sessionId,
  defaultMode = "demo",
}: {
  notify: (s: string) => void;
  sessionId?: string;
  defaultMode?: Mode;
}) {
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
      notify("支持 PDF、PPTX 和 DOCX 文件");
      return;
    }
    if (file.size > 40 * 1024 * 1024) {
      notify("单个文件不能超过 40 MB");
      return;
    }
    setBusy(true);
    try {
      const data = new FormData();
      data.append("file", file);
      data.append("mode", mode);
      if (sessionId) data.append("session_id", sessionId);
      await request("/documents", { method: "POST", body: data });
      notify("资料已上传，正在解析与索引");
      await reload();
    } catch (e) {
      notify(e instanceof Error ? e.message : "上传失败");
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
            <span className="eyebrow">知识来源</span>
            <h1>资料库</h1>
            <p>把课程讲义变成可追溯、可提问的知识来源。</p>
          </div>
          <Button onClick={() => input.current?.click()} disabled={busy}>
            <Upload size={17} />
            {busy ? "上传中…" : "上传资料"}
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
          <h3>让知识，多一个来源</h3>
          <p>
            拖入文件，或
            <button
              className="inline-link"
              onClick={() => input.current?.click()}
              disabled={busy}
            >
              选择本地文件
            </button>
          </p>
          <small>PDF / PPTX / DOCX · 最大 40 MB · 私人访问</small>
          <label className="upload-mode">
            索引模式
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as Mode)}
            >
              <option value="demo">模拟 / 关键词索引（不调用付费 API）</option>
              <option value="real">真实语义索引（需要服务器模型密钥）</option>
            </select>
          </label>
        </section>
        <div className="section-heading">
          <h2>
            全部资料 <span className="count-pill">{documents.length}</span>
          </h2>
          <label className="search-field">
            <Search size={16} />
            <Input
              aria-label="搜索资料"
              placeholder="按名称搜索…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
        </div>
        {loading ? (
          <div className="loading">
            <LoaderCircle className="spin" />
            正在读取资料…
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
                      title="删除资料"
                      aria-label={`删除${d.name || d.filename}`}
                      onClick={async () => {
                        if (
                          confirm(
                            "确定删除此资料？原文件、文本块、向量与相关引用将同时处理。",
                          )
                        ) {
                          try {
                            await request(`/documents/${d.id}`, {
                              method: "DELETE",
                            });
                            await reload();
                          } catch (e) {
                            notify(e instanceof Error ? e.message : "删除失败");
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
                      ? `${d.page_count} 页 / 幻灯片`
                      : "段落位置索引"}{" "}
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
                          ? "模拟索引就绪（不调用付费 API）"
                          : "语义索引就绪",
                      ready_keyword: "关键词索引就绪",
                      pending: "等待解析",
                      parsing: "解析中",
                      failed: "解析失败",
                    }[d.status] || d.status}
                  </span>
                  {d.error && <p className="error-note">{d.error}</p>}
                  <button
                    className="document-open"
                    onClick={() => setSelected(d)}
                  >
                    <BookOpen size={15} />
                    查看来源
                    <ExternalLink size={13} />
                  </button>
                </Card>
              ))}
          </div>
        ) : (
          <div className="empty-state compact">
            <BookOpen size={26} />
            <p>暂无资料。上传讲义后，就可以结合原文提问。</p>
          </div>
        )}
        <div className="info-box">
          扫描件或无法提取的内容会显示解析限制。DOCX
          使用段落定位，不编造固定页码。
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
    <Dialog title="资料来源预览" className="document-preview" close={close}>
        <div className="modal-title">
          <h2>{doc?.name || doc?.filename || "资料来源"}</h2>
          <button className="icon-button" aria-label="关闭预览" onClick={close}>
            <X size={20} />
          </button>
        </div>
        <p className="tiny muted">
          原始提取文本 · 版本 {doc?.version || 1}
          {page ? ` · 第 ${page} 页 / 幻灯片` : ""}
        </p>
        {error && <p className="error-box">{error}</p>}
        {!doc && !error && (
          <div className="loading">
            <LoaderCircle className="spin" />
            正在读取来源…
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
                    ? `第 ${chunk.page} 页 / 幻灯片`
                    : `段落 ${i + 1}`)}{" "}
                · 字符位置 {chunk.position || 0}
              </span>
              <p>{chunk.text}</p>
            </article>
          ))}
          {doc && !doc.chunks?.length && (
            <p className="muted">
              {doc.error ||
                "尚无可读取文本。请等待解析完成，或检查扫描件限制。"}
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
          打开原始文件
        </a>
    </Dialog>
  );
}
