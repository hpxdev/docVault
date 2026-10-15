import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { api } from "./api/client";
import type { DocumentOut } from "./api/types";
import { ChatView } from "./components/ChatView";
import { ComparisonView } from "./components/ComparisonView";
import { StatusBanner } from "./components/FakeModeBanner";
import { LibraryView } from "./components/LibraryView";
import { MetricsView } from "./components/MetricsView";
import { Sidebar, type View } from "./components/Sidebar";

interface Route {
  view: View;
  sessionId: string | null;
  comparisonId?: string | null;
}

const UUID = /^[0-9a-f-]{36}$/i;

/** Hash routes: #/chat, #/chat/<session id>, #/library, #/metrics, #/compare/<comparison id>
 * (refresh and Back work). */
function parseHash(hash: string): Route {
  const [, view, id] = hash.replace(/^#/, "").split("/");
  if (view === "library" || view === "metrics") return { view, sessionId: null };
  if (view === "compare" && id && UUID.test(id)) return { view, sessionId: null, comparisonId: id };
  return { view: "chat", sessionId: id && UUID.test(id) ? id : null };
}

function toHash({ view, sessionId, comparisonId }: Route): string {
  if (view === "compare") return `#/compare/${comparisonId}`;
  return view === "chat" ? `#/chat${sessionId ? `/${sessionId}` : ""}` : `#/${view}`;
}

export default function App() {
  const queryClient = useQueryClient();
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onHash = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigate = useCallback((next: Route) => {
    setRoute(next);
    const hash = toHash(next);
    if (window.location.hash !== hash) window.history.pushState(null, "", hash);
  }, []);

  async function chatWith(doc: DocumentOut) {
    const session = await api.createSession({ document_ids: [doc.id], title: doc.filename });
    queryClient.setQueryData(["session", session.id], session);
    await queryClient.invalidateQueries({ queryKey: ["sessions"] });
    navigate({ view: "chat", sessionId: session.id });
  }

  return (
    <div className="flex h-full flex-col">
      <StatusBanner />
      <div className="flex min-h-0 flex-1">
        <Sidebar
          view={route.view}
          activeSessionId={route.sessionId}
          onSelectSession={(id) => navigate({ view: "chat", sessionId: id })}
          onView={(view) =>
            navigate({ view, sessionId: view === "chat" ? route.sessionId : null })
          }
        />
        <main className="flex min-w-0 flex-1">
          {route.view === "chat" && (
            <ChatView
              sessionId={route.sessionId}
              onSessionCreated={(id) => navigate({ view: "chat", sessionId: id })}
            />
          )}
          {route.view === "library" && (
            <LibraryView
              onChatWith={(d) => void chatWith(d)}
              onOpenComparison={(id) => navigate({ view: "compare", sessionId: null, comparisonId: id })}
            />
          )}
          {route.view === "compare" && route.comparisonId && (
            <ComparisonView
              comparisonId={route.comparisonId}
              onBack={() => navigate({ view: "library", sessionId: null })}
            />
          )}
          {route.view === "metrics" && <MetricsView />}
        </main>
      </div>
    </div>
  );
}
