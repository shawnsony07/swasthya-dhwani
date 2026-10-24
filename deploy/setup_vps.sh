#!/bin/bash
# ==============================================================================
# Swasthya-Dhwani — VPS Provisioning Script (Ubuntu 22.04 / 24.04 LTS)
# Run as root or with sudo:
#   curl -sSL https://raw.githubusercontent.com/shawnsony07/swasthya-dhwani/main/deploy/setup_vps.sh | bash
# ==============================================================================

set -euo pipefail

echo "=================================================================="
echo " Starting Swasthya-Dhwani VPS Setup..."
echo "=================================================================="

# 1. Update OS packages
echo "[1/5] Updating system packages..."
apt-get update && apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg lsb-release ufw git jq

# 2. Configure UFW Firewall (SSH, HTTP, HTTPS)
echo "[2/5] Configuring firewall (ports 22, 80, 443)..."
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP / ACME Challenge'
ufw allow 443/tcp comment 'HTTPS'
# Enable UFW without prompting
ufw --force enable

# 3. Install Docker CE and Docker Compose plugin
echo "[3/5] Installing Docker Engine & Compose..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

# 4. Install Caddy (Automated SSL Reverse Proxy)
echo "[4/5] Installing Caddy Web Server..."
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLF 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLF 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy
systemctl enable --now caddy

# 5. Prepare Project Directory
echo "[5/5] Creating /opt/swasthya directory..."
mkdir -p /opt/swasthya

echo "=================================================================="
echo " VPS Provisioning Complete!"
echo " Next steps:"
echo " 1. cd /opt/swasthya && git clone <REPO_URL> ."
echo " 2. cp .env.example .env and fill in production secrets"
echo " 3. Copy deploy/Caddyfile to /etc/caddy/Caddyfile with your domains"
echo " 4. docker compose up -d --build"
echo "=================================================================="
