# Swasthya-Dhwani x FluentPath — triage spine

<p align="center">
  <img src="docs/logo.png" alt="Swasthya-Dhwani Logo" width="140" style="border-radius: 28px;" />
</p>

Malayalam voice triage service: an LLM interprets speech, but a deterministic
rule engine over a Kerala protocol graph decides clinical acuity. Full product
vision and the delivery plan are in [`docs/architecture.md`](docs/architecture.md).

## What's built so far

This is the **core triage spine** plus a first pass at the **LiveKit voice
agent** — the part of the architecture that must be deterministic, auditable,
and correct before a dashboard UI or live Twilio/SmartThings calls are layered
on top.

| Module | Path | Covers |
| --- | --- | --- |
| Shared contracts | `src/swasthya/contracts.py` | `TriageData` v2, task states, action/audit schemas — every other module imports from here |
| Rule engine | `src/swasthya/protocol/` | Stroke condition, `NO_MATCH` safety fix (T3), acuity floor (T2), determinism (T5) |
| FHIR adapter | `src/swasthya/fhir/` | Observation/Provenance/ServiceRequest/AuditEvent writes to HAPI, identifier hashing, retry/circuit behavior |
| Speech interpreter | `src/swasthya/interpreter/` | Gemini-backed interpretation, confidence policy, prompt-injection resistance |
| Workflow | `src/swasthya/db/`, `src/swasthya/workflow/` | SQLAlchemy models, Alembic migration, state machine, timeout-fails-toward-care fix (T4) |
| Action gateway | `src/swasthya/gateway/` | Allow-list/rate-limit/kill-switch policy; swappable voice/call/device providers |
| Voice agent | `src/swasthya/voice/` | LiveKit `Agent` with audio-tee `stt_node`, Sarvam STT/TTS + Gemini-with-fallback `AgentSession`, and a pure read-back/confirmation-loop state machine (`conversation.py`) feeding the rule engine |

**LiveKit version note:** `docs/architecture.md` says to pin
`livekit-agents==1.5.4`; this environment already had `1.6.1` installed
transitively, so the voice module was built and its API verified by
introspection against **1.6.1**, and `pyproject.toml` pins that instead.
`AgentSession` bundles Silero VAD by default in 1.6+, so there's no separate
VAD dependency.

**Voice agent design:** `agent.py` is deliberately thin — it tees each turn's
audio into a buffer (`audio_tee.py`) and hands transcript+clip to the speech
interpreter, but every decision about what to say next lives in the
LiveKit-free, fully unit-tested `conversation.py`. Scripted safety lines
(read-backs, re-asks, the emergency window, handoff notices) are spoken
verbatim via `session.say()` and suppress the LLM's own reply for that turn
(`StopResponse`) — Gemini never paraphrases a safety-critical line. Slot
filling is a fixed order (identifier → symptoms → warning signs → duration)
for this pass, not full NLU extraction from free dialogue — flagged as a
known simplification, not hidden.

**End-to-end wiring:** `entrypoint.py`'s `_WorkflowSinkAdapter` now opens a
real SQLAlchemy `Session` per call (`src/swasthya/db/session.py`) and drives
the actual `weft_workflow` state machine; `_FhirSinkAdapter` calls the real
`swasthya.fhir.adapter` functions. A FHIR outage is caught at the
`ConversationOrchestrator` boundary and degrades the call
(`fhir_write_failed=True` on the outcome) rather than blocking it — see
`docs/architecture.md` section 8. `simulate_e2e.py` (repo root) proves the
real rule engine + real workflow + real DB agree, end to end, without needing
live LiveKit/Gemini/Sarvam/HAPI credentials — run it with `python
simulate_e2e.py`. It's honest about what it does *not* cover (printed at the
end of its own output): the live interpreter, a live LiveKit room, a real
HAPI server, and real Twilio/SmartThings vendor calls.

**Emergency path wired end to end:** F4's 5-second confirmation window now
runs for real — `agent.py` starts an asyncio timer when emergency terms are
heard; the next turn (or the timer firing first) resolves it via
`conversation.py`'s `handle_emergency_confirmation`, which dispatches
through the real `ActionGateway` (`entrypoint.py`'s
`_EmergencyDispatcherAdapter`): tries the patient's enrolled contacts in
priority order (`AllowList.ordered_targets`, new), falls back to
`DEFAULT_EMERGENCY_CONTACT` for an unenrolled caller (loop L22), and goes
through the gateway's full allow-list/rate-limit/kill-switch/audit policy.
Only the vendor call itself is simulated (`LoggingEmergencyCallProvider` —
no Twilio credentials exist yet).

**Voice cloning note:** Sarvam (the chosen Malayalam TTS vendor) has no voice
cloning — only fixed voices. `gateway/providers/base.py` defines a
`VoiceCloneProvider` protocol so a real cloning vendor can be plugged in
later; the shipped default (`NeutralVoiceProvider`) always falls back to the
neutral Sarvam voice, which is also the documented fallback behavior in
`docs/architecture.md` section 4.

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
ruff check src tests
mypy src --ignore-missing-imports
python -m swasthya.protocol.ingest_protocol --check   # fails if graph.json is stale
python simulate_e2e.py                                 # end-to-end replay harness
```

126 tests, all passing as of this build; `simulate_e2e.py` passes 10/10 scenarios.

## Doctor-approval API (`src/swasthya/api/`)

A FastAPI service implementing `docs/api_contract.md`: `GET /tasks`,
`GET /tasks/{id}`, `POST /tasks/{id}/approve` (`doctor` role),
`POST /tasks/{id}/reject` (`doctor` or `nurse`), `GET /alerts/stream` (SSE,
poll-and-diff every 2s), `GET /healthz`. Auth is real Keycloak JWT
validation against the realm's JWKS endpoint (`AUTH_DISABLED=true` bypasses
it for local work — never outside that). Also runs the first scheduled
caller of `weft_workflow.check_timeouts` anywhere in the system (every 30s).

Run locally: `uvicorn swasthya.api.app:app --reload` (needs `DATABASE_URL`,
`KEYCLOAK_BASE_URL` in the environment or `.env`).

## Docker stack (`docker/`)

`docker compose -f docker/docker-compose.yml up --build` — postgres, HAPI
FHIR, Keycloak (auto-imports `docker/keycloak/swasthya-realm.json`: users
`doctor1`/`doctor1pass`, `nurse1`/`nurse1pass`, `admin1`/`admin1pass`),
the API, and the dashboard. Copy `.env.example` to `docker/.env` (Compose
reads its env file relative to the compose file's own directory, not the
invocation directory — a common gotcha) and fill in `GEMINI_API_KEY`/
`SARVAM_API_KEY`.

Verified for real against this machine's Docker (not just `compose config`):
postgres, HAPI, and Keycloak all boot and respond; a live password-grant
token for `doctor1` was fetched from Keycloak, decoded, and run through the
API's actual `auth.py` JWT-validation code, then through a running
`uvicorn` instance (`GET /tasks` → 401 with no token, 200 with that token).
Two real bugs were caught and fixed in the process, not just assumed away:

- The `hapiproject/hapi:v7.2.0` image has no shell at all (confirmed via
  `docker exec` — `sh`, `wget`, `curl`, `cat`, `which` all fail with
  "executable file not found in $PATH"), so an exec-based Docker
  healthcheck for it can never succeed regardless of whether HAPI is
  actually up. Removed; the `api` service now depends on `service_started`
  for hapi instead of `service_healthy`, backed by the FHIR adapter's own
  existing timeout/retry handling.
- Keycloak 26's User Profile feature requires `firstName`/`lastName` on
  every user by default; without them, every login silently fails with
  `invalid_grant: "Account is not fully set up"` no matter how correct the
  password is. Added `firstName`/`lastName` to the three seeded demo users
  in the realm file.

## Not done yet (see `docs/architecture.md` section 15 for the full tiering)

- Dashboard (Next.js UI) — in progress
- Live Twilio / SmartThings vendor credentials (the gateway dispatch logic
  is real and wired to the emergency path; only the actual vendor API call
  is a logging stand-in)
- CI secret rotation runbook execution
- Clinical sign-off on the stroke symptom list and tier values in
  `src/swasthya/protocol/disease_triage_matrix.json` — flagged inline, not
  yet reviewed by a clinician

## Secrets

No `.env` exists in this repo (it started empty). Copy `.env.example` to
`.env` for local work and never commit the real file.
