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

Each of these has unit tests (126 passing as of this writing — run
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
  "try contacts in priority order." **The policy is real; the emergency
  call provider underneath it is a logging stand-in, not a real Twilio
  call — this is the single biggest remaining gap, see section 6.**
- **`src/swasthya/voice/`** — the LiveKit agent (`agent.py`), the pure
  confirmation-loop state machine (`conversation.py` — read-back,
  re-ask-then-handoff, emergency window), and `entrypoint.py` (wires
  Sarvam/Gemini/the DB/FHIR/the gateway together). Verified: a real
  `interpret_clip()` call against live Gemini correctly flagged "chest
  pain" in Malayalam as an emergency term; a real Sarvam TTS→STT
  round-trip produced and transcribed real Malayalam audio.
- **`src/swasthya/api/`** — the doctor-approval REST API. Every endpoint
  in `docs/api_contract.md`. Verified: a real password-grant JWT from a
  live Keycloak was validated end-to-end through the actual `auth.py`
  code, then through a running `uvicorn` instance (401 without it, 200
  with it).
- **`dashboard/`** — the Next.js app. Verified via a scripted real OAuth
  round-trip against live Keycloak (logged in as both `doctor1` and
  `nurse1`, confirmed role-gated UI).
- **`docker/docker-compose.yml`** — Postgres, HAPI, Keycloak all
  confirmed booting and responding on this machine. Two real bugs found
  and fixed in the process: HAPI's image has no shell at all (its
  Docker healthcheck was removed, not patched around), and Keycloak 26
  requires `firstName`/`lastName` on seeded users or every login fails
  with a misleading "account not fully set up" error.
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
- `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` — **the pair I currently have
  returns 401 "account ... is not active"** even for basic account
  lookup. This looks like the Auth Token rotated when the account was
  activated. **Needs a fresh SID + Auth Token from the Twilio console,
  plus a `TWILIO_FROM_NUMBER`** (the trial account's assigned number) —
  nothing can be verified live until these arrive.

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

1. **Real Twilio emergency call provider (L14) — BUILT, tested, blocked
   on account activation.** `src/swasthya/gateway/providers/twilio_provider.py`
   — `TwilioEmergencyCallProvider`, same `EmergencyCallProvider` Protocol
   as the logging stand-in. Creates the call via plain `httpx` (not the
   Twilio SDK — matches this codebase's FHIR-adapter pattern), then polls
   `GET /Calls/{Sid}.json` until a terminal status or
   `TWILIO_RING_TIMEOUT_SECONDS` elapses (architecture.md L15's own
   documented fallback, used as the primary mechanism since no public
   webhook URL exists yet — see item 2). 13 tests, all against mocked
   HTTP (`tests/test_twilio_provider.py`). Wired into `entrypoint.py`
   behind `EMERGENCY_CALL_PROVIDER=twilio` (default `logging` — a
   misconfigured deployment never silently tries real calls). Ran the
   **real end-to-end pipeline** against the user's live credentials: full
   gateway policy (allow-list, rate limiter, audit trail) executed
   correctly, the Twilio API call was attempted, and it resolved cleanly
   to `EMERGENCY_CALL_FAILED` with a dashboard alert — no crash, no
   token leaked in logs. The one remaining blocker is **not code**: the
   Twilio account itself rejects all API calls with `"account ... is not
   active"` (error 20003) even though the console shows it as active and
   the credentials match exactly (confirmed via screenshot) — this needs
   resolving on Twilio's side (check for a pending verification step in
   their console/email) before a real call can go through.
2. **Twilio status callback webhook (L15) — not started.** The poller in
   item 1 is a real, working mechanism on its own; a webhook endpoint
   (`POST /webhooks/twilio/call-status`, signature-verified per Twilio's
   `X-Twilio-Signature` header, S11) would let a real deployment get the
   result faster and without polling, but isn't required for the gateway
   to function correctly today.
3. **Kill-switch control (L19/L34) — BUILT and tested.** Was in-memory
   and process-local (meaningless across the API/voice-agent process
   boundary) — now DB-backed (`kill_switch_state` table, migration
   `0003`, `src/swasthya/db/kill_switch_store.py`'s `DbKillSwitchStore`),
   via the same store-injection pattern `AllowList`/`RateLimiter` already
   use. `GET/POST /admin/kill-switch(/engage|/disable)`, `admin` role
   only. 9 tests including one that proves state survives across two
   separate `KillSwitch` instances reading the same DB (simulating the
   cross-process case directly, not just trusting it).
4. **On-call roster management (L21) — BUILT and tested.**
   `GET/POST/PATCH/DELETE /admin/roster`, `admin` role only
   (`src/swasthya/api/routers/admin.py`).
5. **Duplicate-call guard (L26) — not started.** No code currently checks
   "is there already an open case for this identifier?" before starting
   a new one. Belongs in `src/swasthya/voice/conversation.py` or
   `agent.py` — look up
   open tasks by `patient_identifier_hash` before calling `submit_task`.

### 5b. Reliability / "should build" tier

6. **Wire the voice agent into `docker-compose.yml`.** Real LiveKit
   credentials exist now (section 3) — there's no `voice-agent` service
   in the compose file yet. Entrypoint: `python -m swasthya.voice.entrypoint
   start`, needs `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET`
   (already in `.env`) plus everything the API service needs
   (`DATABASE_URL`, `HAPI_FHIR_BASE_URL`, etc.).
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
