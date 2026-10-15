import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import { postSSE } from "../api/sse";
import type { CitationOut, MessageOut, StatusPayload } from "../api/types";
import { useDocumentEvents } from "../hooks/useDocumentEvents";
import { errorText, statusLabel } from "../lib/format";
import { AnswerText, AssistantMessage, UserBubble } from "./Message";
import { SourcePanel } from "./SourcePanel";

const MAX_FILES_PER_REQUEST = 10;
const ACCEPT = ".pdf,.docx,.txt,.md,.markdown";

interface Props {
  sessionId: string | null;
  onSessionCreated: (id: string) => void;
}

interface LocalFile {
  key: string;
  filename: string;
  state: "uploading" | "rejected";
  error?: string;
}

interface StreamState {
  question: string;
  text: string;
  citations: CitationOut[];
  phase: "streaming" | "stopping" | "error";
  error?: string;
}

interface ChipDoc {
  id: string;
  filename: string;
  status: string;
  chatReady: boolean;
  error: { code: string; message: string | null } | null;
  stages?: StatusPayload["stages"];
  version?: number;
  isLatest?: boolean;
}

export function ChatView({ sessionId, onSessionCreated }: Props) {
  const queryClient = useQueryClient();
  const [localFiles, setLocalFiles] = useState<LocalFile[]>([]);
  const [duplicates, setDuplicates] = useState<Set<string>>(new Set());
  const [stream, setStream] = useState<StreamState | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [dragging, setDragging] = useState(false);
  const [openCitation, setOpenCitation] = useState<CitationOut | null>(null);
  const [pendingVault, setPendingVault] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const createdHere = useRef<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const dragDepth = useRef(0);

  // Switching to another chat (not one we just created) resets the local, unsaved state.
  useEffect(() => {
    if (sessionId && sessionId === createdHere.current) return;
    setLocalFiles([]);
    setDuplicates(new Set());
    setStream(null);
    setNotice(null);
    setOpenCitation(null);
    setPendingVault(false);
  }, [sessionId]);

  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.getSession(sessionId!),
    enabled: !!sessionId,
  });
  const messages = useQuery({
    queryKey: ["messages", sessionId],
    queryFn: () => api.listMessages(sessionId!),
    enabled: !!sessionId,
  });

  const docIds = session.data?.documents.map((d) => d.id) ?? [];
  const live = useDocumentEvents(docIds, (payload) => {
    if (payload.chat_ready || payload.status === "failed" || payload.deleted) {
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  });

  const chipDocs: ChipDoc[] = (session.data?.documents ?? []).map((d) => {
    const s = live[d.id];
    return {
      id: d.id,
      filename: d.filename,
      status: s?.status ?? d.status,
      chatReady: s?.chat_ready ?? d.chat_ready,
      error: s?.error ?? null,
      stages: s?.stages,
      version: d.version,
      isLatest: d.is_latest,
    };
  });

  const vaultWide = session.data ? session.data.scope_mode === "all" : pendingVault;
  const uploading = localFiles.some((f) => f.state === "uploading");
  const waiting = chipDocs.filter((d) => !d.chatReady && d.status !== "failed" && d.status !== "partial");
  const blocked = chipDocs.filter((d) => !d.chatReady && (d.status === "failed" || d.status === "partial"));
  const busy = stream?.phase === "streaming" || stream?.phase === "stopping";

  let sendHint: string | null = null;
  if (uploading) sendHint = "Uploading…";
  else if (!vaultWide && chipDocs.length === 0)
    sendHint = "Attach documents (drop them here or use +), or turn on “Search entire vault”.";
  else if (!vaultWide && blocked.length)
    sendHint = `Remove ${blocked.length} document(s) that failed to process before asking.`;
  else if (!vaultWide && waiting.length)
    sendHint = `Waiting for ${waiting.length} document(s) to finish indexing…`;
  const canSend = !busy && !sendHint && draft.trim().length > 0;

  // Suggested questions from the attached documents' insights (empty chat only).
  const showEmpty = !messages.data?.items.length && !stream;
  const insights = useQueries({
    queries: chipDocs
      .filter((d) => d.status === "ready" || d.stages?.insights === "succeeded")
      .slice(0, 5)
      .map((d) => ({
        queryKey: ["insights", d.id],
        queryFn: () => api.getInsights(d.id),
        enabled: showEmpty,
        retry: false,
      })),
  });
  const suggestions = useMemo(
    () => insights.flatMap((q) => q.data?.suggested_questions ?? []).slice(0, 4),
    [insights],
  );

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.data?.items.length, stream?.text]);

  async function ensureSession(): Promise<string> {
    if (sessionId) return sessionId;
    const created = await api.createSession({ scope_mode: pendingVault ? "all" : "documents" });
    createdHere.current = created.id;
    queryClient.setQueryData(["session", created.id], created);
    queryClient.invalidateQueries({ queryKey: ["sessions"] });
    onSessionCreated(created.id);
    return created.id;
  }

  async function handleFiles(fileList: FileList | File[]) {
    const files = Array.from(fileList);
    if (!files.length) return;
    setNotice(null);
    let sid: string;
    try {
      sid = await ensureSession();
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : "Could not start a chat.");
      return;
    }
    for (let i = 0; i < files.length; i += MAX_FILES_PER_REQUEST) {
      const batch = files.slice(i, i + MAX_FILES_PER_REQUEST);
      const placeholders = batch.map((f) => ({
        key: `${Date.now()}-${Math.random()}`,
        filename: f.name,
        state: "uploading" as const,
      }));
      setLocalFiles((prev) => [...prev, ...placeholders]);
      try {
        const results = await api.upload(batch);
        const keys = new Set(placeholders.map((p) => p.key));
        const rejected: LocalFile[] = results
          .filter((r) => r.outcome === "rejected")
          .map((r) => ({
            key: `${Date.now()}-${Math.random()}`,
            filename: r.filename,
            state: "rejected",
            error: errorText(r.error?.code, r.error?.message),
          }));
        setLocalFiles((prev) => [...prev.filter((f) => !keys.has(f.key)), ...rejected]);
        // "Already in vault" only when the document existed before this drop (two copies of a new
        // file in one drop give accepted + duplicate for the same document).
        const acceptedIds = new Set(
          results.filter((r) => r.outcome === "accepted").map((r) => r.document!.id),
        );
        const dupIds = results
          .filter((r) => r.outcome === "duplicate" && !acceptedIds.has(r.document!.id))
          .map((r) => r.document!.id);
        if (dupIds.length) setDuplicates((prev) => new Set([...prev, ...dupIds]));
        const ids = results.filter((r) => r.document).map((r) => r.document!.id);
        if (ids.length) {
          const updated = await api.updateSession(sid, { add_document_ids: ids });
          queryClient.setQueryData(["session", sid], updated);
          queryClient.invalidateQueries({ queryKey: ["sessions"] });
          queryClient.invalidateQueries({ queryKey: ["documents"] });
        }
      } catch (err) {
        const keys = new Set(placeholders.map((p) => p.key));
        setLocalFiles((prev) => prev.filter((f) => !keys.has(f.key)));
        setNotice(err instanceof ApiError ? err.message : "Upload failed.");
      }
    }
  }

  async function removeDoc(id: string) {
    if (!sessionId) return;
    const updated = await api.updateSession(sessionId, { remove_document_ids: [id] });
    queryClient.setQueryData(["session", sessionId], updated);
    queryClient.invalidateQueries({ queryKey: ["sessions"] });
  }

  async function toggleVault(on: boolean) {
    if (!sessionId) {
      setPendingVault(on);
      return;
    }
    const updated = await api.updateSession(sessionId, { scope_mode: on ? "all" : "documents" });
    queryClient.setQueryData(["session", sessionId], updated);
    queryClient.invalidateQueries({ queryKey: ["sessions"] });
  }

  async function refreshHistory(sid: string) {
    await queryClient.invalidateQueries({ queryKey: ["messages", sid] });
    queryClient.invalidateQueries({ queryKey: ["session", sid] }); // auto-title after 1st question
    queryClient.invalidateQueries({ queryKey: ["sessions"] });
  }

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    setNotice(null);
    let sid: string;
    try {
      sid = await ensureSession();
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : "Could not start a chat.");
      return;
    }
    setDraft("");
    setStream({ question, text: "", citations: [], phase: "streaming" });
    const controller = new AbortController();
    abortRef.current = controller;
    let failed: string | null = null;
    try {
      await postSSE(
        `/chat/sessions/${sid}/messages/stream`,
        { content: question },
        ({ event, data }) => {
          const d = data as Record<string, unknown>;
          if (event === "token") {
            setStream((s) => (s ? { ...s, text: s.text + String(d.delta ?? "") } : s));
          } else if (event === "citations") {
            setStream((s) => (s ? { ...s, citations: d.citations as CitationOut[] } : s));
          } else if (event === "done") {
            const message = d.message as MessageOut;
            setStream((s) => (s ? { ...s, text: message.content, citations: message.citations } : s));
          } else if (event === "error") {
            failed = String(d.message ?? "The answer could not be generated.");
          }
        },
        controller.signal,
      );
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        // The server stops at the next token and saves the partial answer; give it a moment.
        await new Promise((r) => setTimeout(r, 700));
      } else if (err instanceof ApiError) {
        failed = err.code === "DOCUMENTS_NOT_READY" ? "Some documents are not ready yet." : err.message;
        if (err.status === 409 || err.status === 422) setDraft(question); // nothing was stored
      } else {
        failed = "The connection was interrupted.";
      }
    } finally {
      abortRef.current = null;
    }
    await refreshHistory(sid);
    if (failed) setNotice(failed);
    setStream(null);
  }

  function stop() {
    if (!abortRef.current) return;
    setStream((s) => (s ? { ...s, phase: "stopping" } : s));
    abortRef.current.abort();
  }

  const dropHandlers = {
    onDragEnter: (e: React.DragEvent) => {
      if (!e.dataTransfer.types.includes("Files")) return;
      e.preventDefault();
      dragDepth.current += 1;
      setDragging(true);
    },
    onDragOver: (e: React.DragEvent) => {
      if (e.dataTransfer.types.includes("Files")) e.preventDefault();
    },
    onDragLeave: () => {
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (dragDepth.current === 0) setDragging(false);
    },
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      dragDepth.current = 0;
      setDragging(false);
      void handleFiles(e.dataTransfer.files);
    },
  };

  const history = messages.data?.items ?? [];

  return (
    <div className="relative flex h-full min-w-0 flex-1">
      <div className="relative flex min-w-0 flex-1 flex-col" {...dropHandlers}>
        {dragging && !showEmpty && (
          <div className="vault-drop-overlay pointer-events-none absolute inset-3 z-30 flex items-center justify-center rounded-2xl border-2 border-dashed border-emerald-500 bg-emerald-50/90 dark:bg-emerald-950/90 text-lg font-medium text-emerald-800 dark:text-emerald-200">
            Drop files to add them to this chat (PDF, DOCX, TXT, MD · up to 25 MB each)
          </div>
        )}
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-neutral-200 dark:border-[#364139] px-6 py-4">
          <h1 className="truncate font-semibold">{session.data?.title ?? "New chat"}</h1>
          <label className="flex shrink-0 cursor-pointer items-center gap-2 text-sm text-neutral-700 dark:text-neutral-300">
            <input
              type="checkbox"
              checked={vaultWide}
              onChange={(e) => void toggleVault(e.target.checked)}
              className="h-4 w-4 accent-emerald-600"
              aria-label="Search entire vault"
            />
            Search entire vault
          </label>
        </header>

        <div className={`flex-1 overflow-y-auto ${showEmpty ? "flex flex-col" : ""}`}>
          <div className={`mx-auto w-full space-y-6 px-6 py-6 ${showEmpty ? "flex flex-1 flex-col justify-center max-w-5xl" : "max-w-3xl"}`}>
            {messages.isLoading && sessionId && <div className="text-neutral-500 dark:text-[#a0aca3]">Loading…</div>}
            {messages.error && (
              <div className="text-red-700 dark:text-red-300">Could not load this chat's history.</div>
            )}
            {showEmpty && !messages.isLoading && (
              <EmptyState
                hasDocs={chipDocs.length > 0 || vaultWide}
                suggestions={suggestions}
                canAsk={!sendHint}
                onPick={(q) => void send(q)}
                onBrowse={() => fileInput.current?.click()}
                dragging={dragging}
              />
            )}
            {history.map((m) =>
              m.role === "user" ? (
                <UserBubble key={m.id} content={m.content} />
              ) : (
                <AssistantMessage key={m.id} message={m} onOpenCitation={setOpenCitation} />
              ),
            )}
            {stream && (
              <>
                <UserBubble content={stream.question} />
                <div className="px-1">
                  {stream.text ? (
                    <AnswerText
                      content={stream.text}
                      citations={stream.citations}
                      onOpenCitation={setOpenCitation}
                    />
                  ) : (
                    <div className="animate-pulse text-neutral-400">Searching your documents…</div>
                  )}
                  {stream.phase === "stopping" && (
                    <div className="mt-1 text-xs text-neutral-500 dark:text-[#a0aca3]">Stopping…</div>
                  )}
                </div>
              </>
            )}
            <div ref={bottom} className={showEmpty ? "hidden" : undefined} />
          </div>
        </div>

        <div className="border-t border-neutral-100 dark:border-[#303a33] bg-white dark:bg-[#202421] px-6 pb-5 pt-3">
          <div className="mx-auto max-w-3xl">
            <AttachmentChips
              docs={chipDocs}
              local={localFiles}
              duplicates={duplicates}
              onRemove={(id) => void removeDoc(id)}
              onDismiss={(key) => setLocalFiles((prev) => prev.filter((f) => f.key !== key))}
            />
            {notice && (
              <div className="mb-2 rounded-lg bg-red-50 dark:bg-red-950 px-3 py-2 text-sm text-red-800 dark:text-red-200" role="alert">
                {notice}
              </div>
            )}
            <div className="vault-composer flex items-end gap-2 rounded-2xl border border-neutral-200 dark:border-[#364139] bg-white dark:bg-[#202421] p-3 shadow-sm focus-within:border-[#42735c]">
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xl text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-[#2c332e]"
                aria-label="Attach files"
                title="Attach files"
              >
                +
              </button>
              <input
                ref={fileInput}
                type="file"
                multiple
                accept={ACCEPT}
                className="hidden"
                onChange={(e) => {
                  if (e.target.files) void handleFiles(e.target.files);
                  e.target.value = "";
                }}
              />
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    if (canSend) void send(draft);
                  }
                }}
                rows={1}
                placeholder="Ask about your documents…"
                className="max-h-48 min-h-9 flex-1 resize-none bg-transparent px-1 py-1.5 outline-none field-sizing-content"
                aria-label="Message"
              />
              {busy ? (
                <button
                  type="button"
                  onClick={stop}
                  className="h-9 shrink-0 rounded-full bg-neutral-900 px-4 text-sm font-medium text-white hover:bg-neutral-700"
                >
                  Stop
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void send(draft)}
                  disabled={!canSend}
                  className="h-9 shrink-0 rounded-lg bg-[#42735c] px-4 text-sm font-medium text-white hover:bg-[#365e4b] disabled:cursor-not-allowed disabled:bg-neutral-200 dark:disabled:bg-[#39423c] disabled:text-neutral-500 dark:disabled:text-[#a0aca3]"
                  title={sendHint ?? "Send (Enter)"}
                >
                  Send
                </button>
              )}
            </div>
            <div className="mt-1.5 min-h-4 text-xs text-neutral-500 dark:text-[#a0aca3]">
              {sendHint ?? "Enter to send · Shift+Enter for a new line"}
            </div>
          </div>
        </div>
      </div>
      {openCitation && (
        <SourcePanel citation={openCitation} onClose={() => setOpenCitation(null)} />
      )}
    </div>
  );
}

function EmptyState({
  hasDocs,
  suggestions,
  canAsk,
  onPick,
  onBrowse,
  dragging,
}: {
  hasDocs: boolean;
  suggestions: string[];
  canAsk: boolean;
  onPick: (q: string) => void;
  onBrowse: () => void;
  dragging: boolean;
}) {
  return (
    <div className="py-8 sm:px-4 lg:px-8">
      <div className="grid items-center gap-8 lg:grid-cols-2 lg:gap-12">
        <div className="vault-welcome-copy text-center lg:text-left">
          <p className="mb-4 text-xs font-medium uppercase tracking-[0.16em] text-[#42735c] dark:text-[#95c9a7]">
            Your research workspace
          </p>
          <h2 className="text-3xl font-semibold leading-tight tracking-tight text-neutral-900 dark:text-neutral-100 sm:text-4xl">
            A conversation starts with a document.
          </h2>
          <p className="mt-4 text-sm leading-7 text-neutral-500 dark:text-[#a0aca3]">
            {hasDocs
              ? "Ask about your sources once processing finishes. Answers cite the exact page or section they come from."
              : "Bring your files together and find answers grounded in your sources."}
          </p>
        </div>
        <section
          aria-label="Upload documents"
          data-dragging={dragging}
          className={`vault-upload flex flex-col items-center gap-4 rounded-2xl border-2 border-dashed px-6 py-10 text-center ${
            dragging ? "border-[#42735c] bg-[#e7f1e9] dark:bg-[#283f30]" : "border-[#dce3dc] dark:border-[#4a5a4d] bg-[#f5f7f4] dark:bg-[#252e27]"
          }`}
        >
          <div className="vault-upload-icon flex h-12 w-12 items-center justify-center rounded-xl border border-[#e0e6df] dark:border-[#3c4b40] bg-white dark:bg-[#202421] text-[#42735c] dark:text-[#95c9a7]">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 16V4m-4 4 4-4 4 4M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" />
            </svg>
          </div>
          <div>
            <h3 className="font-medium text-neutral-800 dark:text-neutral-200">Drop your sources here</h3>
            <p className="mt-2 text-xs leading-5 text-neutral-500 dark:text-[#a0aca3]">PDF, DOCX, TXT or Markdown</p>
            <p className="text-xs leading-5 text-neutral-500 dark:text-[#a0aca3]">Up to 25 MB per file</p>
          </div>
          <button
            type="button"
            onClick={onBrowse}
            className="rounded-lg bg-[#42735c] px-5 py-2.5 text-sm font-medium text-white hover:bg-[#365e4b] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#42735c]"
          >
            Browse files
          </button>
          <p className="text-xs text-neutral-500 dark:text-[#a0aca3]">or drag &amp; drop multiple files</p>
        </section>
      </div>
      {suggestions.length > 0 && (
        <div className="mx-auto mt-8 grid max-w-2xl gap-2 sm:grid-cols-2">
          {suggestions.map((q) => (
            <button
              key={q}
              onClick={() => onPick(q)}
              disabled={!canAsk}
              className="rounded-xl border border-neutral-200 dark:border-[#364139] px-4 py-3 text-left text-sm hover:bg-neutral-50 dark:hover:bg-[#252b27] disabled:opacity-50"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function AttachmentChips({
  docs,
  local,
  duplicates,
  onRemove,
  onDismiss,
}: {
  docs: ChipDoc[];
  local: LocalFile[];
  duplicates: Set<string>;
  onRemove: (id: string) => void;
  onDismiss: (key: string) => void;
}) {
  if (!docs.length && !local.length) return null;
  return (
    <ul className="mb-2 flex flex-wrap gap-2" aria-label="Attached documents">
      {docs.map((d) => {
        const failed = d.status === "failed" || (d.status === "partial" && !d.chatReady);
        const ready = d.chatReady;
        const tone = failed
          ? "border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950 text-red-800 dark:text-red-200"
          : ready
            ? "border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950 text-emerald-900 dark:text-emerald-200"
            : "border-neutral-300 dark:border-[#48544b] bg-neutral-50 dark:bg-[#252b27] text-neutral-700 dark:text-neutral-300";
        return (
          <li
            key={d.id}
            className={`flex max-w-full items-center gap-2 rounded-lg border px-2.5 py-1 text-sm ${tone}`}
            title={d.error ? `${d.error.code}: ${d.error.message ?? ""}` : d.filename}
          >
            {!ready && !failed && (
              <span className="h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-neutral-400 border-t-transparent" />
            )}
            <span className="truncate font-medium">{d.filename}</span>
            <span className="shrink-0 text-xs opacity-80">
              {failed ? errorText(d.error?.code, d.error?.message) : statusLabel(d.status, d.chatReady)}
              {duplicates.has(d.id) && " · already in vault"}
              {d.isLatest === false && ` · v${d.version}, newer version exists`}
            </span>
            <button
              onClick={() => onRemove(d.id)}
              className="shrink-0 rounded px-1 opacity-60 hover:opacity-100"
              aria-label={`Remove ${d.filename} from this chat`}
            >
              ✕
            </button>
          </li>
        );
      })}
      {local.map((f) => (
        <li
          key={f.key}
          className={`flex items-center gap-2 rounded-lg border px-2.5 py-1 text-sm ${
            f.state === "rejected"
              ? "border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950 text-red-800 dark:text-red-200"
              : "border-neutral-300 dark:border-[#48544b] bg-neutral-50 dark:bg-[#252b27] text-neutral-600 dark:text-neutral-400"
          }`}
        >
          {f.state === "uploading" && (
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-neutral-400 border-t-transparent" />
          )}
          <span className="truncate font-medium">{f.filename}</span>
          <span className="text-xs">{f.state === "uploading" ? "Uploading…" : f.error}</span>
          {f.state === "rejected" && (
            <button
              onClick={() => onDismiss(f.key)}
              className="rounded px-1 opacity-60 hover:opacity-100"
              aria-label={`Dismiss ${f.filename}`}
            >
              ✕
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
