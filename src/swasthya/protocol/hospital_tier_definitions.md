# Hospital Tier Definitions

Status: **draft, not clinically signed off.** These tier meanings and the
hospital-capability mappings in `disease_triage_matrix.json` were written by
engineering from publicly described Kerala-protocol-style triage categories,
not by a clinician. A qualified clinical owner must review this file and the
matrix before either is used on real (non-synthetic) patients. See
`docs/architecture.md` section 5 ("Open item for the clinical owner") and
loop L27 (protocol change sign-off blocks merge without a recorded
reviewer).

The rule engine (`kerala_protocol_mcp.py`) only ever assigns one of these
four tiers. No LLM output can set or change a tier — see
`docs/architecture.md` section 7.

## Tier A — Routine, self-care / advice

No referral is clinically indicated from the symptoms and warning signs
confirmed so far. The caller is given self-care guidance and a general
PHC-visit recommendation if symptoms persist or worsen. Not currently used
by any condition in the matrix, but reserved for conditions where the
required symptom pattern is present without any supporting or warning
signal.

## Tier B — Non-urgent PHC / outpatient referral

The symptom pattern warrants a visit to a Primary Health Centre (PHC) or
outpatient clinic, but there is no warning sign indicating a time-critical
course. Referral window: within the next few days, at the patient's or
caregiver's convenience.

## Tier C2 — Urgent referral (hours, not minutes)

A warning sign is present that raises clinical concern but does not, by
itself, indicate an immediately life-threatening course. The patient should
be seen at a facility capable of further workup (CHC/FRU level or
equivalent) within hours. `apply_acuity_floor` can raise a case into this
tier purely from low interpreter confidence, even if the matched condition
alone would only justify tier B — see `kerala_protocol_mcp.py`.

## Tier C1 — Emergency referral (immediate)

The highest acuity tier. Indicates a time-critical condition where delay
measurably worsens outcome (e.g. stroke, cardiac warning signs, uncontrolled
bleeding, airway compromise). The case is routed for immediate hospital
referral or emergency transport; `weft_workflow.py`'s approval timeout for
C1 cases is shortened (architecture.md T4).

### Suspected Stroke is a mandatory C1 trigger

Any single FAST sign — facial droop, arm weakness, or speech difficulty —
assigns tier C1 unconditionally (`disease_triage_matrix.json`,
`suspected_stroke` condition). This is deliberate and distinct from every
other condition in the matrix, where a base symptom alone only reaches B or
C2 and an additional warning sign is needed to reach C1: stroke has no
"routine" tier because time-to-treatment dominates every other
consideration. The symptom list and the "any single sign is enough" rule
are both DRAFT and need clinical sign-off before real use.

### Acuity floor interaction (T2)

`apply_acuity_floor` in `kerala_protocol_mcp.py` can force a case to C1
independently of whichever condition matched, when the FluentPath
interpreter reports speech-impairment signals with a new-or-unknown onset.
A caregiver-confirmed **chronic** baseline (e.g. ALS, Parkinson's dysarthria)
is explicitly exempted from this floor — see the docstring on that function
for why. Low interpreter confidence raises whatever tier was assigned by one
step (A -> B -> C2 -> C1, never skipping past C1), and never lowers a tier.
