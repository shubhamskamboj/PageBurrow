"""Print web pages to PDF with the Edge, Chrome or Chromium already on the computer.

The browser runs headless and is driven through the Chrome DevTools protocol, so paper
size, orientation, margins and backgrounds can be set. Nothing is installed.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

from .common import ToolError


def find():
    candidates = []
    if os.name == "nt":
        for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
            if base:
                candidates += [Path(base, "Microsoft/Edge/Application/msedge.exe"),
                               Path(base, "Google/Chrome/Application/chrome.exe"),
                               Path(base, "Chromium/Application/chrome.exe"),
                               Path(base, "BraveSoftware/Brave-Browser/Application/brave.exe")]
    elif sys.platform == "darwin":
        for name in ("Google Chrome", "Microsoft Edge", "Chromium", "Brave Browser"):
            candidates.append(Path(f"/Applications/{name}.app/Contents/MacOS/{name}"))
            candidates.append(Path.home() / f"Applications/{name}.app/Contents/MacOS/{name}")
    for path in candidates:
        if path.is_file():
            return str(path)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
                 "microsoft-edge-stable", "brave-browser", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


class WebSocket:
    """Just enough of RFC 6455 for the DevTools protocol (text frames, client masking)."""

    def __init__(self, url, timeout):
        parts = urllib.parse.urlsplit(url)
        self.sock = socket.create_connection((parts.hostname, parts.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {parts.path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("browser closed the connection")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("browser refused the connection")
        self.buffer = bytearray(head.split(b"\r\n\r\n", 1)[1])

    def _read(self, size):
        while len(self.buffer) < size:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError("browser closed the connection")
            self.buffer += chunk
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    def send(self, text, opcode=0x1):
        data = text.encode() if isinstance(text, str) else text
        header = bytearray([0x80 | opcode])
        size = len(data)
        if size < 126:
            header.append(0x80 | size)
        elif size < 65536:
            header.append(0x80 | 126)
            header += size.to_bytes(2, "big")
        else:
            header.append(0x80 | 127)
            header += size.to_bytes(8, "big")
        mask = os.urandom(4)
        header += mask
        if size:
            key = (mask * (size // 4 + 1))[:size]
            data = (int.from_bytes(data, "big") ^ int.from_bytes(key, "big")).to_bytes(size, "big")
        self.sock.sendall(bytes(header) + data)

    def receive(self):
        message = bytearray()
        while True:
            first, second = self._read(2)
            opcode, size = first & 0x0F, second & 0x7F
            if size == 126:
                size = int.from_bytes(self._read(2), "big")
            elif size == 127:
                size = int.from_bytes(self._read(8), "big")
            mask = self._read(4) if second & 0x80 else None
            payload = self._read(size)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x9:
                self.send(payload, 0xA)
                continue
            if opcode == 0x8:
                raise ConnectionError("browser closed the connection")
            message += payload
            if first & 0x80:
                return message.decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Browser:
    def __init__(self, executable, timeout=90):
        self.folder = tempfile.mkdtemp(prefix="pdftools-browser-")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.process = subprocess.Popen(
            [executable, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--disable-sync", "--mute-audio", "--hide-scrollbars",
             f"--remote-debugging-port={port}", f"--user-data-dir={self.folder}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 30
        while True:
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2))
                pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    break
            except (OSError, ValueError):
                pass
            if time.time() > deadline or self.process.poll() is not None:
                self.close()
                raise ToolError("The browser on this computer could not be started to print the page.")
            time.sleep(0.2)
        self.socket = WebSocket(pages[0]["webSocketDebuggerUrl"], timeout)
        self.counter, self.events, self.timeout = 0, [], timeout

    def call(self, method, params=None):
        self.counter += 1
        ident = self.counter
        self.socket.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.socket.receive())
            if message.get("id") == ident:
                if "error" in message:
                    raise ToolError(f"The browser could not do this: {message['error'].get('message', 'unknown error')}.")
                return message.get("result", {})
            if "method" in message:
                self.events.append(message)

    def wait(self, event, seconds):
        deadline = time.time() + seconds
        while True:
            for i, message in enumerate(self.events):
                if message["method"] == event:
                    return self.events.pop(i)
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            self.socket.sock.settimeout(remaining)
            try:
                message = json.loads(self.socket.receive())
            except (socket.timeout, TimeoutError):
                return None
            finally:
                self.socket.sock.settimeout(self.timeout)
            if "method" in message:
                self.events.append(message)

    def close(self):
        if getattr(self, "socket", None):
            try:
                self.socket.send(json.dumps({"id": 0, "method": "Browser.close"}))
            except OSError:
                pass
            self.socket.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        for _ in range(10):  # Windows keeps files locked for a moment
            shutil.rmtree(self.folder, ignore_errors=True)
            if not os.path.exists(self.folder):
                break
            time.sleep(0.3)


PAPER = {"a4": (8.27, 11.69), "letter": (8.5, 11.0), "legal": (8.5, 14.0), "a3": (11.69, 16.54)}


def print_to_pdf(executable, url=None, html=None, paper="a4", landscape=False, margin=0.4, background=True):
    browser = Browser(executable)
    try:
        browser.call("Page.enable")
        if url:
            result = browser.call("Page.navigate", {"url": url})
            if result.get("errorText"):
                raise ToolError(f"The page could not be opened ({result['errorText']}). Check the address and the connection.")
            browser.wait("Page.loadEventFired", 60)
            # Scroll through the page so images that load on scroll appear in the PDF.
            browser.call("Runtime.evaluate", {"awaitPromise": True, "expression": (
                "new Promise(done => { let y = 0; const step = () => { window.scrollTo(0, y += innerHeight);"
                " if (y < document.body.scrollHeight && y < 60000) setTimeout(step, 120); else { window.scrollTo(0, 0); setTimeout(done, 400); } };"
                " step(); })")})
        else:
            browser.call("Page.navigate", {"url": "about:blank"})
            browser.wait("Page.loadEventFired", 10)
            frame = browser.call("Page.getFrameTree")["frameTree"]["frame"]["id"]
            browser.call("Page.setDocumentContent", {"frameId": frame, "html": html})
            time.sleep(0.6)
        width, height = PAPER.get(paper, PAPER["a4"])
        result = browser.call("Page.printToPDF", {"paperWidth": width, "paperHeight": height, "landscape": landscape,
                                                  "marginTop": margin, "marginBottom": margin, "marginLeft": margin,
                                                  "marginRight": margin, "printBackground": background,
                                                  "preferCSSPageSize": False})
        return base64.b64decode(result["data"])
    finally:
        browser.close()
