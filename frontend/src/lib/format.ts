export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function formatRate(rate: { value: number | null; numerator: number; denominator: number }) {
  if (rate.value === null) return `— (0/0)`;
  return `${(rate.value * 100).toFixed(1)}% (${rate.numerator}/${rate.denominator})`;
}

export function formatUsd(value: number): string {
  return `$${value.toFixed(value < 0.01 ? 5 : 4)}`;
}

export function relativeTime(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

/** Short human labels for document states and stage errors shown on chips. */
export function statusLabel(status: string, chatReady: boolean): string {
  if (status === "ready") return "Ready";
  if (status === "partial") return chatReady ? "Ready (no insights)" : "Partly failed";
  if (status === "failed") return "Failed";
  if (status === "queued") return "Queued";
  return chatReady ? "Ready to chat · analysing" : "Processing…";
}

const ERROR_TEXT: Record<string, string> = {
  ENCRYPTED_DOCUMENT: "Password-protected PDF",
  CORRUPT_DOCUMENT: "File is damaged or unreadable",
  PAGE_LIMIT_EXCEEDED: "Too many pages (max 300)",
  NO_EXTRACTABLE_TEXT: "No text layer (scanned?) — OCR not supported",
  UNSUPPORTED_ENCODING: "Unsupported text encoding",
  UNSUPPORTED_FILE_TYPE: "Unsupported file type",
  EMPTY_FILE: "Empty file",
  FILE_TOO_LARGE: "File too large (max 25 MB)",
  AI_PROVIDER_UNAVAILABLE: "AI provider unavailable — retry later",
  AI_BUDGET_EXCEEDED: "AI spend cap reached",
  AI_NOT_CONFIGURED: "AI is not configured",
};

export function errorText(code: string | undefined | null, fallback?: string | null): string {
  if (!code) return fallback ?? "Unknown error";
  return ERROR_TEXT[code] ?? fallback ?? code;
}
