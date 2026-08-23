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
   documented inside `site/index.html`). Skip it to use the built-in
   placeholders. Photos go in `site/assets/photos/` — keep personal photos
   out of any public fork of this repo.
3. Adjust hostnames/IP/port in `deploy/hortusfox-gate.yml` and
   `deploy/docker-compose.yml` (pick a free port).
4. Run `deploy/install.sh` — it backs up your Traefik dynamic dir, validates
   the YAML, deploys, verifies the gate AND the app AND unrelated hosts, and
   auto-rolls-back on any failure.

## Rollback

```bash
/opt/hortusfox-gate/deploy/rollback.sh
```

## How it's built

One HTML file, ~200 lines of vanilla JS, no frameworks, no build step, no
external requests. Botanical line-art and the two native-vine illustrations
(coral honeysuckle, crossvine) are original inline SVG. Pollen drift is a
small canvas; everything honors `prefers-reduced-motion`.

## License

MIT — see [LICENSE](LICENSE).
