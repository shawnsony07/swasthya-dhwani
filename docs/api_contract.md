# Doctor-approval API contract

This is the authoritative contract between the FastAPI backend
(`src/swasthya/api/`) and the Next.js dashboard (`dashboard/`). Both are
built against this document — if either side needs to deviate, update this
file first.

Base URL (local dev): `http://localhost:8000`

## Auth

Every endpoint except `/healthz` requires `Authorization: Bearer <JWT>`,
a token issued by Keycloak (realm `swasthya`, see
`docker/keycloak/swasthya-realm.json` for the pre-seeded users/roles:
`doctor1`/`doctor1pass` has the `doctor` role, `nurse1`/`nurse1pass` has
`nurse`, `admin1`/`admin1pass` has `admin`+`doctor`).

- The API validates the JWT's signature against Keycloak's JWKS endpoint
  (`${KEYCLOAK_BASE_URL}/realms/swasthya/protocol/openid-connect/certs`),
  checks `exp`, and reads realm roles from the standard Keycloak claim
  shape: `realm_access.roles: string[]`.
- `GET /tasks`, `GET /tasks/{id}`: any authenticated role.
- `POST /tasks/{id}/approve`: requires the `doctor` role. 403 otherwise.
- `POST /tasks/{id}/reject`: requires `doctor` or `nurse`.
- Dev/offline escape hatch: if `AUTH_DISABLED=true` is set in the API's
  environment, auth is skipped entirely and every request is treated as
  role `admin`. The API logs a loud warning on startup when this is set.
  **Default is auth enabled** — this is an opt-in bypass, not the default.

## Endpoints

### `GET /healthz`
No auth. `200 {"status": "ok"}`.

### `GET /tasks`
Query params: `state` (optional, one of the `TaskState` values — see
`src/swasthya/contracts.py`), `limit` (default 50, max 200), `cursor`
(opaque string from a previous response's `next_cursor`).

```json
{
  "tasks": [
    {
      "task_id": "string",
      "state": "awaiting_approval",
      "tier": "C1",
      "hospital": "stroke_unit_or_tertiary",
      "is_time_critical": true,
      "created_at": "2026-10-24T20:00:00Z",
      "updated_at": "2026-10-24T20:01:00Z"
    }
  ],
  "next_cursor": "string | null"
}
```

Ordered newest-first by `updated_at`.

### `GET /tasks/{task_id}`
Same shape as a list item, plus:

```json
{
  "...": "... all TaskSummary fields ...",
  "patient_identifier_hash": "string",
  "triage_snapshot": {
    "raw_transcript": "string",
    "interpreted_text": "string",
    "interpretation_confidence": 0.82,
    "symptoms": ["chest_pain"],
    "symptom_duration_days": 2,
    "warning_signs_present": ["chest_pain"],
    "speech_impairment_signals": ["slurred"],
    "speech_onset": "new",
    "confirmed_by": "patient",
    "interpreter_model": "gemini-2.5-flash",
    "protocol_version": "2025.11.01"
  }
}
```

`triage_snapshot` is `null` if the task predates the snapshot feature or
was never routed through `finalize_and_route` (shouldn't happen in
practice, but the dashboard must render that case without crashing — show
"No snapshot available", not a blank page).

404 if the task doesn't exist.

### `POST /tasks/{task_id}/approve`
Body: `{"actor": "string"}` (the doctor's username/id — the dashboard fills
this from the authenticated session, not a free-text field the user edits).

Transitions `AWAITING_APPROVAL`/`HUMAN_HANDOFF` → `APPROVED`. Returns the
updated task detail (same shape as `GET /tasks/{task_id}`). 409 if the
task isn't in a state that allows this transition (surface the message
from `IllegalTransitionError`).

### `POST /tasks/{task_id}/reject`
Body: `{"actor": "string", "reason": "string"}` (`reason` required,
non-empty — this calls `weft_workflow.reject_with_reason`, which needs one).

Transitions back to `WORKING`. Returns updated task detail. 409 on an
illegal transition.

### `GET /alerts/stream` (Server-Sent Events)
`Content-Type: text/event-stream`. Implementation note (not a contract
detail, but relevant to both sides): this polls the DB every 2 seconds
rather than a true push — architecture.md's own documented fallback for
loop L7 ("Dashboard polls the task endpoint"). Each event:

```
event: task_update
data: {"task_id": "...", "state": "awaiting_approval", "tier": "C1", "is_time_critical": true, "updated_at": "..."}

```

Sent once per task whenever its `state` is one of `awaiting_approval`,
`auto_escalated`, or `human_handoff` AND its `updated_at` is newer than the
last time that task was sent to this connection. A client reconnect starts
fresh (no replay of missed events — the dashboard should also poll
`GET /tasks` on mount/reconnect to catch up, not rely on SSE alone).

## Error shape

Every non-2xx response:

```json
{"detail": "human-readable message"}
```

(FastAPI's default `HTTPException` shape — nothing custom.)
