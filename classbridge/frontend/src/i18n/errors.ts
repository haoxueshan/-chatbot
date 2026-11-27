/**
 * Optional diagnostic summary, never a full provider response.
 * Reject structured payloads, URLs, credential markers and token-like strings.
 * Render the result as React text only.
 */
export function safeDiagnostic(value: unknown): string {
  if (typeof value !== "string") return "";
  const text = value.trim();
  if (!text || text.length > 160 || /[\r\n{}[\]<>]/u.test(text)) return "";
  if (/https?:|www\.|bearer|authorization|password|secret|token|api.?key|credential|密钥|密码|凭据/i.test(text)) return "";
  if (/[A-Za-z0-9_+/=-]{24,}/.test(text)) return "";
  return text;
}