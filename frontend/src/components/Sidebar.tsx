import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { SessionOut } from "../api/types";
import { relativeTime } from "../lib/format";

export type View = "chat" | "library" | "metrics" | "compare";

interface Props {
  view: View;
  activeSessionId: string | null;
  onSelectSession: (id: string | null) => void;
  onView: (view: View) => void;
}

export function Sidebar({ view, activeSessionId, onSelectSession, onView }: Props) {
  const queryClient = useQueryClient();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.listSessions });
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => api.updateSession(id, { title }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sessions"] }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteSession(id),
    onSuccess: (_, id) => {
      if (id === activeSessionId) onSelectSession(null);
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  const startEdit = (s: SessionOut) => {
    setEditing(s.id);
    setDraft(s.title);
  };
  const commitEdit = (id: string) => {
    const title = draft.trim();
    if (title) rename.mutate({ id, title });
    setEditing(null);
  };

  const navButton = (target: View, label: string) => (
    <button
      onClick={() => onView(target)}
      className={`w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-neutral-800 ${
        view === target ? "bg-neutral-800 text-white" : "text-neutral-300"
      }`}
    >
      {label}
    </button>
  );

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col bg-[#181c19] text-neutral-100 max-md:hidden">
      <div className="px-5 pb-2 pt-6 text-lg font-semibold tracking-tight">Document vault</div>
      <div className="p-4">
        <button
          onClick={() => {
            onSelectSession(null);
          }}
          className="w-full rounded-lg border border-[#465148] bg-[#29332c] px-3 py-2.5 text-left text-sm font-medium hover:bg-[#354239]"
        >
          + New chat
        </button>
      </div>
      <nav className="space-y-1 px-3">
        {navButton("library", "Library")}
        {navButton("metrics", "Metrics")}
      </nav>
      <div className="mt-4 px-4 text-xs font-semibold uppercase tracking-wide text-neutral-500 dark:text-[#a0aca3]">
        Chats
      </div>
      <ul className="mt-1 flex-1 space-y-0.5 overflow-y-auto px-2 pb-4">
        {sessions.isLoading && <li className="px-2 py-1 text-sm text-neutral-500 dark:text-[#a0aca3]">Loading…</li>}
        {sessions.error && (
          <li className="px-2 py-1 text-sm text-red-400">Could not load chats.</li>
        )}
        {sessions.data?.items.length === 0 && (
          <li className="px-2 py-1 text-sm text-neutral-500 dark:text-[#a0aca3]">No chats yet.</li>
        )}
        {sessions.data?.items.map((s) => (
          <li key={s.id} className="group">
            {editing === s.id ? (
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => commitEdit(s.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitEdit(s.id);
                  if (e.key === "Escape") setEditing(null);
                }}
                className="w-full rounded bg-neutral-800 px-2 py-1.5 text-sm outline-none ring-1 ring-neutral-600"
                aria-label="Chat title"
              />
            ) : (
              <div
                className={`flex items-center rounded-lg ${
                  view === "chat" && s.id === activeSessionId ? "bg-neutral-800" : "hover:bg-neutral-800/60"
                }`}
              >
                <button
                  onClick={() => {
                    onSelectSession(s.id);
                  }}
                  className="min-w-0 flex-1 px-2 py-1.5 text-left"
                  title={s.title}
                >
                  <div className="truncate text-sm">{s.title}</div>
                  <div className="text-xs text-neutral-500 dark:text-[#a0aca3]">
                    {s.scope_mode === "all" ? "Whole vault" : `${s.documents.length} doc(s)`} ·{" "}
                    {relativeTime(s.updated_at)}
                  </div>
                </button>
                <div className="hidden shrink-0 gap-1 pr-1 group-hover:flex group-focus-within:flex">
                  <button
                    onClick={() => startEdit(s)}
                    className="rounded px-1 text-xs text-neutral-400 hover:text-white"
                    aria-label={`Rename ${s.title}`}
                  >
                    Rename
                  </button>
                  <button
                    onClick={() => {
                      if (confirm(`Delete chat "${s.title}"?`)) remove.mutate(s.id);
                    }}
                    className="rounded px-1 text-xs text-neutral-400 hover:text-red-400"
                    aria-label={`Delete ${s.title}`}
                  >
                    Delete
                  </button>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="border-t border-neutral-800 px-4 py-3 text-xs text-neutral-500 dark:text-[#a0aca3]">
        Local single-user demo · no authentication
      </div>
    </aside>
  );
}
