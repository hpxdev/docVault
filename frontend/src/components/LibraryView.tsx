import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "../api/client";
import type { DocumentOut } from "../api/types";
import { useDocumentEvents } from "../hooks/useDocumentEvents";
import { errorText, formatBytes, relativeTime, statusLabel } from "../lib/format";

const STATUS_TONE: Record<string, string> = {
  ready: "bg-emerald-100 text-emerald-800",
  partial: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-800",
  processing: "bg-blue-100 text-blue-800",
  queued: "bg-neutral-200 text-neutral-700",
};

export function LibraryView({ onChatWith }: { onChatWith: (doc: DocumentOut) => void }) {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<DocumentOut | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const docs = useQuery({
    queryKey: ["documents", q, status],
    queryFn: () => api.listDocuments({ limit: 100, q, status }),
  });
  const items = docs.data?.items ?? [];
  const activeIds = items.filter((d) => d.status === "queued" || d.status === "processing").map((d) => d.id);
  useDocumentEvents(activeIds, (p) => {
    if (p.status !== "processing" && p.status !== "queued") {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["documents"] });
  const reprocess = useMutation({
    mutationFn: (id: string) => api.reprocess(id),
    onSuccess: refresh,
    onError: (err) => setNotice(err instanceof ApiError ? err.message : "Reprocess failed."),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteDocument(id),
    onSuccess: (_, id) => {
      if (selected?.id === id) setSelected(null);
      refresh();
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
    onError: (err) => setNotice(err instanceof ApiError ? err.message : "Delete failed."),
  });
  const upload = useMutation({
    mutationFn: (files: File[]) => api.upload(files.slice(0, 10)),
    onSuccess: (results) => {
      const rejected = results.filter((r) => r.outcome === "rejected");
      setNotice(
        rejected.length
          ? `Rejected: ${rejected.map((r) => `${r.filename} (${errorText(r.error?.code, r.error?.message)})`).join(", ")}`
          : null,
      );
      refresh();
    },
    onError: (err) => setNotice(err instanceof ApiError ? err.message : "Upload failed."),
  });

  return (
    <div className="flex h-full min-w-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-neutral-200 px-6 py-3">
          <h1 className="mr-auto font-semibold">Library</h1>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search filenames…"
            className="rounded-lg border border-neutral-300 px-3 py-1.5 text-sm outline-none focus:border-neutral-500"
            aria-label="Search filenames"
          />
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded-lg border border-neutral-300 px-2 py-1.5 text-sm"
            aria-label="Filter by status"
          >
            <option value="">All statuses</option>
            {["ready", "processing", "queued", "partial", "failed"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <label className="cursor-pointer rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700">
            Upload
            <input
              type="file"
              multiple
              accept=".pdf,.docx,.txt,.md,.markdown"
              className="hidden"
              onChange={(e) => {
                if (e.target.files?.length) upload.mutate(Array.from(e.target.files));
                e.target.value = "";
              }}
            />
          </label>
        </header>
        {notice && (
          <div className="mx-6 mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
            {notice}
          </div>
        )}
        <div className="flex-1 overflow-auto px-6 py-4">
          {docs.isLoading && <div className="text-neutral-500">Loading…</div>}
          {docs.error && <div className="text-red-700">Could not load documents.</div>}
          {docs.data && items.length === 0 && (
            <div className="py-16 text-center text-neutral-500">
              No documents{q || status ? " match these filters" : " yet — upload some to get started"}.
            </div>
          )}
          {items.length > 0 && (
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-neutral-500">
                <tr>
                  <th className="py-2 pr-4 font-medium">Document</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium max-md:hidden">Type</th>
                  <th className="py-2 pr-4 font-medium max-md:hidden">Size</th>
                  <th className="py-2 pr-4 font-medium max-lg:hidden">Category</th>
                  <th className="py-2 pr-4 font-medium max-lg:hidden">Added</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {items.map((d) => (
                  <tr key={d.id} className={selected?.id === d.id ? "bg-neutral-50" : ""}>
                    <td className="max-w-xs py-2.5 pr-4">
                      <button
                        onClick={() => setSelected(d)}
                        className="block max-w-full truncate text-left font-medium hover:underline"
                        title={d.filename}
                      >
                        {d.filename}
                      </button>
                      {d.error && (
                        <div className="truncate text-xs text-red-700" title={d.error.message ?? ""}>
                          {errorText(d.error.code, d.error.message)}
                        </div>
                      )}
                    </td>
                    <td className="py-2.5 pr-4">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[d.status] ?? ""}`}>
                        {statusLabel(d.status, d.chat_ready)}
                      </span>
                    </td>
                    <td className="py-2.5 pr-4 uppercase text-neutral-600 max-md:hidden">
                      {d.file_type}
                      {d.page_count ? ` · ${d.page_count} p` : ""}
                    </td>
                    <td className="py-2.5 pr-4 text-neutral-600 max-md:hidden">{formatBytes(d.size_bytes)}</td>
                    <td className="py-2.5 pr-4 text-neutral-600 max-lg:hidden">{d.category ?? "—"}</td>
                    <td className="py-2.5 pr-4 text-neutral-600 max-lg:hidden">{relativeTime(d.created_at)}</td>
                    <td className="whitespace-nowrap py-2.5 text-right">
                      {d.chat_ready && (
                        <button onClick={() => onChatWith(d)} className="rounded px-2 py-1 text-emerald-700 hover:bg-emerald-50">
                          Chat
                        </button>
                      )}
                      {(d.status === "failed" || d.status === "partial") && (
                        <button
                          onClick={() => reprocess.mutate(d.id)}
                          className="rounded px-2 py-1 text-blue-700 hover:bg-blue-50"
                        >
                          Reprocess
                        </button>
                      )}
                      <button
                        onClick={() => {
                          if (confirm(`Delete "${d.filename}"? Past citations keep their excerpts.`))
                            remove.mutate(d.id);
                        }}
                        className="rounded px-2 py-1 text-red-700 hover:bg-red-50"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
      {selected && <InsightsDrawer doc={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function InsightsDrawer({ doc, onClose }: { doc: DocumentOut; onClose: () => void }) {
  const insights = useQuery({
    queryKey: ["insights", doc.id],
    queryFn: () => api.getInsights(doc.id),
    retry: false,
  });
  const notReady = insights.error instanceof ApiError && insights.error.code === "INSIGHTS_NOT_READY";
  const data = insights.data;
  return (
    <aside
      className="flex h-full w-[28rem] shrink-0 flex-col border-l border-neutral-200 bg-neutral-50 max-lg:absolute max-lg:inset-y-0 max-lg:right-0 max-lg:z-20 max-lg:shadow-xl"
      aria-label="Insights"
    >
      <div className="flex items-start justify-between gap-2 border-b border-neutral-200 p-4">
        <div className="min-w-0">
          <div className="truncate font-semibold" title={doc.filename}>
            {doc.filename}
          </div>
          <div className="text-xs text-neutral-500">
            {doc.file_type.toUpperCase()}
            {doc.page_count ? ` · ${doc.page_count} pages` : ` · ${doc.segment_count ?? 0} sections`}
            {doc.warnings.length > 0 &&
              ` · ${doc.warnings.map((w) => (w.code === "EMPTY_PAGES" ? `empty pages ${(w.pages as number[]).join(", ")}` : w.code)).join("; ")}`}
          </div>
        </div>
        <button onClick={onClose} className="rounded px-2 py-1 text-sm text-neutral-500 hover:bg-neutral-200" aria-label="Close insights">
          ✕
        </button>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto p-4 text-sm">
        {insights.isLoading && <div className="text-neutral-500">Loading insights…</div>}
        {notReady && (
          <div className="text-neutral-600">
            Insights are not available yet (status: {doc.status}).
          </div>
        )}
        {insights.error && !notReady && <div className="text-red-700">Could not load insights.</div>}
        {data && (
          <>
            {data.ai_mode === "fake" && (
              <div className="rounded bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-900">
                FAKE AI MODE — placeholder insights from the test double
              </div>
            )}
            <section>
              <h3 className="mb-1 text-xs font-semibold uppercase text-neutral-500">Summary</h3>
              <p>{data.summary_short}</p>
              <details className="mt-2">
                <summary className="cursor-pointer text-neutral-600">Detailed summary</summary>
                <p className="mt-1 whitespace-pre-wrap">{data.summary_detailed}</p>
              </details>
            </section>
            <section>
              <h3 className="mb-1 text-xs font-semibold uppercase text-neutral-500">Key points</h3>
              <ul className="space-y-1.5">
                {data.key_points.map((kp, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="shrink-0 rounded bg-neutral-200 px-1.5 text-xs leading-5 text-neutral-700">
                      {kp.pages.length ? `p. ${kp.pages.join(", ")}` : `§ ${(kp.sections ?? []).join(", ")}`}
                    </span>
                    <span>{kp.text}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="flex flex-wrap gap-1.5">
              <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
                {data.category}
              </span>
              {data.tags.map((t) => (
                <span key={t} className="rounded-full bg-neutral-200 px-2 py-0.5 text-xs">
                  {t}
                </span>
              ))}
            </section>
            <section>
              <h3 className="mb-1 text-xs font-semibold uppercase text-neutral-500">Tone</h3>
              <p>
                <span className="font-medium">{(data.sentiment.label as string | null) ?? "unknown"}</span>
                {data.sentiment.rationale ? ` — ${data.sentiment.rationale as string}` : ""}
              </p>
            </section>
            {Object.entries(data.entities).some(([, v]) => v.length) && (
              <section>
                <h3 className="mb-1 text-xs font-semibold uppercase text-neutral-500">Entities</h3>
                <dl className="space-y-1">
                  {Object.entries(data.entities)
                    .filter(([, v]) => v.length)
                    .map(([k, v]) => (
                      <div key={k}>
                        <dt className="inline font-medium capitalize">{k}: </dt>
                        <dd className="inline">{v.join("; ")}</dd>
                      </div>
                    ))}
                </dl>
              </section>
            )}
            <section>
              <h3 className="mb-1 text-xs font-semibold uppercase text-neutral-500">Suggested questions</h3>
              <ul className="list-disc space-y-1 pl-5">
                {data.suggested_questions.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </section>
            <div className="text-xs text-neutral-500">
              {data.model} · {data.prompt_version} · coverage {String(data.coverage.segments_covered)}/
              {String(data.coverage.segments_total)} ({String(data.coverage.method)})
            </div>
          </>
        )}
      </div>
      <div className="border-t border-neutral-200 p-4 text-sm">
        <a href={api.fileUrl(doc.id)} target="_blank" rel="noreferrer" className="text-blue-700 underline">
          Open original file
        </a>
      </div>
    </aside>
  );
}
