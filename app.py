"""Web server for PageBurrow: edit and compress PDFs on your own device.

By default only this device can connect (127.0.0.1). With --lan, phones and tablets on
the same network can use the tool after entering a PIN shown in the terminal.
"""
import argparse
import atexit
import base64
from collections import OrderedDict, defaultdict
from decimal import Decimal
from html import escape
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

import pymupdf as pdf

from editor import EditError, apply_page, inspect_page, point
import pdftools
from pdftools.common import Input as ToolInput, zip_files
from pdftools.convert_to import BUILT_IN as OFFICE_READERS, libreoffice, with_libreoffice

ROOT = Path(__file__).resolve().parent
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/tools.js": ("tools.js", "text/javascript; charset=utf-8"),
          "/preview.js": ("preview.js", "text/javascript; charset=utf-8")}
# Served before a phone has entered the PIN, so the pairing page has an icon.
PUBLIC = {"/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
          "/icon-180.png": ("icon-180.png", "image/png"),
          "/icon-192.png": ("icon-192.png", "image/png"),
          "/icon-512.png": ("icon-512.png", "image/png")}
FILES = OrderedDict()
MAX_PDF = 160 * 1024 * 1024
MAX_COMPRESS = 200_000_000
MAX_IMAGE = 12 * 1024 * 1024
DEFAULT_PORT = 8765
COOKIE = "pdftools_access"
# Files for the tools are kept in a private temporary folder while the app runs and are
# deleted when it stops (or after 6 hours unused). Nothing leaves this device.
UPLOAD_DIR = Path(tempfile.mkdtemp(prefix="pageburrow-"))
atexit.register(shutil.rmtree, UPLOAD_DIR, True)
UPLOADS = {}
MAX_UPLOAD = 2_000_000_000
UPLOAD_LIFETIME = 6 * 3600
MIME = {".pdf": "application/pdf", ".zip": "application/zip", ".md": "text/markdown; charset=utf-8",
        ".jpg": "image/jpeg", ".png": "image/png",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"BM", b"II*\x00", b"MM\x00*")
# Previews of produced files, shown before they are downloaded.
PREVIEW_TEXT = (".md", ".txt", ".csv")
PREVIEW_TEXT_LIMIT = 400_000  # characters
PREVIEW_FILES = 200  # files of one result that can be previewed (all are in the download)
PREVIEW_IMAGES = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff")
PREVIEW_OFFICE = (".docx", ".docm", ".doc", ".odt", ".rtf", ".xlsx", ".xlsm", ".xls", ".ods", ".pptx", ".pptm", ".ppt", ".odp")
ORIGINALS = {}  # editor document token -> upload token of the PDF as it was opened
KEY_FILE = ROOT / ".phone-access-key"
MAX_PIN_FAILURES = 10
PAIR_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PageBurrow</title><link rel="apple-touch-icon" href="/icon-180.png"><link rel="icon" href="/icon-192.png">
<style>
*{{box-sizing:border-box}}
body{{margin:0;min-height:100dvh;display:flex;align-items:center;justify-content:center;background:#f3f6f4;color:#202a27;font:16px/1.5 system-ui,sans-serif;padding:16px}}
main{{width:100%;max-width:380px;background:#fff;border:1px solid #dce4e0;border-radius:16px;padding:26px}}
input{{width:100%}}
h1{{font-size:24px;margin:0 0 8px;letter-spacing:-.02em}}p{{margin:0 0 16px;color:#586763}}
label{{display:grid;gap:6px;font-weight:650}}input{{font:inherit;font-size:24px;letter-spacing:.3em;padding:10px;border:1px solid #c9d6ce;border-radius:8px;text-align:center}}
button{{margin-top:14px;width:100%;font:inherit;font-weight:650;color:#fff;background:#147552;border:0;border-radius:8px;padding:12px}}
.error{{background:#fff0ee;color:#852c26;border-radius:8px;padding:8px 10px;margin:14px 0 0}}
</style></head><body><main>
<h1>PageBurrow</h1>
<p>Enter the 6-digit PIN shown in the window of the computer running PageBurrow.</p>
<form method="post" action="/pair"><label>PIN<input name="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required autofocus></label>
<button>Continue</button></form>{message}
</main></body></html>"""


def document(session):
    data, password, _ = session
    doc = pdf.open(stream=data, filetype="pdf")
    # MuPDF can open user-password-free encrypted PDFs without prompting.
    authorization = doc.authenticate(password) if doc.needs_pass or doc.metadata and doc.metadata.get("encryption") else 4
    if not authorization:
        doc.close()
        raise EditError("Enter the correct PDF password.")
    if authorization not in (4, 6) and not (doc.permissions & pdf.PDF_PERM_MODIFY):
        doc.close()
        raise EditError("This PDF restricts editing with the supplied password.")
    return doc


def scanned(page):
    """True when images cover most of the page, as with scans and photos."""
    bounds = page.rect * page.derotation_matrix
    covered = sum(abs(pdf.Rect(info["bbox"]) & bounds) for info in page.get_image_info())
    return covered >= 0.5 * abs(bounds)


def clip_zoom(page, rect):
    """Pixels per point for an eraser patch: the resolution of the scan under `rect`."""
    area = rect * page.derotation_matrix
    best = 0.0
    for info in page.get_image_info():
        box = pdf.Rect(info["bbox"])
        if box.intersects(area) and box.width > 1 and box.height > 1:
            best = max(best, info["width"] / box.width, info["height"] / box.height)
    zoom = min(6.0, max(2.0, best or 3.0))
    return min(zoom, (4_000_000 / max(1.0, rect.width * rect.height)) ** 0.5)


def edits_by_page(edits, page_count):
    if not isinstance(edits, list) or len(edits) > 1500:
        raise EditError("A session supports up to 1,500 edits. Export and reopen to continue.")
    result = defaultdict(list)
    for edit in edits:
        number = edit["page"]
        if not isinstance(number, int) or not 0 <= number < page_count:
            raise EditError("An edit refers to an invalid page.")
        result[number].append(edit)
    return result


def describe_upload(token, entry):
    """What the browser needs to know about an uploaded file."""
    info = {"id": token, "name": entry["name"], "size": entry["size"], "kind": "other"}
    with open(entry["path"], "rb") as handle:
        head = handle.read(2048)
    suffix = Path(entry["name"]).suffix.lower()
    if b"%PDF-" in head[:1024]:
        info["kind"] = "pdf"
        try:
            with pdf.open(entry["path"]) as doc:
                if doc.needs_pass and not (entry["password"] and doc.authenticate(entry["password"])):
                    info["encrypted"] = True
                else:
                    info["pages"] = doc.page_count
                    info["sizes"] = [[round(p.rect.width, 2), round(p.rect.height, 2)] for p in list(doc)[:3000]]
        except (pdf.FileDataError, pdf.EmptyFileError, RuntimeError, ValueError):
            info["damaged"] = True
    elif head.startswith(IMAGE_MAGIC) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        info["kind"] = "image"
    elif suffix in (".docx", ".docm", ".doc", ".odt", ".rtf", ".txt", ".xlsx", ".xlsm", ".xls", ".ods", ".csv",
                    ".pptx", ".pptm", ".ppt", ".odp"):
        info["kind"] = "office"
    elif suffix in (".html", ".htm"):
        info["kind"] = "html"
    return info


def discard(token):
    entry = UPLOADS.pop(token, None) if isinstance(token, str) else None
    if entry:
        entry["path"].unlink(missing_ok=True)
        if entry.get("preview_path"):
            entry["preview_path"].unlink(missing_ok=True)


def forget_old_uploads():
    now = time.time()
    for token, entry in list(UPLOADS.items()):
        if now - entry["time"] > UPLOAD_LIFETIME:
            discard(token)


def option_passwords(value, key=""):
    """Passwords typed in a tool's options (e.g. Protect's), so its result can be previewed."""
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in option_passwords(v, str(k))]
    if isinstance(value, list):
        return [p for v in value for p in option_passwords(v, key)]
    return [value] if isinstance(value, str) and value and "password" in key.lower() else []


def keep_file(name, data, passwords=()):
    """Store a produced file privately so the browser can preview it before downloading it."""
    forget_old_uploads()
    token = secrets.token_urlsafe(18)
    path = UPLOAD_DIR / token
    path.write_bytes(data)
    entry = {"path": path, "name": name, "size": len(data), "password": "", "time": time.time()}
    if b"%PDF-" in data[:1024] and passwords:
        try:
            with pdf.open(path, filetype="pdf") as doc:
                if doc.needs_pass:
                    entry["password"] = next((p for p in passwords if doc.authenticate(p)), "")
        except (pdf.FileDataError, pdf.EmptyFileError, RuntimeError, ValueError):
            pass
    UPLOADS[token] = entry
    return token


def preview_document(entry):
    """A document showing a stored file: the PDF itself, an image, or an Office file
    converted to PDF once (by LibreOffice when installed, otherwise the built-in reader)."""
    suffix = Path(entry["name"]).suffix.lower()
    if suffix in PREVIEW_OFFICE:
        if not entry.get("preview_path"):
            item = ToolInput(entry["name"], path=entry["path"])
            office = libreoffice()
            data = with_libreoffice(item, office) if office else None
            note = "Shown as LibreOffice displays this file. Word, Excel or PowerPoint may show small differences."
            if not data and suffix in OFFICE_READERS:
                try:
                    data = OFFICE_READERS[suffix](item.data)
                except (ValueError, KeyError, IndexError, RuntimeError):
                    data = None
                note = ("Approximate preview drawn by PageBurrow. Word, Excel or PowerPoint show the exact layout; "
                        "install LibreOffice (free) for a more exact preview.")
            if not data:
                raise EditError("This file cannot be previewed here. Download it and open it in its app.")
            entry["preview_path"] = entry["path"].with_name(entry["path"].name + "-preview")
            entry["preview_path"].write_bytes(data)
            entry["preview_note"] = note
        return pdf.open(entry["preview_path"], filetype="pdf")
    if suffix in PREVIEW_IMAGES:
        return pdf.open(entry["path"], filetype=suffix.lstrip("."))
    doc = pdf.open(entry["path"], filetype="pdf")
    if doc.is_encrypted and entry["password"]:
        doc.authenticate(entry["password"])
    return doc


def compress_options(query):
    """Target size in bytes, fit-to-A4 and allow-JPEG from the compress request."""
    options = parse_qs(query)
    size = options.get("target", [""])[0]
    page = options.get("page", [""])[0]
    mode = options.get("mode", [""])[0]
    if not re.fullmatch(r"\d{1,3}(\.\d{1,3})?", size) or not Decimal("0.01") <= Decimal(size) <= 200:
        raise EditError("Enter a maximum size between 0.01 and 200 MB.")
    if page not in ("a4", "original") or mode not in ("lossless", "jpeg"):
        raise EditError("Choose a valid page size and compression mode.")
    return int(Decimal(size) * 1_000_000), page == "a4", mode == "jpeg"


class Request(BaseHTTPRequestHandler):
    timeout = 10
    content_security_policy = (
        "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
    )

    def send(self, data, content_type, code=200, headers=(), referrer="no-referrer"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if not any(name.lower() == "cache-control" for name, _ in headers):
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", referrer)
        self.send_header("Content-Security-Policy", self.content_security_policy)
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def json(self, data, code=200):
        self.send(json.dumps(data).encode(), "application/json", code)

    def session(self):
        token = self.headers.get("X-Document", "")
        if token not in FILES:
            raise EditError("Open the PDF again to start a new session.")
        FILES.move_to_end(token)
        return FILES[token]

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    # ---- access control ----

    def host_allowed(self, host):
        if host == f"127.0.0.1:{self.server.server_port}":
            return True
        if not self.server.lan:
            return False
        # Phones reach the tool by IP address. A host name could be pointed at this
        # device by another website (DNS rebinding), so only IP addresses are accepted.
        name, _, port = host.rpartition(":")
        if port != str(self.server.server_port):
            return False
        try:
            ipaddress.ip_address(name.strip("[]"))
        except ValueError:
            return False
        return True

    def is_remote(self):
        try:
            return not ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return True

    def paired(self):
        try:
            morsel = SimpleCookie(self.headers.get("Cookie", "")).get(COOKIE)
        except CookieError:
            return False
        return bool(morsel and self.server.secret) and secrets.compare_digest(
            morsel.value.encode(), self.server.secret.encode())

    def pair_page(self, message="", code=200):
        notice = f'<p class="error" role="alert">{escape(message)}</p>' if message else ""
        # With "no-referrer", browsers send "Origin: null" for the PIN form, which the
        # cross-site check would refuse. "same-origin" still sends nothing to other sites.
        self.send(PAIR_PAGE.format(message=notice).encode(), "text/html; charset=utf-8", code, referrer="same-origin")

    def pair(self):
        server = self.server
        length = min(int(self.headers.get("Content-Length") or 0), 1024)
        pin = parse_qs(self.rfile.read(length).decode("utf-8", "replace")).get("pin", [""])[0].strip()
        if server.failures >= MAX_PIN_FAILURES:
            self.pair_page("Too many wrong PINs. Restart PageBurrow on the computer to pair this device.", 429)
        elif server.pin and server.secret and secrets.compare_digest(pin.encode(), server.pin.encode()):
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"{COOKIE}={server.secret}; Max-Age=15552000; Path=/; HttpOnly; SameSite=Lax")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            print(f"Paired a device at {self.client_address[0]}.", flush=True)
        else:
            server.failures += 1
            if server.failures >= MAX_PIN_FAILURES:
                print("Phone pairing is locked after too many wrong PINs. Restart to pair a device.", flush=True)
            self.pair_page("That PIN is not correct. Check the PIN shown on the computer.", 401)

    def dispatch(self, post):
        host = self.headers.get("Host", "")
        if not self.host_allowed(host):
            self.json({"error": "Use the address shown in the PageBurrow window."}, 403)
            return
        origin = "http://" + host
        if self.headers.get("Origin", origin) != origin:
            self.json({"error": "Open PageBurrow in its own browser tab."}, 403)
            return
        path = urlsplit(self.path).path
        if not post and path in PUBLIC:
            name, content_type = PUBLIC[path]
            self.send((ROOT / "web" / name).read_bytes(), content_type)
            return
        if self.is_remote() and not self.paired():
            if post and path == "/pair":
                self.pair()
            elif not post and path == "/":
                self.pair_page()
            else:
                self.json({"error": "Enter the PIN on this device first."}, 403)
            return
        if post and self.headers.get("X-Local-Editor") != "1":
            self.json({"error": "Open PageBurrow in its own browser tab."}, 403)
            return
        try:
            if not post and path in STATIC:
                name, content_type = STATIC[path]
                self.send((ROOT / "web" / name).read_bytes(), content_type)
            elif post:
                self.post(path)
            else:
                self.json({"error": "Page not found."}, 404)
        except (ConnectionResetError, BrokenPipeError):
            return
        except EditError as error:
            self.json({"error": str(error)}, 422)
        except (pdf.FileDataError, pdf.EmptyFileError):
            self.json({"error": "This file could not be opened as a PDF or image."}, 422)
        except (ValueError, KeyError, TypeError, RuntimeError, IndexError, OverflowError) as error:
            self.log_error("%s", error)
            self.json({"error": "The PDF operation could not be completed. Check the file and your selection."}, 422)

    # ---- API ----

    def compress(self, data, query, before=None):
        """Compress and send the PDF. With `before` (a function returning the stored token of
        the uncompressed PDF), the result is also kept so it can be previewed and compared."""
        target, a4, jpeg = compress_options(query)
        try:
            from compressor import compress_pdf
        except ImportError:
            raise EditError("Compression needs the Pillow package. Start PageBurrow with its launcher to install it.") from None
        if b"%PDF-" not in data[:1024]:
            raise EditError("The file is not a complete PDF.")
        try:
            result = compress_pdf(data, target, a4, jpeg)
        except (pdf.FileDataError, pdf.EmptyFileError):
            raise EditError("The PDF could not be opened. Check whether it opens in a PDF viewer.") from None
        except ValueError as error:
            raise EditError(str(error)) from None
        except (RuntimeError, OSError, MemoryError) as error:
            self.log_error("PDF compression failed (%s)", type(error).__name__)
            raise EditError("This PDF could not be compressed. Try Original page size and Lossless.") from None
        headers = [("X-PDF-Pages", str(result.pages)),
                   ("X-Compression", "lossless" if result.jpeg_quality is None else "jpeg")]
        if before:
            headers += [("X-Preview-Id", keep_file("compressed.pdf", result.data)), ("X-Before-Id", before())]
        self.send(result.data, "application/pdf", headers=headers)

    # ---- PDF tools (merge, split, convert, ...) ----

    def receive_upload(self):
        """Stream a file to the private temporary folder (it may be large)."""
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= MAX_UPLOAD:
            raise EditError("Choose a file that is not empty and no larger than 2 GB.")
        name = Path(unquote(self.headers.get("X-File-Name", "file"))).name[:200] or "file"
        forget_old_uploads()
        token = secrets.token_urlsafe(18)
        path = UPLOAD_DIR / token
        remaining = size
        with open(path, "wb") as out:
            while remaining:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
        if remaining:
            path.unlink(missing_ok=True)
            raise EditError("The upload was interrupted. Choose the file again.")
        UPLOADS[token] = {"path": path, "name": name, "size": size, "password": "", "time": time.time()}
        self.json(describe_upload(token, UPLOADS[token]))

    def upload(self, token):
        entry = UPLOADS.get(token) if isinstance(token, str) else None
        if entry is None:
            raise EditError("A file is no longer available. Add it again.")
        entry["time"] = time.time()
        return entry

    def preview_info(self, entry):
        """How a stored file can be previewed: its pages, its text, or not at all."""
        name = entry["name"]
        if Path(name).suffix.lower() in PREVIEW_TEXT:
            with open(entry["path"], "rb") as handle:
                raw = handle.read(PREVIEW_TEXT_LIMIT * 4)
            text = raw.decode("utf-8", "replace")
            cut = entry["size"] > len(raw) or len(text) > PREVIEW_TEXT_LIMIT
            self.json({"kind": "text", "name": name, "text": text[:PREVIEW_TEXT_LIMIT], "cut": cut})
            return
        try:
            doc = preview_document(entry)
        except (pdf.FileDataError, pdf.EmptyFileError, RuntimeError, ValueError):
            self.json({"kind": "none", "name": name, "note": "This file cannot be previewed. Download it to open it."})
            return
        with doc:
            if doc.is_encrypted:  # still locked: the password is not known (or not correct)
                self.json({"kind": "locked", "name": name})
                return
            sizes = [[round(doc[i].rect.width, 2), round(doc[i].rect.height, 2)] for i in range(min(doc.page_count, 3000))]
            self.json({"kind": "pages", "name": name, "pages": doc.page_count, "sizes": sizes,
                       "note": entry.get("preview_note", "")})

    def original(self, session):
        """Stored copy of the open document as it was opened, to compare the result with."""
        token = self.headers.get("X-Document", "")
        kept = ORIGINALS.get(token)
        if kept not in UPLOADS:
            kept = ORIGINALS[token] = keep_file("original.pdf", session[0], [session[1]] if session[1] else [])
        UPLOADS[kept]["time"] = time.time()
        return kept

    def tool_request(self, path, payload):
        if path == "/api/tools-info":
            info = pdftools.capabilities()
            info["max_upload"] = MAX_UPLOAD
            self.json(info)
        elif path == "/api/upload-password":
            token = payload.get("id")
            entry = self.upload(token)
            with pdf.open(entry["path"]) as doc:
                if not doc.authenticate(str(payload.get("password", ""))):
                    raise EditError("That password is not correct.")
            entry["password"] = str(payload.get("password", ""))
            self.json(describe_upload(token, entry))
        elif path == "/api/preview":
            entry = self.upload(payload.get("id"))
            with preview_document(entry) as doc:
                if doc.is_encrypted:
                    raise EditError("Enter the password of this PDF to preview it.")
                number = payload.get("page", 0)
                if not isinstance(number, int) or not 0 <= number < doc.page_count:
                    raise EditError("Choose a valid page number.")
                page = doc[number]
                width = max(40, min(int(payload.get("width", 200)), 2400))
                zoom = min(6.0, width / page.rect.width)
                self.send(page.get_pixmap(matrix=pdf.Matrix(zoom, zoom), alpha=False).tobytes("png"), "image/png")
        elif path == "/api/preview-info":
            self.preview_info(self.upload(payload.get("id")))
        elif path == "/api/forget":
            for token in payload.get("ids") or []:
                discard(token)
            self.json({})
        elif path == "/api/ocr-language":
            pdftools.ocr.download(str(payload.get("code", "")))
            self.json(pdftools.capabilities())
        else:  # /api/tool
            name = payload.get("tool")
            files = [ToolInput(e["name"], path=e["path"], password=e["password"])
                     for e in (self.upload(t) for t in payload.get("files") or [])]
            result = pdftools.run(name, files, payload.get("options") or {})
            meta = {"message": result.message, "notes": result.notes, "data": result.data}
            if not result.files:
                self.json(meta)
                return
            # Produced files are also kept for a while, so they can be previewed before downloading.
            # (Only id, name and size travel in the header; the preview asks for the rest.)
            passwords = [f.password for f in files if f.password] + option_passwords(payload.get("options"))
            kept = [keep_file(n, d, passwords) for n, d in result.files[:PREVIEW_FILES]]
            meta["files"] = [{"id": t, "name": UPLOADS[t]["name"], "size": UPLOADS[t]["size"]} for t in kept]
            meta["file_count"] = len(result.files)
            if len(result.files) == 1:
                file_name, data = result.files[0]
            else:
                stem = Path(files[0].name).stem if files else str(name)
                file_name, data = f"{stem}_{name}.zip", zip_files(result.files)
                meta["names"] = [n for n, _ in result.files]
            meta["name"] = file_name
            header = base64.b64encode(json.dumps(meta).encode()).decode("ascii")
            self.send(data, MIME.get(Path(file_name).suffix.lower(), "application/octet-stream"),
                      headers=(("X-Tool-Result", header),))

    def post(self, path):
        if path == "/api/upload":
            self.receive_upload()
            return
        size = int(self.headers.get("Content-Length", "0"))
        limit, label = {"/api/open": (MAX_PDF, "160 MB"), "/api/image": (MAX_IMAGE, "12 MB"),
                        "/api/compress": (MAX_COMPRESS, "200 MB"), "/api/tool": (64 * 1024 * 1024, "64 MB")
                        }.get(path, (8 * 1024 * 1024, "8 MB"))
        if size < 0 or size > limit:
            raise EditError(f"This operation accepts up to {label}.")
        body = self.rfile.read(size)
        query = urlsplit(self.path).query
        if path in ("/api/tool", "/api/tools-info", "/api/upload-password", "/api/preview", "/api/preview-info",
                    "/api/forget", "/api/ocr-language"):
            payload = json.loads(body or b"{}")
            if not isinstance(payload, dict):
                raise EditError("The request is not valid.")
            self.tool_request(path, payload)
            return
        if path == "/api/status":
            lan = None
            if self.server.lan and not self.is_remote():
                lan = {"urls": [f"http://{ip}:{self.server.server_port}" for ip in self.server.addresses],
                       "pin": self.server.pin}
            self.json({"lan": lan, "compress": importlib.util.find_spec("PIL") is not None})
            return
        if path == "/api/compress" and self.headers.get_content_type() == "application/pdf":
            self.compress(body, query)  # a PDF chosen on the Compress screen
            return
        if path == "/api/open":
            session = (body, unquote(self.headers.get("X-PDF-Password", "")), {})
            with document(session) as doc:
                if not doc.is_pdf or not doc.page_count:
                    raise EditError("Choose a PDF with at least one page.")
                signature = doc.get_sigflags() > 0
                count = doc.page_count
            old = self.headers.get("X-Document")
            FILES.pop(old, None)
            discard(ORIGINALS.pop(old, None))
            token = secrets.token_urlsafe(24)
            FILES[token] = session
            while len(FILES) > 6 or sum(len(session[0]) for session in FILES.values()) > 320 * 1024 * 1024:
                evicted, _ = FILES.popitem(last=False)
                discard(ORIGINALS.pop(evicted, None))
            self.json({"token": token, "count": count, "signature": signature})
            return
        if path == "/api/close":
            token = self.headers.get("X-Document")
            FILES.pop(token, None)
            discard(ORIGINALS.pop(token, None))
            self.json({})
            return
        session = self.session()
        if path == "/api/image":
            if not (body.startswith(b"\x89PNG\r\n\x1a\n") or body.startswith(b"\xff\xd8\xff")):
                raise EditError("Choose a PNG or JPEG image.")
            assets = session[2]
            if sum(map(len, assets.values())) + size > 48 * 1024 * 1024:
                raise EditError("Images are limited to 48 MB per session.")
            token = secrets.token_urlsafe(12)
            assets[token] = body
            self.json({"asset": token})
            return
        payload = json.loads(body)
        with document(session) as doc:
            if path == "/api/render":
                number = payload["page"]
                if not isinstance(number, int) or not 0 <= number < doc.page_count:
                    raise EditError("Choose a valid page number.")
                page = doc[number]
                width, height = page.rect.width, page.rect.height
                if payload.get("thumbnail"):
                    pix = page.get_pixmap(matrix=pdf.Matrix(144 / max(width, height), 144 / max(width, height)))
                    self.send(pix.tobytes("png"), "image/png")
                    return
                edits = edits_by_page(payload.get("edits", []), doc.page_count)
                spans = inspect_page(page) if payload.get("inspect", True) else {}
                hide = payload.get("hide")
                # The selected object is drawn by the browser while it is moved or resized.
                hidden = {hide} if isinstance(hide, int) and not isinstance(hide, bool) else set()
                objects = {}
                if edits[number]:
                    notes = apply_page(doc, number, edits[number], session[2], hidden, objects)
                    page = doc[number]
                else:
                    notes = {}
                scale = min(2.25, 2300 / max(width, height))
                pix = page.get_pixmap(matrix=pdf.Matrix(scale, scale))
                public = {k: {field: item[field] for field in ("box", "editable", "font", "size", "text", "color")}
                          for k, item in spans.items()}
                # PNG encoding of a full-page scan takes ~0.5 s and several MB; JPEG keeps
                # previews fast while text is moved. Only the preview is affected.
                fmt = "jpeg" if scanned(page) else "png"
                raster = pix.tobytes("jpeg", jpg_quality=90) if fmt == "jpeg" else pix.tobytes("png")
                self.json({"width": width, "height": height, "spans": public, "notes": notes,
                           "objects": objects, "format": fmt,
                           "raster": base64.b64encode(raster).decode("ascii")})
            elif path == "/api/clip":
                # Lossless image of an area of the original page, for the eraser. The
                # area maps exactly onto whole pixels so the patch lines up when inserted.
                number = payload["page"]
                if not isinstance(number, int) or not 0 <= number < doc.page_count:
                    raise EditError("Choose a valid page number.")
                page = doc[number]
                values = payload["rect"]
                if not isinstance(values, list) or len(values) != 4:
                    raise EditError("Choose an area on the page.")
                rect = pdf.Rect(point(values[:2], page.rect), point(values[2:], page.rect)).normalize()
                if min(rect.width, rect.height) < 2:
                    raise EditError("Drag to select a larger area.")
                zoom = clip_zoom(page, rect)
                width, height = max(1, round(rect.width * zoom)), max(1, round(rect.height * zoom))
                sx, sy = width / rect.width, height / rect.height
                pix = page.get_pixmap(matrix=pdf.Matrix(sx, 0, 0, sy, -rect.x0 * sx, -rect.y0 * sy), clip=rect)
                self.send(pix.tobytes("png"), "image/png")
            elif path in ("/api/export", "/api/compress"):
                edits = edits_by_page(payload["edits"], doc.page_count)
                for number, changes in edits.items():
                    apply_page(doc, number, changes, session[2])
                data = doc.tobytes(garbage=4, deflate=True, encryption=pdf.PDF_ENCRYPT_KEEP) if edits else session[0]
                # X-Preview: also keep the result (and the PDF before this step) for the preview.
                preview = self.headers.get("X-Preview") == "1"
                passwords = [session[1]] if session[1] else []
                if path == "/api/compress":  # the open document, with its edits
                    before = (lambda: keep_file("edited.pdf", data, passwords)) if edits else (lambda: self.original(session))
                    self.compress(data, query, before if preview else None)
                else:
                    headers = ()
                    if preview:
                        headers = (("X-Preview-Id", keep_file("edited.pdf", data, passwords)),
                                   ("X-Before-Id", self.original(session)))
                    self.send(data, "application/pdf", headers=headers)
            else:
                self.json({"error": "Page not found."}, 404)


class Server(HTTPServer):
    # On Windows, SO_REUSEADDR lets a second program take a port that is already in
    # use; ask for exclusive use instead so a second copy falls back to another port.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def lan_addresses():
    """IPv4 addresses other devices on the network can use to reach this one."""
    found = []
    for target in ("192.168.0.1", "10.0.0.1", "8.8.8.8"):
        try:  # connecting a UDP socket picks the outgoing interface; nothing is sent
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect((target, 9))
                found.append(probe.getsockname()[0])
        except OSError:
            pass
    try:
        found += [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    return [ip for ip in dict.fromkeys(found) if not ip.startswith(("127.", "169.254.", "0."))]


def access_secret():
    """Secret stored in paired devices' cookies; kept so devices stay paired across restarts."""
    try:
        value = KEY_FILE.read_text(encoding="ascii").strip()
        if len(value) >= 32:
            return value
    except (OSError, UnicodeDecodeError):
        pass
    value = secrets.token_urlsafe(32)
    try:
        KEY_FILE.write_text(value, encoding="ascii")
        if os.name != "nt":
            KEY_FILE.chmod(0o600)
    except OSError:
        pass  # read-only folder: devices stay paired until the tool stops
    return value


def open_browser(url):
    if shutil.which("termux-open-url"):  # Android (Termux)
        subprocess.Popen(["termux-open-url", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    try:
        webbrowser.open(url)
    except webbrowser.Error:
        pass


def main():
    parser = argparse.ArgumentParser(description="PageBurrow: every PDF tool, on your own device.")
    parser.add_argument("--lan", action="store_true",
                        help="let phones and tablets on the same network connect (they need the PIN shown here)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to use (default {DEFAULT_PORT})")
    parser.add_argument("--host", help="address to listen on (default 127.0.0.1, or 0.0.0.0 with --lan)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    args = parser.parse_args()
    host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")
    try:
        local_only = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local_only = False
    args.lan = args.lan or not local_only  # anything reachable from the network needs the PIN
    try:
        server = Server((host, args.port), Request)
    except OSError:
        server = Server((host, 0), Request)  # the usual port is taken, e.g. by another copy
    with server:
        port = server.server_port
        server.lan = args.lan
        server.pin = f"{secrets.randbelow(10 ** 6):06d}" if args.lan else ""
        server.secret = access_secret() if args.lan else ""
        server.failures = 0
        server.addresses = lan_addresses() if args.lan else []
        url = f"http://127.0.0.1:{port}"
        print(f"PageBurrow is running at {url}", flush=True)
        print("Keep this window open while you work. Close it or press Ctrl+C to stop.", flush=True)
        if args.lan:
            print("\nPhone and tablet access is ON.")
            if server.addresses:
                print("On a phone or tablet on the same Wi-Fi, open:")
                for ip in server.addresses:
                    print(f"    http://{ip}:{port}")
            else:
                print("No network address was found. Connect this device to Wi-Fi and restart.")
            print(f"and enter PIN {server.pin}. Paired devices stay paired for 180 days.")
            print("Files travel unencrypted over your network, so use this only on a network you trust.")
            if os.name == "nt":
                print("If Windows asks, allow Python to communicate on private networks.")
            print(flush=True)
        if not args.no_browser:
            open_browser(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
