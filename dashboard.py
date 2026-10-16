"""TechPulse mobile dashboard (PWA). Run: .venv\\Scripts\\python.exe dashboard.py  -> open http://<PC-IP>:8765 on phone."""
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
WEB = ROOT / "web"
LOG = ROOT / "logs" / "run.log"
HISTORY = ROOT / "history.json"
PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))
PUBLIC = {"/", "/index.html", "/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png", "/api/login"}

mimetypes.add_type("application/manifest+json", ".webmanifest")
_proc = None  # currently running autotube job started from the dashboard


def env_password():
    env = ROOT / ".env"
    text = env.read_text(encoding="utf-8-sig") if env.exists() else ""
    m = re.search(r"(?m)^DASHBOARD_PASSWORD=(.+)$", text)
    if m and m.group(1).strip():
        return m.group(1).strip()
    pw = secrets.token_urlsafe(8)
    env.write_text(text.rstrip() + f"\r\n\r\n# Password for the mobile dashboard\r\nDASHBOARD_PASSWORD={pw}\r\n", encoding="utf-8")
    return pw


PASSWORD = env_password()
TOKEN = hashlib.sha256(f"techpulse-dashboard:{PASSWORD}".encode()).hexdigest()


def read_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def list_videos():
    uploaded = {h.get("video"): h.get("youtube_id") for h in read_json(HISTORY, []) if isinstance(h, dict)}
    items = []
    for video in OUT.glob("**/final.mp4"):
        d = video.parent
        meta = read_json(d / "meta.json", None)
        kind = "long" if "long" in d.name else "short"
        if meta is None:  # older layout: meta.json one level up with long/short keys
            parent = read_json(d.parent / "meta.json", {})
            meta = {**parent.get(d.name, {}), "topic": parent.get("topic", d.parent.name)}
        rel = d.relative_to(OUT).as_posix()
        desc = d / "description.txt"
        items.append({
            "id": rel, "kind": kind, "topic": meta.get("topic", ""), "title": meta.get("title", d.name),
            "description": desc.read_text(encoding="utf-8") if desc.exists() else meta.get("description", ""),
            "video": f"/media/{rel}/final.mp4",
            "thumb": f"/media/{rel}/thumb.jpg" if (d / "thumb.jpg").exists() else None,
            "youtube_id": uploaded.get(str(video)),
            "can_upload": (d / "meta.json").exists() and desc.exists(),
            "mtime": video.stat().st_mtime,
        })
    return sorted(items, key=lambda i: i["mtime"], reverse=True)


def log_tail(n=150):
    if not LOG.exists():
        return ""
    with open(LOG, "rb") as f:
        f.seek(max(0, LOG.stat().st_size - 60000))
        return "\n".join(f.read().decode("utf-8", "replace").splitlines()[-n:])


def start_job(args):
    global _proc
    if _proc and _proc.poll() is None:
        return False
    LOG.parent.mkdir(exist_ok=True)
    logf = open(LOG, "a", encoding="utf-8")
    logf.write(f"\n===== dashboard: autotube.py {' '.join(args)} =====\n")
    logf.flush()
    _proc = subprocess.Popen([sys.executable, str(ROOT / "autotube.py"), *args], cwd=ROOT, stdout=logf,
                             stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def authed(self):
        cookie = self.headers.get("Cookie", "")
        m = re.search(r"tp_auth=([0-9a-f]{64})", cookie)
        return bool(m) and hmac.compare_digest(m.group(1), TOKEN)

    def send_json(self, obj, code=200, headers=()):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, cache="no-cache"):
        size = path.stat().st_size
        start, end = 0, size - 1
        rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if rng and (rng[1] or rng[2]):
            if rng[1]:
                start = int(rng[1])
                end = min(int(rng[2]), size - 1) if rng[2] else size - 1
            else:
                start = max(0, size - int(rng[2]))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", cache)
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in PUBLIC and path != "/api/login":
            return self.send_file(WEB / ("index.html" if path == "/" else path.lstrip("/")))
        if not self.authed():
            return self.send_json({"error": "login required"}, 401)
        if path == "/api/state":
            return self.send_json({"running": bool(_proc and _proc.poll() is None),
                                   "items": list_videos(), "log": log_tail()})
        if path.startswith("/media/"):
            f = (OUT / path[len("/media/"):]).resolve()
            if OUT.resolve() in f.parents and f.is_file() and f.suffix in (".mp4", ".jpg"):
                return self.send_file(f, cache="private, max-age=3600")
        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        data = self.body_json()
        if path == "/api/login":
            if hmac.compare_digest(str(data.get("password", "")), PASSWORD):
                return self.send_json({"ok": True}, headers=[(
                    "Set-Cookie", f"tp_auth={TOKEN}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict")])
            return self.send_json({"error": "wrong password"}, 403)
        if not self.authed():
            return self.send_json({"error": "login required"}, 401)
        if path == "/api/run":
            args = ["--long", str(int(bool(data.get("long")))), "--shorts", str(max(0, min(4, int(data.get("shorts", 1)))))]
            if not data.get("upload"):
                args.append("--no-upload")
            return self.send_json({"started": start_job(args)})
        if path == "/api/upload":
            d = (OUT / str(data.get("id", ""))).resolve()
            if OUT.resolve() not in d.parents or not (d / "meta.json").exists():
                return self.send_json({"error": "bad video id"}, 400)
            return self.send_json({"started": start_job(["--upload-dir", str(d)])})
        self.send_json({"error": "not found"}, 404)


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    print(f"TechPulse dashboard: http://{lan_ip()}:{PORT}  (phone must be on the same Wi-Fi)")
    print("Password is DASHBOARD_PASSWORD in .env")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
