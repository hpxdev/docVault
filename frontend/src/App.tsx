import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "./api/client";
import type { DocumentOut } from "./api/types";
import { ChatView } from "./components/ChatView";
import { StatusBanner } from "./components/FakeModeBanner";
import { LibraryView } from "./components/LibraryView";
import { MetricsView } from "./components/MetricsView";
import { Sidebar, type View } from "./components/Sidebar";

export default function App() {
  const queryClient = useQueryClient();
  const [view, setView] = useState<View>("chat");
  const [sessionId, setSessionId] = useState<string | null>(null);

  async function chatWith(doc: DocumentOut) {
    const session = await api.createSession({ document_ids: [doc.id], title: doc.filename });
    queryClient.setQueryData(["session", session.id], session);
    await queryClient.invalidateQueries({ queryKey: ["sessions"] });
    setSessionId(session.id);
    setView("chat");
  }

  return (
    <div className="flex h-full flex-col">
      <StatusBanner />
      <div className="flex min-h-0 flex-1">
        <Sidebar
          view={view}
          activeSessionId={sessionId}
          onSelectSession={setSessionId}
          onView={setView}
        />
        <main className="flex min-w-0 flex-1">
          {view === "chat" && <ChatView sessionId={sessionId} onSessionCreated={setSessionId} />}
          {view === "library" && <LibraryView onChatWith={(d) => void chatWith(d)} />}
          {view === "metrics" && <MetricsView />}
        </main>
      </div>
    </div>
  );
}
