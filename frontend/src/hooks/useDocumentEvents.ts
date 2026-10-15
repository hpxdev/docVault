import { useEffect, useRef, useState } from "react";

import { API_BASE } from "../api/client";
import type { StatusPayload } from "../api/types";

/** Live status for a set of documents over GET /documents/events (snapshot, then changes).
 * EventSource reconnects on its own if the connection drops. */
export function useDocumentEvents(
  ids: string[],
  onChange?: (payload: StatusPayload) => void,
): Record<string, StatusPayload> {
  const [statuses, setStatuses] = useState<Record<string, StatusPayload>>({});
  const callback = useRef(onChange);
  callback.current = onChange;
  const key = [...new Set(ids)].sort().join(",");

  useEffect(() => {
    if (!key) return;
    const source = new EventSource(`${API_BASE}/documents/events?ids=${key}`);
    const handle = (event: MessageEvent<string>) => {
      const payload = JSON.parse(event.data) as StatusPayload;
      setStatuses((prev) => ({ ...prev, [payload.id]: payload }));
      callback.current?.(payload);
    };
    const handleDeleted = (event: MessageEvent<string>) => {
      const payload = JSON.parse(event.data) as { id: string };
      setStatuses((prev) => ({
        ...prev,
        [payload.id]: { ...(prev[payload.id] ?? {}), id: payload.id, deleted: true } as StatusPayload,
      }));
      callback.current?.({ id: payload.id, deleted: true } as StatusPayload);
    };
    source.addEventListener("snapshot", handle);
    source.addEventListener("status", handle);
    source.addEventListener("deleted", handleDeleted);
    return () => source.close();
  }, [key]);

  return statuses;
}
