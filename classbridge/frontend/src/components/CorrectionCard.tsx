import { useState } from "react";
import { post } from "../lib/api";
import type { CorrectionSuggestion } from "../lib/types";

export function CorrectionCard({ suggestion, sessionId, active, saved, notify, jump }: {
  suggestion: CorrectionSuggestion; sessionId: string; active: boolean; saved: () => void;
  notify: (message: string) => void; jump: (id: string, revision?: number) => void;
}) {
  const [busy, setBusy] = useState(false), [hidden, setHidden] = useState(false);
  const decide = async (action: "accept" | "dismiss") => {
    setBusy(true);
    try {
      await post(`/sessions/${sessionId}/corrections/${suggestion.task_id}/${action}`, {});
      setHidden(true); saved();
    } catch (e) { notify(e instanceof Error ? e.message : "处理建议失败"); }
    finally { setBusy(false); }
  };
  if (hidden) return null;
  return <aside className="correction-card">
    <strong>推测校正 · 待确认</strong>
    <p className="tiny muted">基于文字规律与上下文，尚未通过音频核实。原始识别保留。</p>
    <p lang="und">{suggestion.suggested_text}</p>
    <details>
      <summary>查看改动与依据</summary>
      {suggestion.edits.map((edit, i) => <p key={i}><del>{edit.before}</del> → <ins>{edit.after}</ins>：{edit.reason}</p>)}
      {suggestion.evidence.map((e) => <div key={e.id} className="correction-evidence">
        {e.sentence_id && e.source_revision ? <button className="text-button" onClick={() => jump(e.sentence_id!, e.source_revision)}>
          {e.kind === "source" ? "本句" : "前文"} v{e.source_revision}
        </button> : <span>{e.kind === "term" ? "已填术语" : "已填课程背景"}</span>}
        <span>{e.quote}</span>
      </div>)}
    </details>
    <div className="correction-actions">
      <button className="secondary" disabled={busy || active} onClick={() => void decide("accept")}>
        {active ? "停止录音后可采纳" : "采纳为新版本"}
      </button>
      <button className="text-button" disabled={busy} onClick={() => void decide("dismiss")}>忽略建议</button>
    </div>
  </aside>;
}
