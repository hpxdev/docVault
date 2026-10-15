import { useQuery } from "@tanstack/react-query";

import { api, ApiError } from "../api/client";
import type { ComparisonOut, SourceRef } from "../api/types";

/** Page/section chip for one cited source; PDF pages open the original file at that page. */
function RefChip({ src }: { src: SourceRef }) {
  const label = src.pages.length
    ? `p. ${src.pages.join(", ")}`
    : src.sections?.length
      ? `§ ${src.sections.join(", ")}`
      : null;
  if (!label) return null;
  const chip = (
    <span className="rounded bg-neutral-200 px-1.5 text-xs leading-5 text-neutral-700">
      {src.label} · {label}
    </span>
  );
  return src.pages.length ? (
    <a
      href={`${api.fileUrl(src.document_id)}#page=${src.pages[0]}`}
      target="_blank"
      rel="noreferrer"
      className="hover:opacity-80"
      title="Open the original at this page"
    >
      {chip}
    </a>
  ) : (
    chip
  );
}

export function ComparisonView({ comparisonId, onBack }: { comparisonId: string; onBack: () => void }) {
  const query = useQuery({
    queryKey: ["comparison", comparisonId],
    queryFn: () => api.getComparison(comparisonId),
    retry: false,
  });
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="flex items-center gap-3 border-b border-neutral-200 px-6 py-3">
        <button onClick={onBack} className="rounded px-2 py-1 text-sm text-neutral-600 hover:bg-neutral-100">
          ← Library
        </button>
        <h1 className="font-semibold">Comparison</h1>
      </header>
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {query.isLoading && <div className="text-neutral-500">Loading…</div>}
        {query.error && (
          <div className="text-red-700">
            {query.error instanceof ApiError && query.error.status === 404
              ? "This comparison no longer exists (one of its documents was deleted)."
              : "Could not load the comparison."}
          </div>
        )}
        {query.data && <ComparisonBody data={query.data} />}
      </div>
    </div>
  );
}

function ComparisonBody({ data }: { data: ComparisonOut }) {
  const partial = Object.entries(data.coverage.documents as Record<string, { complete: boolean }>)
    .filter(([, c]) => !c.complete)
    .map(([label]) => label);
  const validation = data.coverage.validation as { dropped_key_points: number; dropped_refs: number };
  const uncited = data.differences.flatMap((d) => d.positions).filter((p) => !p.addressed).length;
  return (
    <div className="mx-auto max-w-5xl space-y-6 text-sm">
      {data.ai_mode === "fake" && (
        <div className="rounded bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-900">
          FAKE AI MODE — placeholder comparison from the test double
        </div>
      )}
      <section>
        <ul className="flex flex-wrap gap-2">
          {data.documents.map((d) => (
            <li key={d.id} className="rounded-lg border border-neutral-200 px-2.5 py-1">
              <span className="font-semibold">{d.label}</span> {d.filename}
              <span className="text-neutral-500"> · v{d.version}</span>
            </li>
          ))}
        </ul>
        {data.same_document_versions && (
          <p className="mt-2 text-neutral-600">These are versions of one document, oldest first.</p>
        )}
        {data.focus && (
          <p className="mt-2 text-neutral-600">
            Focus: <span className="font-medium">{data.focus}</span>
            {data.focus_covered === false && " — none of the documents addresses it."}
          </p>
        )}
      </section>
      <section>
        <h2 className="mb-1 text-xs font-semibold uppercase text-neutral-500">Overview</h2>
        <p>{data.overview}</p>
      </section>
      <section>
        <h2 className="mb-2 text-xs font-semibold uppercase text-neutral-500">Differences</h2>
        {data.differences.length === 0 ? (
          <p className="text-neutral-500">No verifiable differences were found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-neutral-500">
                  <th className="border-b border-neutral-200 py-2 pr-4 font-medium">Aspect</th>
                  {data.documents.map((d) => (
                    <th key={d.id} className="border-b border-neutral-200 py-2 pr-4 font-medium">
                      {d.label} · v{d.version}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.differences.map((diff, i) => (
                  <tr key={i} className="align-top">
                    <td className="border-b border-neutral-100 py-2 pr-4 font-medium">{diff.aspect}</td>
                    {diff.positions.map((p) => (
                      <td key={p.label} className="border-b border-neutral-100 py-2 pr-4">
                        <div className={p.addressed ? "" : "italic text-neutral-500"}>{p.statement}</div>
                        {p.addressed && (
                          <div className="mt-1">
                            <RefChip src={p} />
                          </div>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section>
        <h2 className="mb-2 text-xs font-semibold uppercase text-neutral-500">In common</h2>
        {data.similarities.length === 0 ? (
          <p className="text-neutral-500">No verifiable similarities were found.</p>
        ) : (
          <ul className="space-y-2">
            {data.similarities.map((s, i) => (
              <li key={i}>
                <div>{s.text}</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {s.sources.map((src) => (
                    <RefChip key={src.label} src={src} />
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <footer className="space-y-1 border-t border-neutral-200 pt-3 text-xs text-neutral-500">
        {partial.length > 0 && (
          <div className="text-amber-800">
            {partial.join(", ")} {partial.length === 1 ? "was" : "were"} too long to compare in full; only the
            parts most relevant to the focus (or evenly spread parts) were used.
          </div>
        )}
        <div>
          Every point cites pages or sections checked by the server
          {validation.dropped_key_points > 0 &&
            `; ${validation.dropped_key_points} point(s) without verifiable sources were dropped`}
          {uncited > 0 && `; ${uncited} position(s) shown in grey have no verified source`}.
        </div>
        <div>
          {data.model} · {data.prompt_version} · {data.cached ? "stored result (no AI cost)" : "new"} ·{" "}
          {new Date(data.created_at).toLocaleString()}
        </div>
      </footer>
    </div>
  );
}
