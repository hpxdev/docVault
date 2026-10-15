import type {
  AskResponse,
  ComparisonList,
  ComparisonOut,
  DocumentList,
  DocumentMetrics,
  DocumentOut,
  InsightsOut,
  MessageList,
  ProcessingMetrics,
  Readiness,
  SessionList,
  SessionOut,
  SummaryList,
  SummaryOut,
  SummaryRequest,
  UploadResponse,
  UploadResult,
  VersionList,
} from "./types";

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";

/** Error envelope from the API: {"error": {code, message, details}, "request_id"}. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

export async function parseError(res: Response): Promise<ApiError> {
  let body: { error?: { code?: string; message?: string; details?: Record<string, unknown> } } =
    {};
  try {
    body = await res.json();
  } catch {
    // not JSON (e.g. a proxy error page): fall through to a generic message
  }
  return new ApiError(
    res.status,
    body.error?.code ?? "HTTP_ERROR",
    body.error?.message ?? `Request failed (HTTP ${res.status}).`,
    body.error?.details ?? {},
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, init);
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Cannot reach the API. Is the backend running?");
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  ready: () => request<Readiness>("/health/ready"),

  listDocuments: (
    params: { limit?: number; offset?: number; status?: string; q?: string; all_versions?: boolean } = {},
  ) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
    return request<DocumentList>(`/documents?${qs}`);
  },
  getDocument: (id: string) => request<DocumentOut>(`/documents/${id}`),
  getInsights: (id: string) => request<InsightsOut>(`/documents/${id}/insights`),
  reprocess: (id: string) =>
    request<{ document: DocumentOut; stages: string[] }>(`/documents/${id}/reprocess`, {
      method: "POST",
    }),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  fileUrl: (id: string) => `${API_BASE}/documents/${id}/file`,

  /** Upload ≤ 10 files. When every file is rejected the API answers 4xx with per-file results in
   * `details.results`; those are returned like a normal response so the UI can show reasons. */
  upload: async (files: File[]): Promise<UploadResult[]> => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    try {
      return (await request<UploadResponse>("/documents", { method: "POST", body: form })).results;
    } catch (err) {
      if (err instanceof ApiError && Array.isArray(err.details.results)) {
        return err.details.results as UploadResult[];
      }
      throw err;
    }
  },

  /** Upload one file as the next version of a document (any version id of the group). */
  uploadVersion: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<DocumentOut>(`/documents/${id}/versions`, { method: "POST", body: form });
  },
  listVersions: (id: string) => request<VersionList>(`/documents/${id}/versions`),

  createSummary: (id: string, body: SummaryRequest) =>
    request<SummaryOut>(`/documents/${id}/summaries`, json("POST", body)),
  listSummaries: (id: string) => request<SummaryList>(`/documents/${id}/summaries`),

  compare: (documentIds: string[], focus?: string) =>
    request<ComparisonOut>("/comparisons", json("POST", { document_ids: documentIds, focus: focus || null })),
  getComparison: (id: string) => request<ComparisonOut>(`/comparisons/${id}`),
  listComparisons: (documentId?: string) =>
    request<ComparisonList>(`/comparisons?limit=20${documentId ? `&document_id=${documentId}` : ""}`),

  listSessions: () => request<SessionList>("/chat/sessions?limit=100"),
  getSession: (id: string) => request<SessionOut>(`/chat/sessions/${id}`),
  createSession: (body: { document_ids?: string[]; scope_mode?: "documents" | "all"; title?: string }) =>
    request<SessionOut>("/chat/sessions", json("POST", body)),
  updateSession: (
    id: string,
    body: {
      title?: string;
      scope_mode?: "documents" | "all";
      add_document_ids?: string[];
      remove_document_ids?: string[];
    },
  ) => request<SessionOut>(`/chat/sessions/${id}`, json("PATCH", body)),
  deleteSession: (id: string) => request<void>(`/chat/sessions/${id}`, { method: "DELETE" }),

  /** Newest page of history (the API pages oldest-first). */
  listMessages: async (id: string) => {
    const first = await request<MessageList>(`/chat/sessions/${id}/messages?limit=100`);
    if (first.total <= 100) return first;
    return request<MessageList>(
      `/chat/sessions/${id}/messages?limit=100&offset=${first.total - 100}`,
    );
  },
  ask: (id: string, content: string) =>
    request<AskResponse>(`/chat/sessions/${id}/messages`, json("POST", { content })),

  documentMetrics: () => request<DocumentMetrics>("/metrics/documents"),
  processingMetrics: (window: string) =>
    request<ProcessingMetrics>(`/metrics/processing?window=${window}`),
};
