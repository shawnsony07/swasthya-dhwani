"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { API_BASE_URL, fetchTasks } from "@/lib/api";
import type { TaskSummary } from "@/lib/types";

interface UseTasksResult {
  tasks: TaskSummary[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
  connectionState: "connecting" | "open" | "closed" | "error";
}

/**
 * Fetches GET /tasks on mount and keeps the list live via GET
 * /alerts/stream. Per docs/api_contract.md, SSE never replays missed
 * events, so this also re-fetches GET /tasks whenever the EventSource
 * (re)connects -- not just once on mount -- to catch up after any drop.
 */
export function useTasks(): UseTasksResult {
  const { data: session, status } = useSession();
  const accessToken = session?.accessToken;

  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connectionState, setConnectionState] =
    useState<UseTasksResult["connectionState"]>("connecting");

  const eventSourceRef = useRef<EventSource | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetchTasks(accessToken);
      setTasks(response.tasks);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tasks");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    if (session?.error === "RefreshAccessTokenError") {
      setError("Session expired. Please sign in again.");
      setLoading(false);
      return;
    }
    if (status !== "authenticated" || !accessToken) return;

    // Standard fetch-on-mount: `load`'s setState calls happen inside its
    // async body after the awaited fetch, not synchronously here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();

    const es = new EventSource(
      `${API_BASE_URL}/alerts/stream?token=${encodeURIComponent(accessToken)}`
    );
    eventSourceRef.current = es;
    setConnectionState("connecting");

    es.onopen = () => {
      setConnectionState("open");
      // Re-sync on every (re)connect -- SSE never replays missed events.
      load();
    };

    es.addEventListener("task_update", () => {
      // The event payload is a partial summary; re-fetch the full list so
      // ordering, pagination and any fields not on the event stay correct.
      load();
    });

    es.onerror = () => {
      setConnectionState("error");
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
      setConnectionState("closed");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, accessToken]);

  return { tasks, loading, error, refetch: load, connectionState };
}
