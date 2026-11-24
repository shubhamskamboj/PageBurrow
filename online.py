"""Small-instance hosted entry point. Run behind a TLS-terminating reverse proxy.

The existing PDF engine is single-threaded. Each browser gets separate in-memory
document maps and a temporary directory; requests are deliberately serialized.
"""
import os
from pathlib import Path
import secrets
import shutil
import tempfile
import time
from http.cookies import SimpleCookie, CookieError
from urllib.parse import urlsplit

import app

LIMIT = 10 * 1024 * 1024
SESSION_BYTES = 40 * 1024 * 1024
TTL = 30 * 60
COOKIE = "__Host-pageburrow"
SOURCE = "https://github.com/shubhamskamboj/PageBurrow"
MUPDF_PATH = "vendor/mupdf-1.28.6"
BROWSER_ASSETS = {
    "/large-pdf.js": ("large-pdf.js", "text/javascript; charset=utf-8"),
    "/large-pdf-worker.js": ("large-pdf-worker.js", "text/javascript; charset=utf-8"),
    f"/{MUPDF_PATH}/mupdf.js": (f"{MUPDF_PATH}/mupdf.js", "text/javascript; charset=utf-8"),
    f"/{MUPDF_PATH}/mupdf-wasm.js": (f"{MUPDF_PATH}/mupdf-wasm.js", "text/javascript; charset=utf-8"),
    f"/{MUPDF_PATH}/mupdf-wasm.wasm": (f"{MUPDF_PATH}/mupdf-wasm.wasm", "application/wasm"),
    f"/{MUPDF_PATH}/LICENSE": (f"{MUPDF_PATH}/LICENSE", "text/plain; charset=utf-8"),
}
SESSIONS = {}
app.MAX_UPLOAD = LIMIT
app.MAX_PDF = LIMIT
app.MAX_COMPRESS = LIMIT
app.UPLOAD_LIFETIME = TTL


def expire():
    now = time.monotonic()
    for key, session in list(SESSIONS.items()):
        if now - session["used"] > TTL:
            shutil.rmtree(session["directory"], ignore_errors=True)
            del SESSIONS[key]


class OnlineRequest(app.Request):
    def log_message(self, format, *args):
        # Do not log uploaded filenames, document tokens, or request query strings.
        pass

    def host_allowed(self, host):
        return host == urlsplit(self.server.public_origin).netloc

    def is_remote(self):
        # Public users do not use the local-network PIN pairing flow.
        return False

    def send(self, data, content_type, code=200, headers=(), referrer="no-referrer"):
        if content_type.startswith("text/html") and code == 200:
            text = data.decode()
            text = text.replace("Every PDF tool, on your own device", "Your PDF toolbox, online")
            has_browser_engine = (app.ROOT / "web" / MUPDF_PATH / "mupdf-wasm.wasm").is_file()
            description = (
                "Large PDF Tools process up to 200 MB in your browser. "
                "Standard tools upload up to 10 MB per file to this server for processing."
                if has_browser_engine else
                "Files are uploaded to this server for processing. Up to 10 MB per upload."
            )
            text = text.replace(
                "Edit, convert, organize, sign and protect PDFs. Your files are never uploaded to the internet, there are no limits, and it works offline.",
                f"Edit, convert, organize, sign and protect PDFs in your browser. {description}")
            text = text.replace("● Works offline · Files stay on your device",
                'Online preview · Files expire after 30 minutes of session inactivity. '
                'Download results before leaving. '
                '<a href="' + SOURCE + '">Source code &amp; local offline version</a>')
            text = text.replace('<div id="tool-grid"',
                '<p class="muted">HTML-to-PDF and extra OCR language downloads are unavailable in this hosted preview. '
                'English and Hindi OCR are included. Translation requires a supported browser. '
                'This shared preview is intended for small, non-sensitive documents.</p><div id="tool-grid"')
            if has_browser_engine:
                text = text.replace("</head>", '  <script src="/large-pdf.js" defer></script>\n</head>')
            data = text.encode()
        if getattr(self, "new_cookie", None):
            headers = tuple(headers) + (("Set-Cookie", f"{COOKIE}={self.new_cookie}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={TTL}"),)
        super().send(data, content_type, code, headers, referrer)

    def dispatch(self, post):
        self.new_cookie = None
        path = urlsplit(self.path).path
        # Health probes carry no user data and can arrive over the internal host.
        if path == "/healthz" and not post:
            self.json({"status": "ok"})
            return
        if not self.host_allowed(self.headers.get("Host", "")):
            self.json({"error": "Use the configured public website address."}, 403)
            return
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.server.public_origin:
            self.json({"error": "Open PageBurrow in its own browser tab."}, 403)
            return
        # A shared link must open the home page in a top-level browser tab.
        landing_navigation = (
            not post and path == "/"
            and self.headers.get("Sec-Fetch-Mode") == "navigate"
            and self.headers.get("Sec-Fetch-Dest") == "document"
        )
        if self.headers.get("Sec-Fetch-Site") == "cross-site" and not landing_navigation:
            self.json({"error": "Cross-site requests are not supported."}, 403)
            return
        if post and self.headers.get("X-Local-Editor") != "1":
            self.json({"error": "Open PageBurrow in its own browser tab."}, 403)
            return
        if not post and path in BROWSER_ASSETS:
            self.browser_asset(path)
            return
        # Reject oversized/chunked input before the original handler reads it.
        if post:
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                size = -1
            if self.headers.get("Transfer-Encoding") or not 0 <= size <= LIMIT:
                self.json({"error": "Uploads and requests must be no larger than 10 MB."}, 413)
                return
        expire()
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", "")).get(COOKIE)
            key = cookie.value if cookie else None
        except CookieError:
            key = None
        session = SESSIONS.get(key)
        if session is None:
            # Only the main page creates sessions; assets and probes cannot fill slots.
            if path != "/" or post:
                if not post and path in {**app.STATIC, **app.PUBLIC}:
                    name, mime = {**app.STATIC, **app.PUBLIC}[path]
                    self.send((app.ROOT / "web" / name).read_bytes(), mime)
                else:
                    self.json({"error": "Your session expired. Reload PageBurrow and add your files again."}, 401)
                return
            if len(SESSIONS) >= 4:
                self.send(b"PageBurrow is busy. Please try again later.", "text/plain", 503,
                          (("Retry-After", "60"),))
                return
            key = secrets.token_urlsafe(32)
            session = {"used": time.monotonic(), "files": app.OrderedDict(), "uploads": {},
                       "originals": {}, "directory": Path(tempfile.mkdtemp(dir=app.UPLOAD_DIR))}
            SESSIONS[key] = session
        session["used"] = time.monotonic()
        self.new_cookie = key
        previous = app.FILES, app.UPLOADS, app.ORIGINALS, app.UPLOAD_DIR
        app.FILES, app.UPLOADS, app.ORIGINALS, app.UPLOAD_DIR = (
            session["files"], session["uploads"], session["originals"], session["directory"])
        try:
            used = sum(p.stat().st_size for p in app.UPLOAD_DIR.iterdir() if p.is_file())
            if post and path not in ("/api/forget", "/api/close") and used + size > SESSION_BYTES:
                self.json({"error": "Session storage is full. Remove files before continuing."}, 413)
                return
            if path == "/api/open":
                # Keep at most one editor document per visitor.
                app.FILES.clear()
                app.ORIGINALS.clear()
            # Original local-mode handler validates http://Host. The external
            # origin was checked above; normalize only for the internal dispatch.
            if origin is not None:
                self.headers.replace_header("Origin", "http://" + self.headers["Host"])
            super().dispatch(post)
        finally:
            app.FILES, app.UPLOADS, app.ORIGINALS, app.UPLOAD_DIR = previous

    def browser_asset(self, path):
        filename, mime = BROWSER_ASSETS[path]
        asset = app.ROOT / "web" / filename
        if not asset.is_file():
            self.json({"error": "PDF engine asset unavailable."}, 404)
            return
        if path == "/large-pdf-worker.js":
            self.content_security_policy = (
                "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'"
            )
        headers = []
        if filename.startswith(MUPDF_PATH):
            headers.append(("Cache-Control", "public, max-age=31536000, immutable"))
            headers.append(("Vary", "Accept-Encoding"))
            encodings = self.headers.get("Accept-Encoding", "").split(",")
            compressed = asset.with_name(asset.name + ".br")
            if "br" in [encoding.strip() for encoding in encodings] and compressed.is_file():
                headers.append(("Content-Encoding", "br"))
                asset = compressed
        self.send(asset.read_bytes(), mime, headers=headers)

    def tool_request(self, path, payload):
        if path == "/api/ocr-language" or (path == "/api/tool" and payload.get("tool") == "html_to_pdf"):
            raise app.EditError("This feature is available in the local version only. See the source code link below the tools.")
        super().tool_request(path, payload)


class OnlineServer(app.Server):
    def service_actions(self):
        expire()


def main():
    origin = os.environ.get("PUBLIC_ORIGIN") or os.environ.get("RENDER_EXTERNAL_URL", "")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
        raise SystemExit("Set PUBLIC_ORIGIN to the HTTPS address of this website.")
    with OnlineServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), OnlineRequest) as server:
        server.public_origin = origin.rstrip("/")
        server.lan, server.secret, server.pin, server.addresses = False, "", "", []
        print(f"PageBurrow hosted preview: {server.public_origin}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
