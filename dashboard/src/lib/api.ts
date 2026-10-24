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

export function fetchAuditTimeline(
  accessToken: string | undefined,
  taskId: string
): Promise<AuditTimeline> {
  return request<AuditTimeline>(
    `/tasks/${encodeURIComponent(taskId)}/audit`,
    accessToken
  );
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
