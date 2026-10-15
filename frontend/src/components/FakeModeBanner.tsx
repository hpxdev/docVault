import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";

export function useReadiness() {
  return useQuery({ queryKey: ["ready"], queryFn: api.ready, refetchInterval: 30_000 });
}

/** Shown whenever the backend runs with AI_PROVIDER=fake, so fake output is never mistaken for
 * a real model's. Also surfaces a missing worker or AI configuration. */
export function StatusBanner() {
  const { data, error } = useReadiness();
  if (error) {
    return (
      <div className="bg-red-600 px-4 py-1.5 text-center text-sm text-white">
        Cannot reach the API. Start the backend with <code>docker compose up</code>.
      </div>
    );
  }
  if (!data) return null;
  const ai = data.checks.ai;
  return (
    <>
      {ai.ai_mode === "fake" && (
        <div className="bg-amber-400 px-4 py-1.5 text-center text-sm font-semibold text-amber-950">
          FAKE AI MODE — answers and insights come from deterministic test doubles, not a real
          model.
        </div>
      )}
      {!ai.ok && (
        <div className="bg-red-600 px-4 py-1.5 text-center text-sm text-white">
          AI is not configured ({ai.error}). Set OPENAI_API_KEY in .env and restart.
        </div>
      )}
      {!data.checks.worker.ok && (
        <div className="bg-orange-600 px-4 py-1.5 text-center text-sm text-white">
          No background worker is running: uploads will wait in the queue.
        </div>
      )}
    </>
  );
}
