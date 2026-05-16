#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "[launch_sitl] Starting 3 PX4 SITL instances via docker compose..."
docker compose -f "$REPO_ROOT/docker-compose.yml" up -d

echo "[launch_sitl] Waiting 15s for SITL instances to initialise..."
sleep 15
echo "[launch_sitl] SITL ready. MAVLink UDP ports: 14540, 14541, 14542"
