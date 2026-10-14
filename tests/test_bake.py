"""Unit tests for deploy/bake.py against a fake HortusFox. No network.

    python3 -m unittest tests/test_bake.py      (needs Pillow)
"""
import importlib.util
import io
import json
import shutil
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("bake", ROOT / "deploy" / "bake.py")
bake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bake)

TOKEN = "test-token-not-real"


def jpeg_with_gps():
    im = Image.new("RGB", (2000, 1500), (90, 140, 60))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"                                     # Make
    exif.get_ifd(0x8825).update({1: "N", 2: (30.0, 1.0, 0.0), 3: "W", 4: (90.0, 2.0, 0.0)})
    out = io.BytesIO()
    im.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


def rows(*items):
    # HortusFox returns each column by name AND by index; the client must drop the latter.
    return [{**r, **{str(i): v for i, v in enumerate(r.values())}} for r in items]


class FakeHortus:
    def __init__(self):
        self.up = True
        self.locations = rows({"id": 1, "name": "Front bed", "active": 1},
                              {"id": 2, "name": "Porch", "active": 1},
                              {"id": 9, "name": "Trash", "active": 1})
        self.plants = rows(
            {"id": 1, "name": "Gardenia", "location": 1, "photo": "a_thumb.jpg", "history": 0, "created_at": "2026-09-01"},
            {"id": 2, "name": "Satsuma", "location": 2, "photo": "b_thumb.jpg", "history": 0, "created_at": "2026-10-01"},
            {"id": 3, "name": "Dead fern", "location": 9, "photo": "c_thumb.jpg", "history": 0, "created_at": "2026-10-05"},
            {"id": 4, "name": "Old rose", "location": 1, "photo": "d_thumb.jpg", "history": 1, "created_at": "2026-10-06"},
            {"id": 5, "name": "Sundew", "location": 2, "photo": "placeholder.jpg", "history": 0, "created_at": "2026-10-07"})
        self.tasks = rows({"id": 1, "title": "Water", "done": 0}, {"id": 2, "title": "Prune", "done": 0})
        self.photo = jpeg_with_gps()
        self.seen_tokens = set()

    def serve(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if not fake.up:
                    self.send_response(502); self.end_headers(); return
                u = urllib.parse.urlparse(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                if u.path.startswith("/img/"):
                    name = u.path[5:]
                    if name in ("a.jpg", "b.jpg"):
                        self.send_response(200); self.send_header("Content-Type", "image/jpeg")
                        self.end_headers(); self.wfile.write(fake.photo); return
                    self.send_response(404); self.end_headers(); return
                fake.seen_tokens.add(q.get("token"))
                body = {"/api/locations/list": {"code": 200, "list": fake.locations},
                        "/api/plants/search": {"code": 200, "list": fake.plants},
                        "/api/tasks/fetch": {"code": 200, "data": fake.tasks}}.get(u.path)
                if body is None or q.get("token") != TOKEN:
                    body = {"code": 403}
                data = json.dumps(body).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.end_headers(); self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"


class BakeTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeHortus()
        self.client = bake.Hortus(self.fake.serve(), TOKEN, timeout=5)
        self.site = Path(tempfile.mkdtemp())
        (self.site / "index.html").write_text("<html></html>")

    def tearDown(self):
        self.fake.httpd.shutdown()
        shutil.rmtree(self.site)

    def read_garden(self):
        text = (self.site / "plants.local.js").read_text()
        return json.loads(text[text.index("window.GARDEN = ") + 16:].rstrip().rstrip(";"))

    def test_counts_photos_and_metadata_stripped(self):
        bake.bake(self.client, self.site, want_photos=6)
        g = self.read_garden()
        # living = not archived, not in Trash; spaces exclude Trash; open tasks only
        self.assertEqual(g["stats"], {"plants": 3, "beds": 2, "tasks": 2})
        self.assertEqual([f["name"] for f in g["featured"]], ["Satsuma", "Gardenia"])   # newest first
        self.assertEqual(g["featured"][0]["loc"], "Porch")
        for f in g["featured"]:
            p = self.site / f["photo"]
            with Image.open(p) as im:
                self.assertLessEqual(max(im.size), bake.MAX_EDGE)
                self.assertEqual(len(im.getexif()), 0, "EXIF/GPS must be gone")
                self.assertNotIn("exif", im.info)
                self.assertNotIn("icc_profile", im.info)
            self.assertNotIn(b"PhoneMaker", p.read_bytes())
        self.assertNotIn(TOKEN, (self.site / "plants.local.js").read_text())

    def test_unreachable_keeps_last_good_build(self):
        bake.bake(self.client, self.site)
        before = (self.site / "plants.local.js").read_bytes()
        photos = sorted(p.name for p in (self.site / "assets" / "photos").iterdir())
        self.fake.up = False
        with self.assertRaises(bake.BakeError):
            bake.bake(self.client, self.site)
        self.assertEqual((self.site / "plants.local.js").read_bytes(), before)
        self.assertEqual(sorted(p.name for p in (self.site / "assets" / "photos").iterdir()), photos)

    def test_empty_or_collapsed_garden_is_refused(self):
        bake.bake(self.client, self.site)
        before = (self.site / "plants.local.js").read_bytes()
        self.fake.plants = self.fake.plants[:1]                    # 3 living -> 1
        with self.assertRaises(bake.BakeError):
            bake.bake(self.client, self.site)
        self.assertEqual((self.site / "plants.local.js").read_bytes(), before)
        bake.bake(self.client, self.site, force=True)              # --force accepts it
        self.assertEqual(self.read_garden()["stats"]["plants"], 1)
        self.fake.plants = []
        with self.assertRaises(bake.BakeError):
            bake.bake(self.client, self.site, force=True)

    def test_bad_token_fails_without_leaking_it(self):
        self.client.token = "wrong-secret-xyz"
        with self.assertRaises(bake.BakeError) as cm:
            bake.bake(self.client, self.site)
        self.assertNotIn("wrong-secret-xyz", str(cm.exception))
        self.assertFalse((self.site / "plants.local.js").exists())

    def test_old_photos_pruned_after_one_cycle(self):
        photos = self.site / "assets" / "photos"
        bake.bake(self.client, self.site)
        first = {p.name for p in photos.iterdir()}
        self.fake.photo = self._other_jpeg()
        bake.bake(self.client, self.site)
        second = {p.name for p in photos.iterdir()}
        self.assertTrue(first < second, "previous build's photos kept one more cycle")
        bake.bake(self.client, self.site)
        third = {p.name for p in photos.iterdir()}
        self.assertEqual(third, second - first, "then pruned")

    @staticmethod
    def _other_jpeg():
        out = io.BytesIO()
        Image.new("RGB", (800, 600), (200, 60, 90)).save(out, "JPEG")
        return out.getvalue()


if __name__ == "__main__":
    unittest.main()
