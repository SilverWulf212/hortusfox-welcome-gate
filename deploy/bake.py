#!/usr/bin/env python3
"""Rebuild site/plants.local.js (and its photos) from a live HortusFox.

Reads locations, plants, open tasks and plant logs through the HortusFox REST
API with an API token. Writes the counts the welcome page shows, plus a
handful of plant photos, downscaled and stripped of every byte of metadata
(EXIF, GPS, XMP, ICC) before they land in the public site.

Which photos: plants with a soil sensor first (detected the way The Garden
dashboard does it: a plant-log line starting "soil sensor" or "auto ha", or a
plant attribute/tag mentioning a sensor), then the best of the rest: healthy
health_state, a real photo, most recently photographed.

Safe when HortusFox is down: everything is fetched and built in memory and
on temp files first. Only a complete, sane build replaces the live files, so
a failed run leaves the last good build in place and exits non-zero.

Config (environment):
  HORTUSFOX_URL         base URL      (default http://192.168.50.241:8123)
  HORTUSFOX_TOKEN       API token, or
  HORTUSFOX_TOKEN_FILE  file holding it (default /etc/hortusfox-gate/token)
  GATE_SITE             site dir      (default: ../site next to this file)
  GATE_PHOTOS           how many photos to feature (default 6; 0 = counts only,
                        the photo strip is hidden)

Needs Python 3.9+ and Pillow. deploy/bake.sh runs it in a container that has both.
"""

import hashlib
import http.client
import io
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from PIL import Image, ImageOps

NET_ERRORS = (OSError, http.client.HTTPException, ValueError)
IMAGE_NAME = re.compile(r"\A[A-Za-z0-9_.-]{1,120}\.(?:jpe?g|png|webp|gif)\Z")
PHOTO_NAME = re.compile(r"\A[0-9a-f]{16}\.jpg\Z")     # what this script writes
MAX_EDGE = 640                                       # px; the strip shows ~150px tiles
SHRINK_GUARD = 0.5     # refuse a build that loses more than half the plants at once
GOOD_HEALTH = "in_good_standing"                     # HortusFox's healthy state
SENSOR_PREFIX = ("soil sensor", "auto ha")           # same as garden-dashboard standing.py
SENSOR_WORD = re.compile(r"\bsensor\b", re.I)


class BakeError(Exception):
    pass


def log(msg):
    print(f"bake: {msg}", flush=True)


# ---- HortusFox -------------------------------------------------------------

class Hortus:
    def __init__(self, base, token, timeout=20):
        self.base, self.token, self.timeout = base.rstrip("/"), token, timeout

    def get(self, path, key, **params):
        qs = urllib.parse.urlencode({"token": self.token, **params})
        try:
            with urllib.request.urlopen(f"{self.base}{path}?{qs}", timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
        except NET_ERRORS as e:
            # never echo the URL: it carries the token
            raise BakeError(f"HortusFox did not answer {path}: {type(e).__name__}") from None
        if not isinstance(data, dict) or data.get("code") != 200:
            raise BakeError(f"HortusFox refused {path} (code {data.get('code') if isinstance(data, dict) else '?'})")
        # The API returns every column twice (by name and by index); keep names.
        return [{k: v for k, v in row.items() if not str(k).isdigit()}
                for row in (data.get(key) or []) if isinstance(row, dict)]

    def image(self, name):
        if not IMAGE_NAME.match(name):
            raise BakeError("bad image name")
        try:
            with urllib.request.urlopen(f"{self.base}/img/{name}", timeout=self.timeout) as r:
                if not (r.headers.get_content_type() or "").startswith("image/"):
                    raise BakeError("not an image")
                return r.read()
        except NET_ERRORS:
            raise BakeError(f"image unavailable: {name}") from None

    def photo_time(self, name):
        """When the photo file was last written (Last-Modified), or None."""
        if not IMAGE_NAME.match(name):
            return None
        req = urllib.request.Request(f"{self.base}/img/{name}", method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                lm = r.headers.get("Last-Modified")
            return parsedate_to_datetime(lm).timestamp() if lm else None
        except (*NET_ERRORS, TypeError):
            return None

    def has_sensor_log(self, plant_id):
        try:
            log = self.get("/api/plants/log/fetch", "log", plant=plant_id, limit=300)
        except BakeError:
            return False                          # a missing log is not a failed build
        return any((e.get("content") or "").lower().startswith(SENSOR_PREFIX) for e in log)


# ---- build -----------------------------------------------------------------

def is_trash(loc):
    return (loc.get("name") or "").strip().lower() == "trash"


def summarize(locations, plants, open_tasks):
    """Counts + the plants that could be featured (unranked). Pure; no I/O."""
    trash = {l["id"] for l in locations if "id" in l and is_trash(l)}
    beds = [l for l in locations if "id" in l and not is_trash(l)
            and str(l.get("active", 1)) not in ("0", "False", "false")]
    names = {l["id"]: (l.get("name") or "").strip() for l in locations if "id" in l}
    living = [p for p in plants if "id" in p and not p.get("history")
              and p.get("location") not in trash]
    with_photo = [p for p in living
                  if p.get("photo") and not str(p["photo"]).startswith("placeholder")]
    featured = [{"id": p["id"],
                 "name": (p.get("name") or "").strip() or "Unnamed plant",
                 "loc": names.get(p.get("location"), ""),
                 "src": str(p["photo"]),
                 "healthy": (p.get("health_state") or GOOD_HEALTH) == GOOD_HEALTH,
                 "attr_sensor": any(SENSOR_WORD.search(str(p.get(k) or ""))
                                    for k in ("tags", "sensor", "notes")),
                 "dated": str(p.get("updated_at") or p.get("created_at") or "")}
                for p in with_photo]
    stats = {"plants": len(living), "beds": len(beds), "tasks": len(open_tasks)}
    return stats, featured


def _fallback_ts(dated):
    try:
        return datetime.fromisoformat(dated[:19]).timestamp()
    except ValueError:
        return 0.0


def rank(candidates, sensor_ids, photo_times):
    """Sensor plants first, then healthy, then most recently photographed.

    Pure. sensor_ids: plant ids with a soil-sensor log line. photo_times:
    {plant id: unix time the photo was written}; missing -> updated/created date.
    """
    def key(c):
        sensor = c["attr_sensor"] or c["id"] in sensor_ids
        when = photo_times.get(c["id"]) or _fallback_ts(c["dated"])
        return (sensor, c["healthy"], when, c["id"])
    return sorted(candidates, key=key, reverse=True)


def clean_jpeg(raw):
    """Downscale and re-encode with no metadata at all. Returns JPEG bytes."""
    with Image.open(io.BytesIO(raw)) as im:
        im = ImageOps.exif_transpose(im)        # honor rotation before EXIF goes
        im = im.convert("RGB")
        im.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        # Copy pixels only into a fresh image: no info, exif, xmp or icc rides along.
        bare = Image.frombytes("RGB", im.size, im.tobytes())
    out = io.BytesIO()
    bare.save(out, "JPEG", quality=78, optimize=True, progressive=True)
    return out.getvalue()


def previous_plants(js_path):
    """Plant count of the current live build, if it was written by this script."""
    try:
        text = js_path.read_text(encoding="utf-8")
        body = text[text.index("window.GARDEN = ") + 16:].rstrip().rstrip(";")
        return int(json.loads(body)["stats"]["plants"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_atomic(path, data, mode=0o644):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".bake-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def bake(hortus, site, want_photos=6, force=False):
    site = Path(site)
    js_path = site / "plants.local.js"
    photo_dir = site / "assets" / "photos"
    if not (site / "index.html").is_file():
        raise BakeError(f"{site} does not look like the gate site (no index.html)")

    locations = hortus.get("/api/locations/list", "list")
    plants = hortus.get("/api/plants/search", "list", expression="", limit=1000)
    open_tasks = hortus.get("/api/tasks/fetch", "data", done=0, limit=1000)
    stats, candidates = summarize(locations, plants, open_tasks)

    if not locations or stats["plants"] == 0:
        raise BakeError("HortusFox returned an empty garden; keeping the last build")
    prev = previous_plants(js_path)
    if prev and stats["plants"] < prev * SHRINK_GUARD and not force:
        raise BakeError(f"plant count fell from {prev} to {stats['plants']}; "
                        "keeping the last build (rerun with --force if that is real)")

    # Rank (sensor plants, then healthy, then freshest photo), then walk the
    # ranking until we have enough photos that download and decode.
    if want_photos > 0:
        sensor_ids = {c["id"] for c in candidates if hortus.has_sensor_log(c["id"])}
        photo_times = {c["id"]: hortus.photo_time(c["src"]) for c in candidates}
        candidates = rank(candidates, sensor_ids, {k: v for k, v in photo_times.items() if v})
    else:
        candidates = []
    featured, photos = [], {}
    for c in candidates:
        if len(featured) >= want_photos:
            break
        src = c["src"]
        c = {"name": c["name"], "loc": c["loc"]}
        raw = None
        for name in dict.fromkeys([src.replace("_thumb", ""), src]):   # full size, then thumb
            try:
                raw = hortus.image(name)
                break
            except BakeError:
                continue
        if raw is None:
            continue
        try:
            jpg = clean_jpeg(raw)
        except Exception as e:                  # corrupt upload: skip it, not the build
            log(f"skipping an unreadable photo ({type(e).__name__})")
            continue
        fname = hashlib.sha256(jpg).hexdigest()[:16] + ".jpg"   # content-named: caches never go stale
        photos[fname] = jpg
        featured.append({**c, "photo": f"assets/photos/{fname}"})

    baked = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    garden = {"baked": baked, "stats": stats, "featured": featured}
    js = ("/* Generated by deploy/bake.py from live HortusFox data. Do not edit;\n"
          "   do not commit (it is git-ignored). Rebuilt nightly. */\n"
          "window.GARDEN = " + json.dumps(garden, ensure_ascii=False, indent=2) + ";\n")

    # Commit: photos first (new names, nothing references them yet), then the
    # data file that points at them, then prune photos nothing points at.
    photo_dir.mkdir(parents=True, exist_ok=True)
    for fname, jpg in photos.items():
        if not (photo_dir / fname).exists():
            write_atomic(photo_dir / fname, jpg)
    old_refs = set(re.findall(r"assets/photos/([0-9a-f]{16}\.jpg)",
                              js_path.read_text(encoding="utf-8") if js_path.exists() else ""))
    write_atomic(js_path, js.encode("utf-8"))
    # Keep the previous build's photos one more cycle: an edge-cached copy of
    # the old plants.local.js may still reference them for a little while.
    keep = set(photos) | old_refs
    for f in photo_dir.iterdir():
        if PHOTO_NAME.match(f.name) and f.name not in keep:
            f.unlink()
    log(f"ok: {stats['plants']} plants, {stats['beds']} spaces, {stats['tasks']} open tasks, "
        f"{len(featured)} photos")
    return garden


def read_token():
    tok = os.environ.get("HORTUSFOX_TOKEN", "").strip()
    if tok:
        return tok
    path = os.environ.get("HORTUSFOX_TOKEN_FILE", "/etc/hortusfox-gate/token")
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        raise BakeError(f"no token: set HORTUSFOX_TOKEN or put it in {path}") from None


def main(argv):
    force = "--force" in argv
    site = os.environ.get("GATE_SITE") or str(Path(__file__).resolve().parent.parent / "site")
    try:
        hortus = Hortus(os.environ.get("HORTUSFOX_URL", "http://192.168.50.241:8123"), read_token())
        bake(hortus, site, int(os.environ.get("GATE_PHOTOS", "6")), force)
    except BakeError as e:
        log(f"FAILED, last good build kept: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
