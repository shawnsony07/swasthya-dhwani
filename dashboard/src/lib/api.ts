import type {
  ApiErrorBody,
  AuditTimeline,
  AdminMetrics,
  RoutingBoard,
  TaskDetail,
  TaskListResponse,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  accessToken: string | undefined,
  init: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as ApiErrorBody;
      if (body?.detail) detail = body.detail;
    } catch {
      // non-JSON error body; keep the generic message
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}

export function fetchTasks(
  accessToken: string | undefined,
  params?: { state?: string; limit?: number; cursor?: string }
): Promise<TaskListResponse> {
  const qs = new URLSearchParams();
  if (params?.state) qs.set("state", params.state);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.cursor) qs.set("cursor", params.cursor);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request<TaskListResponse>(`/tasks${suffix}`, accessToken);
}

export function fetchTask(
  accessToken: string | undefined,
  taskId: string
): Promise<TaskDetail> {
  return request<TaskDetail>(
    `/tasks/${encodeURIComponent(taskId)}`,
    accessToken
  );
}

export async function fetchAuditTimeline(
  accessToken: string | undefined,
  taskId: string
): Promise<AuditTimeline> {
  interface RawAuditEvent {
    id: number;
    task_id: string;
    event: string;
    actor: string;
    timestamp: string;
    protocol_version: string;
    model_id: string | null;
    detail: Record<string, unknown>;
  }

  const raw = await request<RawAuditEvent[]>(
    `/tasks/${encodeURIComponent(taskId)}/audit`,
    accessToken
  );
  const events = (Array.isArray(raw) ? raw : []).map((r, idx) => ({
    seq: r.id ?? idx + 1,
    actor: r.actor ?? "system",
    action: r.event ?? "event",
    from_state: (r.detail?.from_state as string) ?? null,
    to_state: (r.detail?.to_state as string) ?? (r.event === "working" ? "working" : r.event === "approval_requested" ? "awaiting_approval" : null),
    note: (r.detail?.reason as string) ?? (Object.keys(r.detail || {}).length > 0 ? JSON.stringify(r.detail) : null),
    ts: r.timestamp ?? new Date().toISOString(),
  }));
  return { task_id: taskId, events };
}

export function approveTask(
  accessToken: string | undefined,
  taskId: string,
  actor: string
): Promise<TaskDetail> {
  return request<TaskDetail>(
    `/tasks/${encodeURIComponent(taskId)}/approve`,
    accessToken,
    {
      method: "POST",
      body: JSON.stringify({ actor }),
    }
  );
}

export function rejectTask(
  accessToken: string | undefined,
  taskId: string,
  actor: string,
  reason: string
): Promise<TaskDetail> {
  return request<TaskDetail>(
    `/tasks/${encodeURIComponent(taskId)}/reject`,
    accessToken,
    {
      method: "POST",
      body: JSON.stringify({ actor, reason }),
    }
  );
}

export function fetchRoutingBoard(
  accessToken: string | undefined
): Promise<RoutingBoard> {
  return request<RoutingBoard>("/admin/routing", accessToken);
}

export function fetchAdminMetrics(
  accessToken: string | undefined
): Promise<AdminMetrics> {
  return request<AdminMetrics>("/admin/metrics", accessToken);
}
