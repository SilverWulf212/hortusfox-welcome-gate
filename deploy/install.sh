#!/usr/bin/env bash
# Install the HortusFox welcome gate on wulfdock.
# Safe by construction: adds one container + one Traefik file; edits nothing.
set -euo pipefail

BASE=/opt/hortusfox-gate
DYN=/opt/traefik/dynamic
TS=$(date +%Y%m%d-%H%M%S)
BK=/root/backups/pre-gate-$TS
mkdir -p "$BK"

echo "== pre-change backup =="
cp -a "$DYN/hortusfox.yml" "$BK/" 2>/dev/null || true
cp -a "$DYN/00-base.yml"  "$BK/" 2>/dev/null || true
tar -czf "$BK/traefik-dynamic.tgz" -C /opt/traefik dynamic
ls -la "$BK"

echo "== validate gate yaml =="
python3 - "$BASE/deploy/hortusfox-gate.yml" <<'PY'
import sys, yaml
yaml.safe_load(open(sys.argv[1]))
print("yaml OK")
PY

echo "== place router file =="
cp "$BASE/deploy/hortusfox-gate.yml" "$DYN/hortusfox-gate.yml"

echo "== start gate container =="
docker compose -f "$BASE/deploy/docker-compose.yml" up -d --quiet-pull

sleep 2
echo "== verify =="
fail=0
check() { # name url expect_sub
  local body code
  body=$(curl -s --max-time 8 -w "\n%{http_code}" "$2")
  code=$(printf '%s' "$body" | tail -1)
  if [ "$code" != "200" ]; then echo "FAIL $1 -> $code"; fail=1; return; fi
  if [ -n "${3:-}" ] && ! printf '%s' "$body" | grep -q "$3"; then echo "FAIL $1 (content)"; fail=1; return; fi
  echo "ok   $1 -> $code"
}
check "gate /"            "http://192.168.50.241:8124/"                 "living garden"
check "gate plants.local" "http://192.168.50.241:8124/plants.local.js"  "GARDEN"
pc=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "http://192.168.50.241:8124/assets/photos/p1.jpg")
if [ "$pc" = "200" ]; then echo "ok   gate photo -> 200"; else echo "FAIL gate photo -> $pc"; fail=1; fi
check "app /auth"         "http://192.168.50.241:8123/auth"
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "http://192.168.50.241:8123/index.php")
if [ "$code" = "302" ]; then echo "ok   app /index.php -> 302 (to auth, logged out)"; else echo "FAIL app /index.php -> $code"; fail=1; fi

if [ "$fail" != "0" ]; then
  echo "== FAILURES — rolling back =="
  docker compose -f "$BASE/deploy/docker-compose.yml" down || true
  rm -f "$DYN/hortusfox-gate.yml"
  exit 1
fi

echo "== collateral sweep (traefik must route other hosts untouched) =="
for h in gitea.silverwulf.org mealie.silverwulf.org; do
  code=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 8 "https://$h/")
  echo "$h -> $code"
done

echo "== public checks =="
code=$(curl -sk -o /tmp/gate.html -w "%{http_code}" --max-time 10 "https://plants.silverwulf.org/")
grep -q "living garden" /tmp/gate.html && echo "ok   https://plants.silverwulf.org/ serves the gate" || { echo "FAIL gate content"; fail=1; }
code2=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 10 "https://plants.silverwulf.org/auth")
echo "plants.silverwulf.org/auth -> $code2 (302 expected)"
code3=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 10 "https://plants.silverwulf.org/plants")
echo "plants.silverwulf.org/plants -> $code3 (302 expected)"
code4=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 10 "https://plants.silverwulf.org/index.php")
echo "plants.silverwulf.org/index.php -> $code4 (302 expected)"

[ "$fail" = "0" ] && echo "ALL GREEN — gate live. Rollback: $BASE/rollback.sh" || { echo "FAILURES — rolling back"; "$BASE/rollback.sh"; exit 1; }
