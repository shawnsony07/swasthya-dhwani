#!/bin/bash
# ==============================================================================
# Swasthya-Dhwani — Zero-Downtime / Automated Update Script
# Run from /opt/swasthya:
#   ./deploy/update.sh
# ==============================================================================

set -euo pipefail

echo "=================================================================="
echo " Pulling latest code and updating containers..."
echo "=================================================================="

# 1. Fetch latest commits
git pull origin main

# 2. Rebuild and restart services gracefully
docker compose -f docker/docker-compose.yml up -d --build

# 3. Clean up dangling images to save disk space
docker image prune -f

echo "=================================================================="
echo " Update completed successfully!"
echo " Services status:"
docker compose -f docker/docker-compose.yml ps
echo "=================================================================="
