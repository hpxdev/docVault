import Markdown from "react-markdown";

import type { CitationOut, MessageOut } from "../api/types";

/** `[S1]` markers become links that the custom `a` renderer turns into citation chips. */
function withCitationLinks(text: string): string {
  return text.replace(/\[S(\d+)\]/g, "[S$1](#cite-$1)");
}

function CitationChip({
  marker,
  citation,
  onOpen,
}: {
  marker: string;
  citation?: CitationOut;
  onOpen: (c: CitationOut) => void;
}) {
  if (!citation) {
    // Streaming: markers arrive before the server has validated them.
    return (
      <span className="mx-0.5 rounded bg-neutral-200 px-1 text-[0.7rem] font-medium text-neutral-500">
        {marker}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onOpen(citation)}
      title={`${citation.document_name} · ${citation.location}`}
      className="mx-0.5 inline-flex items-center rounded bg-emerald-100 px-1.5 text-[0.7rem] font-semibold text-emerald-800 align-baseline hover:bg-emerald-200 focus:outline-none focus:ring-2 focus:ring-emerald-500"
    >
      {marker} · {citation.location}
    </button>
  );
}

export function AnswerText({
  content,
  citations,
  onOpenCitation,
}: {
  content: string;
  citations: CitationOut[];
  onOpenCitation: (c: CitationOut) => void;
}) {
  const byMarker = new Map(citations.map((c) => [c.marker, c]));
  return (
    <div className="markdown leading-relaxed">
      <Markdown
        components={{
          a: ({ href, children }) => {
            const match = href?.match(/^#cite-(\d+)$/);
            if (match) {
              const marker = `S${match[1]}`;
              return (
                <CitationChip
                  marker={marker}
                  citation={byMarker.get(marker)}
                  onOpen={onOpenCitation}
                />
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer" className="text-blue-700 underline">
                {children}
              </a>
            );
          },
        }}
      >
        {withCitationLinks(content)}
      </Markdown>
    </div>
  );
}

export function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-neutral-100 px-4 py-2.5">
        {content}
      </div>
    </div>
  );
}

const STATUS_STYLE: Record<string, { box: string; label: string } | undefined> = {
  not_found: {
    box: "border border-amber-300 bg-amber-50",
    label: "Not found in the selected documents",
  },
  unsupported: {
    box: "border border-red-300 bg-red-50",
    label: "No verifiable citation — treat this answer with caution",
  },
  error: { box: "border border-red-300 bg-red-50", label: "The answer could not be generated" },
};

export function AssistantMessage({
  message,
  onOpenCitation,
}: {
  message: MessageOut;
  onOpenCitation: (c: CitationOut) => void;
}) {
  const style = STATUS_STYLE[message.answer_status ?? ""];
  return (
    <div className={`rounded-2xl ${style ? `${style.box} px-4 py-3` : "px-1"}`}>
      {style && (
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral-600">
          {style.label}
          {message.error_code ? ` (${message.error_code})` : ""}
        </div>
      )}
      <AnswerText
        content={message.content}
        citations={message.citations}
        onOpenCitation={onOpenCitation}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-neutral-500">
        {message.interrupted && (
          <span className="rounded bg-neutral-200 px-1.5 py-0.5">Stopped</span>
        )}
        {message.ai_mode === "fake" && (
          <span className="rounded bg-amber-200 px-1.5 py-0.5 text-amber-900">fake AI</span>
        )}
        {message.citations.length > 0 && <span>{message.citations.length} source(s)</span>}
        {message.latency_ms.total !== null && message.latency_ms.total !== undefined && (
          <span>{(message.latency_ms.total / 1000).toFixed(1)} s</span>
        )}
        {message.usage.estimated_cost_usd > 0 && (
          <span title="Estimated from token counts">
            ≈ ${message.usage.estimated_cost_usd.toFixed(5)}
          </span>
        )}
        {message.standalone_query && message.standalone_query !== "" && (
          <span className="truncate" title={`Searched for: ${message.standalone_query}`}>
            searched: “{message.standalone_query}”
          </span>
        )}
      </div>
    </div>
  );
}
