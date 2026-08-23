#!/usr/bin/env bash
# Remove the welcome gate; the app router takes back the full hostname instantly.
set -euo pipefail
docker compose -f /opt/hortusfox-gate/deploy/docker-compose.yml down || true
rm -f /opt/traefik/dynamic/hortusfox-gate.yml
sleep 1
code=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 8 "https://plants.silverwulf.org/auth")
echo "plants.silverwulf.org/auth -> $code (302 expected — app fully in charge)"
echo "gate removed."
