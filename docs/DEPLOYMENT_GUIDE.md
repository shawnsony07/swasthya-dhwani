# Swasthya-Dhwani x FluentPath — Production Deployment Guide

This guide details how to dockerize, configure, and deploy the entire Swasthya-Dhwani healthcare voice triage system to production.

---

## 1. System Architecture & Container Topology

Swasthya-Dhwani is a distributed, privacy-first healthcare AI system comprising **6 core containers** orchestrated via Docker Compose:

```
                          [ Internet / Patients & Clinicians ]
                                         │
                    ┌────────────────────┴────────────────────┐
                    │  Reverse Proxy (Caddy / Nginx / Cloud) │
                    │       Automated Let's Encrypt SSL       │
                    └────────────────────┬────────────────────┘
                                         │
       ┌──────────────────┬──────────────┴─────────────┬──────────────────┐
       │ :3000            │ :8000                      │ :8081            │
┌──────▼───────┐   ┌──────▼───────┐             ┌──────▼───────┐   ┌──────▼───────┐
│  dashboard   │   │     api      │             │   keycloak   │   │     hapi     │
│  (Next.js)   ├───►  (FastAPI)   │             │ (Auth Server)│   │  (FHIR R4)   │
└──────────────┘   └──────┬───────┘             └──────┬───────┘   └──────┬───────┘
                          │                            │                  │
                          └──────────────┬─────────────┴──────────────────┘
                                         │
                                  ┌──────▼───────┐
                                  │   postgres   │
                                  │ (PostgreSQL) │
                                  └──────▲───────┘
                                         │
                                  ┌──────┴───────┐
                                  │ voice-agent  │
                                  │ (LiveKit Wk) │
                                  └──────▲───────┘
                                         │
                     ┌───────────────────┴───────────────────┐
                     │          Managed Cloud APIs           │
                     │  - LiveKit Cloud (WebRTC Signaling)   │
                     │  - Google Gemini (Speech Reasoner)    │
                     │  - Sarvam AI (Malayalam STT / TTS)    │
                     │  - Twilio Voice (Emergency PSTN Calls)│
                     └───────────────────────────────────────┘
```

### Container Services Summary

| Service | Technology | Port (Internal/Host) | Purpose |
| --- | --- | --- | --- |
| **`dashboard`** | Next.js 16 / React 19 / Tailwind 4 | `3000:3000` | Clinician referral triage queue & Patient voice WebRTC phone interface |
| **`api`** | FastAPI / Python 3.11+ / Uvicorn | `8000:8000` | Doctor-approval REST API, SSE live alerts, Keycloak JWT auth, Twilio webhooks |
| **`voice-agent`** | LiveKit Agents 1.6+ Worker / Python 3.11+ | None (Outbound WebRTC) | Continuous worker connecting to LiveKit Cloud, processing Malayalam dialogue |
| **`postgres`** | PostgreSQL 16 Alpine | `5432:5432` | Relational store for triage tasks, audit events, roster, kill-switch |
| **`keycloak`** | Keycloak 26.0 (Quay) | `8080:8081` | OIDC Identity Provider with `swasthya` realm, JWT roles (`doctor`, `nurse`, `admin`) |
| **`hapi`** | HAPI FHIR R4B v7.2.0 | `8080:8080` | Standards-compliant clinical FHIR repository (Observations, ServiceRequests) |

---

## 2. Where to Deploy: Recommended Hosting Options

### Option A: Single Cloud VPS / VM (Recommended for Most Deployments)
- **Providers:** Hetzner Cloud (CPX31 / CCX13), DigitalOcean Droplet (4-8 GB RAM), AWS EC2 (t4g.xlarge / c6i.large), Google Cloud Compute Engine (e2-standard-2 / e2-standard-4), Azure VM.
- **Estimated Cost:** $15 – $40 / month.
- **Why this is best:**
  1. Low-latency internal Docker bridge network (`swasthya_default`) connects Postgres, Keycloak, HAPI FHIR, and the API with zero egress fees and sub-millisecond query times.
  2. The Voice Agent requires a long-running, continuous Python daemon (LiveKit worker) which can be expensive or constrained on pure serverless platforms.
  3. Single-command deployment (`docker compose -f docker/docker-compose.yml up -d --build`).

### Option B: Hybrid Cloud (PaaS + Managed Databases)
- **Frontend (`dashboard`):** Vercel or Cloudflare Pages (connects to your public API).
- **Backend (`api`):** Google Cloud Run or AWS ECS Fargate.
- **Voice Agent (`voice-agent`):** Google Cloud Run (min-instances=1, CPU always allocated) or AWS EC2 / Render Background Worker.
- **Database:** Supabase Postgres or AWS RDS PostgreSQL.
- **Why use this:** High auto-scaling for variable web traffic, but requires managing multiple vendor dashboards.

---

## 3. Production Prerequisites & Environment Setup

### Required External API Accounts
1. **Google AI Studio / Gemini API:** `GEMINI_API_KEY` for clinical audio reasoning.
2. **Sarvam AI:** `SARVAM_API_KEY` for Malayalam Speech-to-Text and TTS Bulbul v3.
3. **LiveKit Cloud:** `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` for low-latency WebRTC audio streaming.
4. **Twilio (Optional but recommended for emergency dispatch):** `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`.

### Domain Name & DNS Records
Point your domain (e.g. `swasthya.yourhospital.org`) or subdomains to your server's Public IP:
- `swasthya.yourhospital.org` $\rightarrow$ Next.js Dashboard & Patient Portal
- `api.swasthya.yourhospital.org` $\rightarrow$ FastAPI Backend
- `auth.swasthya.yourhospital.org` $\rightarrow$ Keycloak Login & JWKS

---

## 4. Step-by-Step Deployment on Ubuntu / Debian VPS

### Step 1: Install Docker & Docker Compose
SSH into your server and run:

```bash
# Update package lists
sudo apt update && sudo apt upgrade -y

# Install Docker dependencies
sudo apt install -y ca-certificates curl gnupg lsb-release

# Add Docker's official GPG key & repository
sudo mkdir -m 0755 -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine and Compose plugin
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Enable and start Docker service
sudo systemctl enable --now docker
```

---

### Step 2: Clone Repository & Configure Environment

```bash
git clone https://github.com/shawnsony07/swasthya-dhwani.git /opt/swasthya
cd /opt/swasthya

# Copy environment template
cp .env.example .env
```

Edit `/opt/swasthya/.env` using `nano .env`:

```env
# ==============================================================================
# SWASTHYA-DHWANI PRODUCTION ENVIRONMENT
# ==============================================================================

# Database Credentials
POSTGRES_USER=swasthya
POSTGRES_PASSWORD=GENERATE_STRONG_RANDOM_PASSWORD_HERE
POSTGRES_DB=swasthya
DATABASE_URL=postgresql+psycopg://swasthya:GENERATE_STRONG_RANDOM_PASSWORD_HERE@postgres:5432/swasthya

# Security & Secrets
NEXTAUTH_SECRET=GENERATE_32_CHAR_RANDOM_STRING_HERE
NEXTAUTH_URL=https://swasthya.yourhospital.org
NEXT_PUBLIC_API_BASE_URL=https://api.swasthya.yourhospital.org
CORS_ORIGINS=https://swasthya.yourhospital.org
AUTH_DISABLED=false

# Keycloak Configuration
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=GENERATE_STRONG_KEYCLOAK_ADMIN_PASSWORD
KEYCLOAK_BASE_URL=http://keycloak:8080

# External AI & Voice Providers
GEMINI_API_KEY=your_gemini_api_key_here
GOOGLE_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_FALLBACK_MODEL=gemini-flash-lite-latest

SARVAM_API_KEY=your_sarvam_api_key_here
SARVAM_TTS_MODEL=bulbul:v3
SARVAM_TTS_VOICE=priya

# LiveKit WebRTC Cloud
LIVEKIT_URL=wss://your-subdomain.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret

# Twilio Emergency Telephony
EMERGENCY_CALL_PROVIDER=twilio
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_FROM_NUMBER=+1XXXXXXXXXX
DEFAULT_EMERGENCY_CONTACT=+91XXXXXXXXXX
```

> [!TIP]
> Generate secure secrets easily on Linux with:
> `openssl rand -base64 32`

---

### Step 3: Build and Launch the Stack

Run the stack in the background with automatic build:

```bash
cd /opt/swasthya
docker compose -f docker/docker-compose.yml up -d --build
```

Check the status of all 6 containers:

```bash
docker compose -f docker/docker-compose.yml ps
```

All services (`postgres`, `hapi`, `keycloak`, `api`, `voice-agent`, `dashboard`) should show status `Up` or `healthy`.

To inspect logs:

```bash
# Follow all logs
docker compose -f docker/docker-compose.yml logs -f

# Follow voice agent worker logs
docker compose -f docker/docker-compose.yml logs -f voice-agent

# Follow API logs
docker compose -f docker/docker-compose.yml logs -f api
```

---

### Step 4: Reverse Proxy & Automatic SSL with Caddy (Recommended)

Caddy automatically provisions and renews SSL certificates from Let's Encrypt with zero configuration.

Install Caddy:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLF 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLF 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

Create `/etc/caddy/Caddyfile`:

```caddy
# Frontend Dashboard & Patient Voice Client
swasthya.yourhospital.org {
    reverse_proxy localhost:3000
}

# FastAPI Backend & SSE Alert Stream
api.swasthya.yourhospital.org {
    reverse_proxy localhost:8000
}

# Keycloak Auth Server
auth.swasthya.yourhospital.org {
    reverse_proxy localhost:8081
}
```

Reload Caddy to activate HTTPS immediately:

```bash
sudo systemctl reload caddy
```

Now access `https://swasthya.yourhospital.org` in any browser — it will load over secure HTTPS!

---

## 5. Production Health Checks & Verification

Verify each layer of the running stack:

1. **API Health Endpoint:**
   ```bash
   curl -i http://localhost:8000/healthz
   # Expect: HTTP/200 OK {"status": "ok"}
   ```

2. **HAPI FHIR Metadata:**
   ```bash
   curl -i http://localhost:8080/fhir/metadata
   # Expect: HTTP/200 OK with FHIR CapabilityStatement JSON
   ```

3. **Keycloak OIDC Configuration:**
   ```bash
   curl -i http://localhost:8081/realms/swasthya/.well-known/openid-configuration
   # Expect: HTTP/200 OK with OIDC discovery document
   ```

4. **LiveKit Room Worker Connection:**
   Check the `voice-agent` logs:
   ```bash
   docker compose -f docker/docker-compose.yml logs voice-agent
   # Expect: "registered worker with LiveKit Cloud" and listening for incoming room jobs.
   ```

---

## 6. Telephony (Twilio & SIP) Inbound Setup

### A. Twilio Status Callback Webhook
In your Twilio Console (Voice Settings):
- **Status Callback URL:** `https://api.swasthya.yourhospital.org/webhooks/twilio/call-status`
- **HTTP Method:** `POST`

### B. Inbound SIP Dispatch Rule (LiveKit)
For patients calling from mobile or landline phones directly:
Refer to [`docs/TELEPHONY_SIP_SETUP.md`](TELEPHONY_SIP_SETUP.md) to set up an Inbound SIP Trunk in LiveKit Cloud routing dialed numbers directly into `MalayalamTriageAgent`.

---

## 7. Automated Backups & System Maintenance

### Daily PostgreSQL Backup Cronjob
Create `/etc/cron.daily/swasthya-backup`:

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/swasthya"
mkdir -p "$BACKUP_DIR"
docker exec swasthya-postgres-1 pg_dump -U swasthya swasthya | gzip > "$BACKUP_DIR/db-$(date +\%Y\%m\%d).sql.gz"
find "$BACKUP_DIR" -type f -mtime +14 -delete
```

Make it executable:
```bash
sudo chmod +x /etc/cron.daily/swasthya-backup
```

---

## 8. Summary of Commands Cheat Sheet

| Action | Command |
| --- | --- |
| **Start Stack** | `docker compose -f docker/docker-compose.yml up -d` |
| **Rebuild & Start** | `docker compose -f docker/docker-compose.yml up -d --build` |
| **Stop Stack** | `docker compose -f docker/docker-compose.yml stop` |
| **Tear Down** | `docker compose -f docker/docker-compose.yml down` |
| **View All Logs** | `docker compose -f docker/docker-compose.yml logs -f` |
| **Restart Voice Agent** | `docker compose -f docker/docker-compose.yml restart voice-agent` |
| **Run DB Migrations Manually** | `docker compose -f docker/docker-compose.yml exec api alembic upgrade head` |
