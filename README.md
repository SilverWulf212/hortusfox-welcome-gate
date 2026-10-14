# HortusFox Welcome Gate

A static, single-page welcome overlay that sits in front of a self-hosted
[HortusFox](https://github.com/danielbrendel/hortusfox-web) plant manager and
hands off to it with a fade. It changes nothing inside HortusFox: no themes,
no patches, no template edits, no database writes — so upstream updates can
never break it, and removing it is two commands.

**Live behavior**

- `https://your-hortusfox.example/` → this welcome page (first visit)
- every other path — `/auth`, `/plants`, `/tasks`, `/api/*`, PHP, assets —
  proxies to HortusFox exactly as before
- clicking *Enter the garden* fades to pale and lands you in the app
- returning visitors skip the splash instantly (`localStorage` flag →
  `/index.php`, which still reaches the app because the gate only owns `/`)

**Why it stays safe across HortusFox releases**

The overlay is served by its own tiny nginx container. HortusFox containers,
volumes, compose files and themes are untouched. The only two assumptions —
`/index.php` resolves to the app and `/auth` is the login route — were true
for every modern HortusFox release, and both fail soft: worst case, visitors
see the splash once more.

## Install (Traefik with file provider)

1. Copy this repo to your Docker host, e.g. `/opt/hortusfox-gate/`.
2. Put your instance's real data in `site/plants.local.js` (see the shape
   documented inside `site/index.html`), or let `deploy/bake.py` build it
   from the API (below). Skip it to use the built-in placeholders. Photos go in `site/assets/photos/` — keep personal photos
   out of any public fork of this repo.
3. Adjust hostnames/IP/port in `deploy/hortusfox-gate.yml` and
   `deploy/docker-compose.yml` (pick a free port).
4. Run `deploy/install.sh` — it backs up your Traefik dynamic dir, validates
   the YAML, deploys, verifies the gate AND the app AND unrelated hosts, and
   auto-rolls-back on any failure.

## Nightly rebuild from live data

`deploy/bake.py` regenerates `site/plants.local.js` from the HortusFox REST
API: living plants (not archived, not in Trash), growing spaces (locations
minus Trash and inactive ones), open tasks, and a few plant photos
(`GATE_PHOTOS`, default 6). Photo order: plants with a soil sensor first
(a plant-log line starting "soil sensor" / "auto ha", as The Garden dashboard
detects it, or a tag/attribute mentioning a sensor), then healthy plants
(`health_state` in good standing), most recently photographed first (the
photo's Last-Modified, else the plant's updated/created date). Each photo is downscaled to 640 px and re-encoded from bare
pixels, so no EXIF, GPS, XMP or ICC data reaches the public site. Photos are
content-named (`<hash>.jpg`) so week-long caches never show a stale picture.

It never breaks the live page: everything is fetched and built first, and
only a complete build replaces the old one. HortusFox down, a bad token, an
empty answer, or a plant count that halves overnight → exit 1, last good
build still served. `--force` accepts a genuine big drop.

```bash
# token: a HortusFox API key, on the host only (never in this repo). The bake
# container runs as the owner of site/, so that user owns the token file.
o=$(stat -c %u /opt/hortusfox-gate/site); g=$(stat -c %g /opt/hortusfox-gate/site)
sudo install -d -m 755 /etc/hortusfox-gate
sudo install -m 600 -o "$o" -g "$g" /dev/null /etc/hortusfox-gate/token
sudoedit /etc/hortusfox-gate/token            # paste the key, save
/opt/hortusfox-gate/deploy/bake.sh            # Docker-wrapped (Python + Pillow)
sudo cp deploy/hortusfox-gate-bake.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now hortusfox-gate-bake.timer
```

Cron instead of systemd: `15 4 * * * /opt/hortusfox-gate/deploy/bake.sh`.
Tests (no network, needs Pillow): `python3 -m unittest tests/test_bake.py`.

## Fronting a second app

The same page can greet signed-out visitors of another app. `GATE_HOSTS` in
`site/index.html` maps a hostname to that app's sign-in (here
`garden.silverwulf.org` → `/login`, "Sign in"); on a listed host the
HortusFox hand-off cookie is never set. The Traefik router `garden-gate`
sends `/` to the gate only when the app's session cookie (`garden_session`)
is absent, and the matching nginx `server` block serves the page without
any proxying. The app itself is unchanged.

## Rollback

```bash
/opt/hortusfox-gate/deploy/rollback.sh
```

## How it's built

One HTML file, ~200 lines of vanilla JS, no frameworks, no build step, no
external requests. (The optional nightly bake is a separate script; the page
itself still has no build step.) Botanical line-art and the two native-vine illustrations
(coral honeysuckle, crossvine) are original inline SVG. Pollen drift is a
small canvas; everything honors `prefers-reduced-motion`.

## License

MIT — see [LICENSE](LICENSE).
