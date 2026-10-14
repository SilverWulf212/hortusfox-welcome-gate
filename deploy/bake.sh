#!/usr/bin/env bash
# Nightly rebuild of the gate's live numbers + photos from HortusFox.
# Runs deploy/bake.py in a throwaway container (Python + Pillow), as the
# owner of site/, so the host needs nothing but Docker.
#
# Token: /etc/hortusfox-gate/token, mode 600, owned by the owner of site/
# (the container runs as that user). Never in this repo.
# Exit 0 = new build live. Exit 1 = HortusFox unreachable/odd; the previous
# build is still being served untouched.
set -euo pipefail

BASE="${GATE_BASE:-/opt/hortusfox-gate}"
TOKEN_FILE="${HORTUSFOX_TOKEN_FILE:-/etc/hortusfox-gate/token}"
IMAGE=hortusfox-gate-bake:local

[ -r "$TOKEN_FILE" ] || { echo "bake: no readable token at $TOKEN_FILE" >&2; exit 1; }

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  docker build -q -t "$IMAGE" -f "$BASE/deploy/bake.Dockerfile" "$BASE/deploy" >/dev/null
fi

owner=$(stat -c %u:%g "$BASE/site")
if [ "$(stat -c %u "$TOKEN_FILE")" != "${owner%%:*}" ]; then
  echo "bake: $TOKEN_FILE must be owned by the owner of site/ (uid ${owner%%:*}), mode 600" >&2
  exit 1
fi
exec docker run --rm --network host --user "$owner" \
  -v "$BASE":/gate:ro \
  -v "$BASE/site":/gate/site \
  -v "$TOKEN_FILE":/run/hortusfox-token:ro \
  -e HORTUSFOX_TOKEN_FILE=/run/hortusfox-token \
  -e HORTUSFOX_URL="${HORTUSFOX_URL:-http://192.168.50.241:8123}" \
  -e GATE_SITE=/gate/site \
  -e GATE_PHOTOS="${GATE_PHOTOS:-6}" \
  "$IMAGE" "$@"
