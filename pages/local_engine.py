"""Use PageBurrow's existing tool handlers inside the browser's Python worker."""
from email.message import Message
from io import BytesIO
import json
from types import SimpleNamespace
from urllib.parse import urlsplit
import app
from pathlib import Path
from js import pageBurrowOcr

# The browser PyMuPDF wheel omits Tesseract and Pillow's optional ICC module.
# Adapt the two primitives so the original OCR, redaction and PDF/A tools work.
def ocr_bytes(pix, compress=True, language="eng", tessdata=None):
    result = pageBurrowOcr(pix.tobytes("png"), language, pix.xres)
    return bytes(result.to_py())

app.pdf.Pixmap.pdfocr_tobytes = ocr_bytes
app.pdftools.optimize.srgb_profile = lambda: Path("/pageburrow/srgb.icc").read_bytes()

app.MAX_PDF = app.MAX_UPLOAD = app.MAX_COMPRESS = 200_000_000


class BrowserRequest(app.Request):
    def __init__(self, path, headers, body):
        self.path = path
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key] = value
        self.headers["Content-Length"] = str(len(body))
        self.rfile = BytesIO(body)
        self.server = SimpleNamespace(lan=False)

    def send(self, data, content_type, code=200, headers=(), referrer=None):
        self.response = [code, dict(headers, **{"Content-Type": content_type}), data]

    def log_message(self, *args):
        pass


def dispatch(path, header_json, body):
    request = BrowserRequest(path, json.loads(header_json), body.to_py())
    try:
        request.post(urlsplit(path).path)
    except Exception as error:
        request.json({"error": str(error) or "This document could not be processed on this device."}, 422)
    return request.response
