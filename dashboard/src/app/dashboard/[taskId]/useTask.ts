"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { ApiError, fetchTask } from "@/lib/api";
import type { TaskDetail } from "@/lib/types";

export function useTask(taskId: string) {
  const { data: session, status } = useSession();
  const accessToken = session?.accessToken;

  const [task, setTask] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const detail = await fetchTask(accessToken, taskId);
      setTask(detail);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
      } else {
        setError(err instanceof Error ? err.message : "Failed to load task");
      }
    } finally {
      setLoading(false);
    }
  }, [accessToken, taskId]);

  useEffect(() => {
    // Standard fetch-on-mount/dependency-change: `load`'s own setState
    // calls happen inside its async body (after the awaited fetch), not
    // synchronously in this effect — the lint rule's static check can't
    // see through the async boundary, but there is no cascading
    // synchronous render here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (status !== "authenticated") return;
    load();
  }, [status, load]);

  return { task, setTask, loading, error, notFound, refetch: load };
}
