#!/usr/bin/env bash
# E2E for the welcome gate, run in the official Playwright container.
# --network host + /etc/hosts pin: the hostname resolves to the LOCAL Traefik
# edge (valid LE cert), so tests exercise router + gate + app end-to-end
# without Cloudflare in the way. Set E2E_BASE to override.
set -euo pipefail

BASE=/opt/hortusfox-gate
IMAGE="${PW_IMAGE:-mcr.microsoft.com/playwright:v1.49.0-noble}"

docker pull -q "$IMAGE" >/dev/null

cd "$BASE"
docker run --rm --network host \
  --add-host "plants.silverwulf.org:192.168.50.241" \
  --add-host "garden.silverwulf.org:192.168.50.241" \
  -v "$BASE":/work -w /work -u root -e HOME=/tmp \
  --entrypoint /bin/bash "$IMAGE" -c "
    npm i --no-save --no-audit --no-fund "@playwright/test@$(echo "${IMAGE##*:v}" | cut -d- -f1)" >/dev/null 2>&1
    npx playwright test --reporter=list"
