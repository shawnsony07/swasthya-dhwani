# Swasthya-Dhwani Doctor Dashboard

Doctor-facing alert, approve/reject dashboard for the triage workflow
described in `docs/architecture.md` (section 12, UX/accessibility; section
9, S3 role gating) and `docs/api_contract.md` (authoritative API contract
for the FastAPI backend at `src/swasthya/api/`).

Scope of this pass: the doctor approval flow (`/dashboard`,
`/dashboard/[taskId]`). Nurse enrollment is explicitly out of scope.

## Stack

- Next.js 16 (App Router, Turbopack), React 19, TypeScript (strict mode)
- Auth.js / NextAuth v5 with the Keycloak OIDC provider (public client,
  authorization code + PKCE — no client secret)
- Tailwind CSS 4
- A small custom i18n context (English/Malayalam) for the highest-visibility
  labels — see "i18n coverage" below

`cacheComponents`/PPR are disabled in `next.config.ts`: every route here is
session-gated and fetches live data per request, so there is nothing worth
statically prerendering.

## Setup

```bash
npm install
cp .env.example .env.local   # then edit values as needed
npm run dev
```

Open http://localhost:3000. Unauthenticated visitors are redirected to
`/login`, which starts the Keycloak sign-in redirect (no custom-styled
form — NextAuth's default redirect is used, per the task scope).

### Environment variables

All read from `.env.local` (see `.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `KEYCLOAK_BASE_URL` | `http://localhost:8081` | Keycloak base URL. The realm `swasthya`'s OIDC issuer is derived as `${KEYCLOAK_BASE_URL}/realms/swasthya`. |
| `KEYCLOAK_CLIENT_ID` | `swasthya-dashboard` | Public OIDC client id registered in Keycloak (no secret: `directAccessGrantsEnabled`, redirect URI `http://localhost:3000/*`). |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Base URL of the FastAPI backend. Exposed to the browser because `EventSource` (SSE) connects to it directly from client code. |
| `AUTH_SECRET` | — (required) | Signs/encrypts NextAuth session cookies/JWTs. Generate with `npx auth secret` or `openssl rand -base64 32`. |
| `AUTH_URL` | `http://localhost:3000` | Canonical origin NextAuth uses for callback URLs; must match a redirect URI registered on the Keycloak client. |

### Running the backend locally

The FastAPI backend is not a dependency of `npm run dev` itself, but the
dashboard has nothing to talk to without it. From `dashboard/`:

```bash
DATABASE_URL="sqlite:///demo.db" KEYCLOAK_BASE_URL="http://localhost:8081" \
  python -m uvicorn swasthya.api.app:app --app-dir ../src --port 8000
```

(A file-based SQLite DB, not `:memory:`, if you want to seed test data from
a separate script while the server runs — see below.)

## Auth model

- NextAuth v5 (`src/auth.ts`) with the Keycloak provider, PKCE + state
  checks, JWT session strategy. The Keycloak access token is decoded
  (`realm_access.roles`) once at sign-in and stored on the session JWT;
  it's refreshed via the refresh-token grant when within 10s of expiry.
- `session.accessToken` is attached as `Authorization: Bearer <token>` on
  every call to the FastAPI backend (`src/lib/api.ts`).
- `session.roles` (`doctor` | `nurse` | `admin`) drives the Approve/Reject
  button visibility client-side. **This is UI-only, defense-in-depth** —
  the backend independently enforces `require_role(...)` server-side on
  `/tasks/{id}/approve` and `/tasks/{id}/reject`, which is the real gate.
- `src/proxy.ts` (Next 16's middleware convention, renamed per its own
  deprecation notice) redirects any unauthenticated request to `/login`.
- `GET /alerts/stream` is consumed via the browser's native `EventSource`,
  which cannot set an `Authorization` header — per the contract, the token
  is passed as `?token=` instead: `new EventSource(`${API_BASE}/alerts/stream?token=${jwt}`)`.
  This is implemented in `src/app/dashboard/useTasks.ts`.

## Pages

- `/login` — Keycloak sign-in redirect.
- `/dashboard` — alert list. Fetches `GET /tasks` on load, live-updates via
  SSE, and re-fetches `GET /tasks` on every SSE (re)connect (SSE never
  replays missed events, per the contract). "Needs approval" / "All" filter
  tabs.
- `/dashboard/[taskId]` — fetches `GET /tasks/{id}`; renders the raw vs.
  interpreted vs. confidence panel (`src/components/TriagePanel.tsx`),
  labelling interpreted text "machine-interpreted". `triage_snapshot: null`
  renders "No snapshot available" rather than crashing. Doctor-role sessions
  see Approve/Reject; Reject requires a non-empty reason (validated
  client-side before submit, and the backend's 422 on an empty one is
  still surfaced if it ever gets through). A 409 (illegal transition, e.g.
  already approved by someone else) is shown as an inline error, not
  swallowed.

A persistent amber footer ("Synthetic / demo data — not a real clinical
tool") appears on every page, per the architecture doc's privacy-honesty
requirement.

## i18n coverage

A small custom context (`src/lib/i18n.ts` + `LocaleClientProvider`), not
next-intl — chosen to avoid pulling in locale-subpath routing/middleware
for a pass that only needs label-swapping. Persisted to `localStorage`;
toggle button in the nav bar.

**Translated:** nav title/sign-out/signed-in-as, filter tabs, all six task
state labels, all four tier labels, Approve/Reject button text, the
time-critical badge, the synthetic-data footer.

**Not translated (left for a later pass):** triage snapshot field labels
(raw transcript, interpreted text, confidence, impairment signals, speech
onset, confirmed-by, symptoms/warning-signs lists), error/loading messages,
the reject-reason form, and the login page's static copy.

## Accessibility notes

- Semantic `<button>`/`<nav>`/`<main>`/`<dl>` throughout — no `<div
  onClick>`.
- Every interactive element has a visible `focus-visible` outline
  (Tailwind `focus-visible:outline` utilities).
- State/tier/time-critical indicators always pair color with an icon and a
  text label (never color alone) — see `src/components/badges.tsx`.
- Confidence is shown as both a number and a progress-bar visual
  indicator, each with `role="progressbar"`/`aria-value*`.
- Error states use `role="alert"`.

## Verification performed

- `npm install`, `npm run build` (Turbopack, TypeScript strict) — clean.
- `npm run dev` on port 3000.
- A real Keycloak authorization-code + PKCE round trip was scripted
  end-to-end (not just "code that should work"): CSRF token →
  `/api/auth/signin/keycloak` → Keycloak's hosted login form → submitted
  `doctor1`/`doctor1pass` → followed the callback → confirmed
  `GET /api/auth/session` returns `roles: ["doctor"]`, `username:
  "doctor1"`, and a real access token whose decoded `realm_access.roles`
  claim is `["doctor"]`. Repeated for `nurse1`/`nurse1pass` → confirmed
  `roles: ["nurse"]` (no `doctor` role, so no Approve/Reject buttons are
  rendered by `/dashboard/[taskId]`).
- Started the FastAPI backend against a file-based SQLite DB, seeded two
  tasks directly via `swasthya.workflow.weft_workflow` (one time-critical
  C1 stroke case with a full triage snapshot in `awaiting_approval`, one
  `human_handoff` case with `triage_snapshot: null`), and confirmed both
  render via `GET /tasks` / `GET /tasks/{id}` with the exact shapes the
  frontend expects.
- Exercised the live API directly with real tokens: doctor approve → 200;
  nurse approve → 403; re-approving an already-approved task → 409 with
  the `IllegalTransitionError` message surfaced; doctor reject with an
  empty reason → 422; doctor reject with a real reason on a
  `human_handoff` task → 200, state `working`.
- Confirmed middleware/proxy gating: `/dashboard` without a session cookie
  → 307 to `/login`; with a valid session cookie → 200.
