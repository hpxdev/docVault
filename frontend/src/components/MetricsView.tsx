import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { formatBytes, formatMs, formatRate, formatUsd } from "../lib/format";

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-neutral-200 dark:border-[#364139] p-4">
      <div className="text-xs uppercase tracking-wide text-neutral-500 dark:text-[#a0aca3]">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-neutral-500 dark:text-[#a0aca3]">{sub}</div>}
    </div>
  );
}

const WINDOWS = ["1h", "24h", "7d", "all"] as const;

export function MetricsView() {
  const [window, setWindow] = useState<(typeof WINDOWS)[number]>("24h");
  const docs = useQuery({ queryKey: ["metrics", "documents"], queryFn: api.documentMetrics, refetchInterval: 15_000 });
  const proc = useQuery({
    queryKey: ["metrics", "processing", window],
    queryFn: () => api.processingMetrics(window),
    refetchInterval: 15_000,
  });

  return (
    <div className="h-full min-w-0 flex-1 overflow-y-auto">
      <header className="flex items-center gap-3 border-b border-neutral-200 dark:border-[#364139] px-6 py-3">
        <h1 className="mr-auto font-semibold">Metrics</h1>
        <div className="flex rounded-lg border border-neutral-300 dark:border-[#48544b] p-0.5 text-sm" role="group" aria-label="Time window">
          {WINDOWS.map((w) => (
            <button
              key={w}
              onClick={() => setWindow(w)}
              className={`rounded-md px-2.5 py-1 ${w === window ? "bg-neutral-900 text-white" : "hover:bg-neutral-100 dark:hover:bg-[#2c332e]"}`}
            >
              {w}
            </button>
          ))}
        </div>
      </header>
      <div className="mx-auto max-w-5xl space-y-8 px-6 py-6">
        {(docs.error || proc.error) && <div className="text-red-700 dark:text-red-300">Could not load metrics.</div>}
        {docs.data && (
          <section>
            <h2 className="mb-3 font-semibold">Documents</h2>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Card label="Documents" value={String(docs.data.documents.total)} sub={`${docs.data.documents.chat_ready} chat-ready`} />
              <Card label="Pages" value={String(docs.data.content.total_pages)} sub={`avg ${docs.data.content.average_pages.value ?? "—"} per PDF`} />
              <Card label="Chunks" value={String(docs.data.content.total_chunks)} />
              <Card label="Stored" value={formatBytes(docs.data.content.total_bytes)} />
            </div>
            <div className="mt-3 text-sm text-neutral-600 dark:text-neutral-400">
              By status:{" "}
              {Object.entries(docs.data.documents.by_status).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"}
              {"  ·  "}By type:{" "}
              {Object.entries(docs.data.documents.by_file_type).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"}
            </div>
          </section>
        )}
        {proc.data && (
          <>
            <section>
              <h2 className="mb-3 font-semibold">AI usage ({window})</h2>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Card label="Estimated cost" value={formatUsd(proc.data.ai.estimated_cost_usd)} sub={`all time ${formatUsd(proc.data.ai.estimated_spend_all_time_usd)} of ${formatUsd(proc.data.ai.spend_limit_usd)} cap`} />
                <Card label="AI calls" value={String(proc.data.ai.calls)} sub={`errors ${formatRate(proc.data.ai.error_rate)}`} />
                <Card label="Input tokens" value={proc.data.ai.input_tokens.toLocaleString()} />
                <Card label="Output tokens" value={proc.data.ai.output_tokens.toLocaleString()} />
              </div>
              <p className="mt-2 text-xs text-neutral-500 dark:text-[#a0aca3]">Costs are estimates from token counts and configured prices, not invoice amounts.</p>
              {proc.data.ai.by_purpose_and_model.length > 0 && (
                <table className="mt-3 w-full text-left text-sm">
                  <thead className="text-xs uppercase text-neutral-500 dark:text-[#a0aca3]">
                    <tr>
                      <th className="py-1 pr-3 font-medium">Purpose</th>
                      <th className="py-1 pr-3 font-medium">Model</th>
                      <th className="py-1 pr-3 text-right font-medium">Calls</th>
                      <th className="py-1 pr-3 text-right font-medium">Tokens in / out</th>
                      <th className="py-1 text-right font-medium">Est. cost</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-100 tabular-nums">
                    {proc.data.ai.by_purpose_and_model.map((r) => (
                      <tr key={`${r.purpose}-${r.model}`}>
                        <td className="py-1 pr-3">{r.purpose}</td>
                        <td className="py-1 pr-3">{r.model}</td>
                        <td className="py-1 pr-3 text-right">{r.calls}</td>
                        <td className="py-1 pr-3 text-right">
                          {r.input_tokens.toLocaleString()} / {r.output_tokens.toLocaleString()}
                        </td>
                        <td className="py-1 text-right">{formatUsd(r.estimated_cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
            <section>
              <h2 className="mb-3 font-semibold">Chat ({window})</h2>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Card label="Questions" value={String(proc.data.chat.questions)} />
                <Card label="Not found" value={formatRate(proc.data.chat.not_found_rate)} />
                <Card label="First token p50 / p95" value={formatMs(proc.data.chat.first_token_ms.p50)} sub={`p95 ${formatMs(proc.data.chat.first_token_ms.p95)}`} />
                <Card label="Citations per answer" value={proc.data.chat.avg_citations_per_answer.value?.toFixed(2) ?? "—"} sub={`unsupported ${formatRate(proc.data.chat.unsupported_rate)}`} />
              </div>
            </section>
            <section>
              <h2 className="mb-3 font-semibold">Processing ({window})</h2>
              <table className="w-full text-left text-sm">
                <thead className="text-xs uppercase text-neutral-500 dark:text-[#a0aca3]">
                  <tr>
                    <th className="py-1 pr-3 font-medium">Stage</th>
                    <th className="py-1 pr-3 font-medium">Success rate</th>
                    <th className="py-1 pr-3 font-medium">Duration p50 / p95</th>
                    <th className="py-1 pr-3 font-medium">Retries</th>
                    <th className="py-1 font-medium">Failures</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100 tabular-nums">
                  {(["extract", "index", "insights"] as const).map((s) => {
                    const m = proc.data!.stages[s];
                    return (
                      <tr key={s}>
                        <td className="py-1.5 pr-3 font-medium">{s}</td>
                        <td className="py-1.5 pr-3">{formatRate(m.success_rate)}</td>
                        <td className="py-1.5 pr-3">
                          {formatMs(m.duration_ms.p50)} / {formatMs(m.duration_ms.p95)}
                        </td>
                        <td className="py-1.5 pr-3">{m.retries}</td>
                        <td className="py-1.5">
                          {Object.entries(m.failures_by_code).map(([k, v]) => `${k} ${v}`).join(", ") || "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="mt-3 text-sm text-neutral-600 dark:text-neutral-400">
                Upload → chat-ready: p50 {formatMs(proc.data.upload_to_chat_ready_ms.p50)}, p95{" "}
                {formatMs(proc.data.upload_to_chat_ready_ms.p95)} · Queue depth:{" "}
                {Object.entries(proc.data.queues).map(([k, v]) => `${k} ${v ?? "?"}`).join(", ")}
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
