# Swasthya-Dhwani x FluentPath — triage spine

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

114 tests, all passing as of this build; `simulate_e2e.py` passes 10/10 scenarios.

## Not done yet (see `docs/architecture.md` section 15 for the full tiering)

- Dashboard (Next.js UI)
- Live Twilio / SmartThings vendor credentials (the gateway dispatch logic
  is real and wired to the emergency path; only the actual vendor API call
  is a logging stand-in)
- Doctor-approval HTTP API (FastAPI A2A handler, SSE alert stream) — right
  now only `weft_workflow` functions exist, called directly by tests/the
  replay harness, not through an endpoint a dashboard could hit
- Docker Compose stack, Keycloak wiring, CI secret rotation runbook execution
- A real HAPI FHIR server to run against (the adapter is tested against
  mocked HTTP; `simulate_e2e.py` uses a recording fake, not a live server)
- Clinical sign-off on the stroke symptom list and tier values in
  `src/swasthya/protocol/disease_triage_matrix.json` — flagged inline, not
  yet reviewed by a clinician

## Secrets

No `.env` exists in this repo (it started empty). Copy `.env.example` to
`.env` for local work and never commit the real file.
