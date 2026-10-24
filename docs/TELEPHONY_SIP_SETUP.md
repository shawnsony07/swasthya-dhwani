# Swasthya-Dhwani Telephony & Patient Inbound Setup Guide
*Connecting Real Cellular & Landline Phone Numbers to the Live Malayalam Voice Triage Agent*

---

## 1. Dual-Channel Architecture

Swasthya-Dhwani supports two parallel patient intake channels that route directly into the identical clinical triage engine:

```
                                  ┌─────────────────────────────┐
 [ Patient Smartphone / Web ] ──> │ WebRTC Patient Dialer       │ ──┐
                                  │ (/patient - zero login)     │   │
                                  └─────────────────────────────┘   │
                                                                    ▼
                                                          ┌───────────────────────┐
                                                          │   LiveKit Cloud       │
                                                          │   Room Dispatch       │
                                                          └──────────┬────────────┘
                                                                     │
                                  ┌─────────────────────────────┐    │
 [ Patient Cellular / Landline ]─>│ Twilio Elastic SIP Trunk    │ ──┘
 (Direct phone call: +1 / +91)    │ LiveKit SIP Inbound Trunk   │
                                  └─────────────────────────────┘
                                                                     │
                                                                     ▼
                                                          ┌───────────────────────┐
                                                          │ Swasthya Voice Agent  │
                                                          │ · Sarvam STT (ml-IN)  │
                                                          │ · Triage Rules Engine │
                                                          │ · Sarvam TTS (priya)  │
                                                          │ · FHIR + 108 Dispatch │
                                                          └───────────────────────┘
```

In [`src/swasthya/voice/entrypoint.py`](file:///c:/dev/fluent_swasthya/src/swasthya/voice/entrypoint.py#L394-L401), the agent automatically tags telemetry and clinical records:
- `channel="sip"` if inbound from telephone network (`room.name` begins with `sip-`).
- `channel="web"` if inbound from the mobile patient dialer (`room.name` begins with `patient-`).

---

## 2. Option A: Mobile Talking Dashboard (WebRTC) — Ready Now

The mobile talking screen is built and live at **`/patient`**:
- **URL**: `http://localhost:3001/patient`
- **Features**:
  - Zero login required for patients (public route).
  - Phone-optimized container with native mobile ergonomics.
  - Interactive pulsing acoustic orb with live status (`കേൾക്കുന്നു` / `സംസാരിക്കുന്നു`).
  - Real-time audio frequency visualizer wave.
  - Live Malayalam speech transcript feed (`ml-IN`).
  - Kerala district selector (defaults to Ernakulam).
  - Emergency **108 Ambulance Direct Dial** button.
  - Clinician portal toggle button.

---

## 3. Option B: Connecting a Real Phone Number via LiveKit SIP & Twilio

To allow patients to dial an actual phone number from any mobile phone or landline without internet, follow these 3 steps:

### Step 1: LiveKit Cloud Inbound SIP Trunk Setup

1. Open your [LiveKit Cloud Console](https://cloud.livekit.io/) for project `swasthya-dhwani-manv1osr`.
2. Navigate to **SIP** in the sidebar.
3. Click **Create Inbound Trunk**:
   - **Name**: `swasthya-patient-inbound`
   - **Numbers**: Enter your Twilio phone number in E.164 format (e.g., `+17372508034` or Indian DID `+91...`).
4. Click **Create Dispatch Rule**:
   - **Rule Type**: Individual / Direct Dispatch.
   - **Room Prefix**: `sip-` (or room name template: `sip-call-{call_id}`).
   - **Participant Identity**: `patient-{caller_number}`.
   - **Metadata**: `{"channel": "sip", "district": "Kerala"}`.
5. LiveKit Cloud will generate your unique SIP endpoint:
   - Example: `<project-subdomain>.sip.livekit.cloud`

Alternatively, configure via LiveKit CLI:
```bash
lk sip inbound-trunk create \
  --name "swasthya-patient-inbound" \
  --numbers "+17372508034"

lk sip dispatch-rule create \
  --name "swasthya-triage-dispatch" \
  --trunk-ids "<TRUNK_ID>" \
  --rule-type individual \
  --room-prefix "sip-"
```

---

### Step 2: Configure Twilio Elastic SIP Trunking

1. Log in to your [Twilio Console](https://console.twilio.com/).
2. Navigate to **Elastic SIP Trunking** -> **Manage** -> **Trunks**.
3. Click **Create new SIP Trunk**:
   - **Friendly Name**: `LiveKit Swasthya SIP Trunk`
4. Under **Origination**:
   - Add Origination URI:
     - **SIP URI**: `sip:<project-subdomain>.sip.livekit.cloud`
     - **Priority**: `10`
     - **Weight**: `10`
     - **Status**: Enabled
5. Under **Phone Numbers**:
   - Assign your Twilio number (e.g., `+17372508034`) to this SIP Trunk.

---

### Step 3: Run the Swasthya Voice Agent Worker

Start the agent worker (or run it via `docker compose up swasthya-voice`):
```bash
python -m swasthya.voice.entrypoint dev
```

### End-to-End Verification Flow:
1. Patient dials the phone number from any cellular network.
2. Twilio receives the cellular call and bridges SIP audio to `sip.livekit.cloud`.
3. LiveKit Cloud creates a room prefixed with `sip-...` and dispatches the job.
4. `MalayalamTriageAgent` answers the call.
5. The patient hears:
   > *"നമസ്കാരം, സ്വാസ്ഥ്യ ധ്വനിയിലേക്ക് സ്വാഗതം. നിങ്ങളുടെ രോഗലക്ഷണങ്ങൾ എന്തൊക്കെയാണ്?"*
   *(Spoken by Sarvam `priya` Malayalam voice directly over the cellular network).*
6. The patient speaks their symptoms in Malayalam; Sarvam STT transcribes the speech, the Kerala clinical rule engine evaluates emergency red flags, and the task appears live on the Clinician Operations Queue at `http://localhost:3001/dashboard`.
