# Swasthya-Dhwani x FluentPath — triage spine

Malayalam voice triage service: an LLM interprets speech, but a deterministic
rule engine over a Kerala protocol graph decides clinical acuity. Full product
vision and the delivery plan are in [`docs/architecture.md`](docs/architecture.md).

## What's built so far

This is the **core triage spine** — the part of the architecture that must be
deterministic, auditable, and correct before anything is layered on top (voice
agent, dashboard UI, live Twilio/SmartThings calls). No LiveKit audio pipeline
or dashboard UI exists yet; this is library + API-shaped code with full test
coverage.

| Module | Path | Covers |
| --- | --- | --- |
| Shared contracts | `src/swasthya/contracts.py` | `TriageData` v2, task states, action/audit schemas — every other module imports from here |
| Rule engine | `src/swasthya/protocol/` | Stroke condition, `NO_MATCH` safety fix (T3), acuity floor (T2), determinism (T5) |
| FHIR adapter | `src/swasthya/fhir/` | Observation/Provenance/ServiceRequest/AuditEvent writes to HAPI, identifier hashing, retry/circuit behavior |
| Speech interpreter | `src/swasthya/interpreter/` | Gemini-backed interpretation, confidence policy, prompt-injection resistance |
| Workflow | `src/swasthya/db/`, `src/swasthya/workflow/` | SQLAlchemy models, Alembic migration, state machine, timeout-fails-toward-care fix (T4) |
| Action gateway | `src/swasthya/gateway/` | Allow-list/rate-limit/kill-switch policy; swappable voice/call/device providers |

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
```

72 tests, all passing as of this build.

## Not done yet (see `docs/architecture.md` section 15 for the full tiering)

- LiveKit voice agent (audio tee, read-back loop wired to real STT/TTS)
- Dashboard (Next.js UI)
- Live Twilio / SmartThings integrations (gateway providers are stubs today)
- Docker Compose stack, Keycloak wiring, CI secret rotation runbook execution
- Clinical sign-off on the stroke symptom list and tier values in
  `src/swasthya/protocol/disease_triage_matrix.json` — flagged inline, not
  yet reviewed by a clinician

## Secrets

No `.env` exists in this repo (it started empty). Copy `.env.example` to
`.env` for local work and never commit the real file.
