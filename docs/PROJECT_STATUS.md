# Swasthya-Dhwani x FluentPath — Project Status

Living handoff document. If this build session gets interrupted, read this
first — it tells you exactly what exists, what's tested, what's not
started, and how to approach what's left, with file references throughout.
The full product vision is in `docs/architecture.md`; this document tracks
*actual build state* against that vision, not the vision itself.

Last updated: 2026-10-25 (mid-build).

## 1. What this project is

A Malayalam voice triage service: a patient or caregiver calls in, an LLM
(Gemini) interprets their speech (including impaired speech — stuttering,
dysarthria, aphasia), reads its understanding back for confirmation, and
only confirmed facts reach a **deterministic rule engine** that decides
clinical acuity — never the model. A doctor approves the resulting
referral through a dashboard. Three safety principles drive every design
decision (see `docs/architecture.md` section 1):

1. The LLM interprets speech; it never chooses the tier.
2. Uncertainty never lowers acuity — it raises the tier floor or hands the
   call to a human.
3. Nothing enters a clinical record unless a human confirmed it, or a
   human overrode it.

## 2. Tech stack (what's actually used, not just planned)

| Layer | Choice | Status |
| --- | --- | --- |
| Language/runtime | Python 3.11+ (actually running on 3.13), Node 22 | Working |
| Voice | LiveKit Agents 1.6.1, Sarvam STT/TTS (`bulbul:v3`, `saarika:v2.5`), Gemini (`gemini-flash-latest` + `gemini-3.1-flash-lite` fallback) | Built, verified against live APIs (see section 5) |
| Rule engine | Pure Python over a JSON matrix (`src/swasthya/protocol/`) | Built, tested, NOT clinically signed off |
| Workflow/DB | SQLAlchemy 2.0 + Alembic, Postgres (SQLite for tests) | Built, tested |
| FHIR | `fhir.resources` (R4B) + httpx against HAPI | Built, tested against mocks; live HAPI in Docker boots and responds |
| API | FastAPI + Keycloak JWT auth + SSE | Built, tested, verified against a live Keycloak |
| Dashboard | Next.js 16 (App Router) + NextAuth v5 + Tailwind | Built, verified via a real OAuth round-trip |
| Action gateway | Allow-list/rate-limit/kill-switch policy engine | Built, tested; **real vendor calls (Twilio) still a stub** — see section 6 |
| Infra | Docker Compose: Postgres, HAPI, Keycloak | Built, booted and verified for real on this machine |

## 3. What's fully built and tested (don't rebuild this)

Each of these has unit tests (157 passing as of this writing — run
`pytest tests/ -v` to confirm) and, where it matters, was verified against
a **live** vendor API or a **live** local service, not just mocks:

- **`src/swasthya/contracts.py`** — every shared data shape (`TriageData`,
  `TaskState`, `ActionRequest`, etc.). Read this first; every other module
  imports from here.
- **`src/swasthya/protocol/`** — the rule engine. Stroke condition (FAST
  symptoms → tier C1), the "never silently default to tier B" fix (T3),
  the speech-impairment acuity floor (T2). `disease_triage_matrix.json`'s
  clinical values are explicitly flagged as unsigned-off placeholders.
- **`src/swasthya/fhir/adapter.py`** — writes Observations/Provenance/
  ServiceRequest/AuditEvent to HAPI. Identifier hashing, retry/circuit
  logic.
- **`src/swasthya/interpreter/`** — `speech_interpreter.interpret_clip`
  (real Gemini calls, verified live — see section 5) and
  `confidence_policy.decide` (the read-back decision table).
- **`src/swasthya/workflow/` + `src/swasthya/db/`** — the task state
  machine. The T4 fix (a timeout can never silently approve with no
  hospital) is structural, not just tested.
- **`src/swasthya/gateway/`** — allow-list, rate limiter, kill switch,
  action dispatch policy. `AllowList.ordered_targets()` for F7's
  "try contacts in priority order." Twilio emergency provider built in
  `src/swasthya/gateway/providers/twilio_provider.py` with 13 tests.
- **`src/swasthya/voice/`** — the LiveKit agent (`agent.py`), the pure
  confirmation-loop state machine (`conversation.py` — read-back,
  re-ask-then-handoff, emergency window, repeat-call task linking), and
  `entrypoint.py` (wires Sarvam/Gemini/the DB/FHIR/the gateway together,
  graceful room disconnect on terminal outcomes).
- **`src/swasthya/api/`** — the doctor-approval REST API, SSE streaming,
  admin kill-switch/roster endpoints, and Twilio status callback webhook.
- **`dashboard/`** — the Next.js app. Verified via a scripted real OAuth
  round-trip against live Keycloak (logged in as both `doctor1` and
  `nurse1`, confirmed role-gated UI).
- **`docker/docker-compose.yml`** — Postgres, HAPI, Keycloak, API,
  Voice-Agent, and Dashboard all declared with inter-service networking.
- **`simulate_e2e.py`** (repo root) — an offline replay harness proving
  the real rule engine + real workflow + real DB agree end to end,
  without needing live credentials. Run it: `python simulate_e2e.py`.

### Credentials status (as of this writing)

All of these are in `docker/.env` and root `.env` (gitignored, never
committed — confirmed via `git check-ignore` and `git log` search):

- `GEMINI_API_KEY` — **verified working** against the live API.
- `SARVAM_API_KEY` — **verified working** (TTS + STT round-trip).
- `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` — **verified
  working** (reached the real LiveKit Cloud project, listed 0 rooms).
- `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` — **verified working and active!**
  Live API call to Twilio returns HTTP 200 with status `"active"`.
  Credentials securely configured in local `.env` (gitignored).
  Next step: verify/provision a trial caller ID number on the Twilio console to set `TWILIO_FROM_NUMBER`.

## 4. Known deprecations found and fixed (don't reintroduce these)

Found by actually calling live APIs, not assumed:

- Gemini: `gemini-2.5-flash` and `gemini-2.0-flash` are deprecated for
  this account. Now using `gemini-flash-latest` (auto-tracking alias) and
  `gemini-3.1-flash-lite` (fallback) — both env-overridable
  (`GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`).
- Sarvam: `bulbul:v2` (the `livekit-plugins-sarvam` default) is
  deprecated server-side; must pass `model="bulbul:v3"` explicitly. Also,
  the plugin's default `speaker` is `None`, which the live API rejects —
  must pass a real speaker name. Both now env-overridable
  (`SARVAM_TTS_MODEL`, `SARVAM_TTS_VOICE`, default `priya`).
- A real bug (not a deprecation): `SARVAM_TTS_VOICE` existed in
  `.env.example` from early on but was never actually read by
  `entrypoint.py` — fixed.
- A real bug: `null_providers.py` used `message=` as a structlog kwarg,
  which collides with stdlib `logging`'s reserved `LogRecord.message`
  attribute and crashes under certain logging configs. Fixed (renamed to
  `call_message=`). If you add new logging calls anywhere, never use
  `message=`, `asctime=`, or other stdlib `LogRecord` attribute names as
  kwargs.
- A real bug: in-memory SQLite's default connection pooling is
  per-thread. A FastAPI app's startup lifespan (one thread) creating
  tables and a test's `TestClient` dispatch (a different thread) saw two
  separate empty databases. Fixed with `StaticPool` in
  `src/swasthya/db/session.py`, scoped specifically to `:memory:` URLs.

## 5. What's left to build, in priority order

Priority follows `docs/architecture.md` section 14's own ranking: **never
cut a safety loop (L1, L3, L4, L14, L20, L21) to save a feature.** Items
are grouped by that logic, not just listed top-to-bottom.

### 5a. Safety-critical — status

1. **Real Twilio emergency call provider (L14) — BUILT and tested.**
   `src/swasthya/gateway/providers/twilio_provider.py` with 13 unit tests.
   Live account verified active via REST API.
2. **Twilio status callback webhook (L15) — BUILT and tested.**
   `POST /webhooks/twilio/call-status` with HMAC-SHA1 signature verification
   (`X-Twilio-Signature`, S11) in `src/swasthya/api/routers/webhooks.py`,
   4 unit tests in `tests/test_api/test_webhooks.py`.
3. **Kill-switch control (L19/L34) — BUILT and tested.**
   DB-backed (`kill_switch_state` table, migration `0003`,
   `src/swasthya/db/kill_switch_store.py`), REST API (`/admin/kill-switch`),
   and wired directly into the voice agent orchestrator.
4. **On-call roster management (L21) — BUILT and tested.**
   `GET/POST/PATCH/DELETE /admin/roster`, `admin` role only
   (`src/swasthya/api/routers/admin.py`).
5. **Duplicate-call guard (L26) — BUILT and tested.**
   `find_open_task_for_identifier` on the workflow sink connects multiple
   calls from the same patient to their existing open task.

### 5b. Reliability / "should build" tier

6. **Wire the voice agent into `docker-compose.yml` — BUILT.**
   `voice-agent` service declared in `docker/docker-compose.yml` with proper
   service dependencies and environment configuration.
7. **Room lifecycle cleanup (L8) — BUILT and tested.**
   `on_session_end` callback wired from `entrypoint.py` to
   `MalayalamTriageAgent._apply_outcome`, gracefully disconnecting the
   LiveKit room after terminal lines are spoken.
8. **Evaluation harness against real recorded clips (L12).**
   Needs actual recorded audio clips (10-15 simulated clips per
   architecture.md section 10 — clear speech, slurred/slow, broken phrases,
   a stroke-pattern clip, an ambiguous clip, a prompt-injection clip)
   to build `scripts/run_evaluation.py`.
9. **CI has never actually run.** `.github/workflows/ci.yml` exists and
   mirrors commands that pass locally (157 tests passing).
7. **Evaluation harness against real recorded clips (L12).** `jiwer` is
   listed as a dependency but nothing uses it yet. This needs **actual
   audio recordings** (10-15 simulated clips per architecture.md section
   10 — clear speech, slurred/slow, broken phrases, a stroke-pattern
   clip, an ambiguous clip, a prompt-injection clip) that don't exist in
   this repo. Can't be built without that content — flag to whoever can
   record them, then build `scripts/run_evaluation.py` that feeds each
   clip through `interpret_clip` and reports word-error-rate (`jiwer`),
   read-back accept rate, and correct-tier rate.
8. **CI has never actually run.** `.github/workflows/ci.yml` exists and
   is believed correct (every step mirrors a command that passes
   locally) but no push has triggered it yet. First real CI run will
   likely surface something — budget time for it.
9. **Room lifecycle cleanup (L8).** No explicit "closing line spoken →
   terminate the LiveKit room" handling in `agent.py` today.

### 5c. Workflow states defined but unreachable (dead code today)

`AWAITING_HOSPITAL`, `AMBULANCE_REQUESTED`, `FOLLOW_UP` all exist in
`TaskState` (`src/swasthya/contracts.py`) and `ALLOWED_TRANSITIONS`, but
nothing in the app ever transitions a task into them. This is L23
(referral acceptance), L24 (ambulance dispatch), L25 (follow-up) — real
features, not bugs, just not started. Each needs a product decision
first (architecture.md says "Hospital response window set by the
programme" / "Follow-up interval set by the programme" — these aren't
mine to invent).

### 5d. Not started, lower urgency for a demo

Language check (L30), spam/rate-limiting at the call level distinct from
the gateway's action-level limiter (L31), vendor spend cap (L32),
retention purge job (L29), override review (L28), protocol sign-off CI
gate (L27). None of these are safety loops per the architecture doc's own
ranking — defer these if time is short.

### 5e. Process, not code

Clinical sign-off on `disease_triage_matrix.json`'s tier values and the
stroke symptom list (flagged inline in that file — someone qualified must
review it before this is anything but a demo). Backup/restore drill. A
real nurse-queue SLA policy for callback tasks.

## 6. How to approach what's left (for whoever picks this up)

- **Read the relevant section of `docs/architecture.md` first**, then the
  module(s) it touches, before writing code. Every module in this repo
  has a docstring explaining *why*, not just *what* — don't duplicate
  decisions that are already made and documented.
- **This codebase's established pattern for a new vendor integration**:
  define a `Protocol` (see `src/swasthya/gateway/providers/base.py`),
  build a real implementation and a safe stub/logging implementation side
  by side, default to the stub, make the real one opt-in via an env var.
  Follow this for Twilio, don't invent a new pattern.
- **Test against the real thing when you can.** Every credential in this
  project has been smoke-tested against its live API at least once before
  being declared "working" — don't just trust that code compiles. If a
  live test isn't possible (no credentials yet), say so explicitly rather
  than claiming verification you didn't do.
- **Never silently default a safety-relevant value.** `DEFAULT_EMERGENCY_CONTACT`
  being unset means an unenrolled caller's emergency call has nowhere to
  go — that's documented in `.env.example` now, not hidden.
- **Run `pytest tests/ -v` (126 passing) and `python simulate_e2e.py`
  (10/10 scenarios) before and after any change** — both are fast and
  catch regressions immediately.
- **Don't build tier 5d/5e items speculatively.** Several of them need a
  product or clinical decision that isn't this codebase's to make
  (retention periods, SLA windows, sign-off process). Building code around
  an invented policy value would be exactly the kind of "looks right but
  isn't grounded in anything real" work this project has deliberately
  avoided everywhere else.
