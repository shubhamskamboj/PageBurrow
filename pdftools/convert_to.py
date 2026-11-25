"""Convert to PDF: images, Word, PowerPoint, Excel and web pages."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

import pymupdf as pdf

from . import browser, ooxml
from .common import Result, ToolError, save
from .organize import IMAGE_TYPES, image_page
from .registry import tool


@tool("images_to_pdf")
def images_to_pdf(files, opt):
    images = [f for f in files if f.suffix in IMAGE_TYPES]
    if not images:
        raise ToolError("Choose JPG, PNG, GIF, BMP, TIFF or WEBP images.")
    page_size = opt.choice("page", ("fit", "a4", "letter"), "a4")
    orientation = opt.choice("orientation", ("auto", "portrait", "landscape"), "auto")
    margin = {"none": 0, "small": 18, "big": 40}[opt.choice("margin", ("none", "small", "big"), "none")]
    if opt.flag("separate"):
        out = []
        for item in images:
            doc = pdf.open()
            image_page(doc, item.data, page_size, orientation, margin)
            out.append((item.stem + ".pdf", save(doc)))
        return Result(out, f"Created {len(out)} PDF files.")
    doc = pdf.open()
    for item in images:
        image_page(doc, item.data, page_size, orientation, margin)
    return Result([(images[0].stem + ("_images" if len(images) > 1 else "") + ".pdf", save(doc))],
                  f"Created a PDF with {doc.page_count} page(s).")


def libreoffice():
    candidates = [shutil.which("soffice"), shutil.which("libreoffice")]
    if os.name == "nt":
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")):
            if base:
                candidates.append(str(Path(base, "LibreOffice/program/soffice.exe")))
    else:
        candidates += ["/Applications/LibreOffice.app/Contents/MacOS/soffice", "/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice",
                       "/opt/libreoffice/program/soffice", "/snap/bin/libreoffice"]
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def with_libreoffice(item, executable):
    with tempfile.TemporaryDirectory(prefix="pdftools-office-") as folder:
        source = Path(folder, "input" + item.suffix)
        source.write_bytes(item.data)
        profile = Path(folder, "profile").as_uri()
        try:
            subprocess.run([executable, "--headless", "--norestore", "--nolockcheck", f"-env:UserInstallation={profile}",
                            "--convert-to", "pdf", "--outdir", folder, str(source)],
                           capture_output=True, timeout=300, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        result = Path(folder, "input.pdf")
        return result.read_bytes() if result.exists() else None


BUILT_IN = {".docx": ooxml.docx_to_pdf, ".docm": ooxml.docx_to_pdf, ".xlsx": ooxml.xlsx_to_pdf, ".xlsm": ooxml.xlsx_to_pdf,
            ".pptx": ooxml.pptx_to_pdf, ".pptm": ooxml.pptx_to_pdf}
KINDS = {"word": (".docx", ".docm", ".doc", ".odt", ".rtf", ".txt"), "powerpoint": (".pptx", ".pptm", ".ppt", ".odp"),
         "excel": (".xlsx", ".xlsm", ".xls", ".ods", ".csv")}


def office_to_pdf(files, opt, kind):
    accepted = KINDS[kind]
    items = [f for f in files if f.suffix in accepted]
    if not items:
        raise ToolError(f"Choose {', '.join(accepted[:3])} files.")
    engine = opt.choice("engine", ("auto", "builtin"), "auto")
    office = libreoffice() if engine == "auto" else None
    out, notes, used = [], [], set()
    for item in items:
        data = with_libreoffice(item, office) if office else None
        if data:
            used.add("LibreOffice")
        else:
            if item.suffix == ".txt":
                text = item.data.decode("utf-8", "replace")
                data = ooxml.render_html([f"<body><pre style='white-space:pre-wrap;font-family:monospace;font-size:10pt'>"
                                          f"{ooxml.escape(text)}</pre></body>"], 595, 842, (54, 54, 54, 54))
            elif item.suffix == ".csv":
                import csv
                import io
                rows = list(csv.reader(io.StringIO(item.data.decode("utf-8-sig", "replace"))))
                book = ooxml.Xlsx()
                book.sheet(item.stem, rows, header=True)
                data = ooxml.xlsx_to_pdf(book.build())
            elif item.suffix in BUILT_IN:
                try:
                    data = BUILT_IN[item.suffix](item.data)
                except (ValueError, KeyError, IndexError, RuntimeError) as error:
                    raise ToolError(f"{item.name} could not be converted ({error}). Install LibreOffice for full support.") from None
            else:
                raise ToolError(f"{item.name}: older {item.suffix} files need LibreOffice (free) installed on this computer, "
                                f"or save the file as {accepted[0]} first.")
            used.add("built-in converter")
        out.append((item.stem + ".pdf", data))
    if "built-in converter" in used:
        notes.append("Converted with the built-in converter, which keeps text, fonts, tables and pictures but simplifies "
                     "complex layouts. Install LibreOffice (free) for exact layout; it is then used automatically.")
    return Result(out, f"Converted {len(out)} file(s) with {' and '.join(sorted(used))}.", notes)


@tool("word_to_pdf")
def word_to_pdf(files, opt):
    return office_to_pdf(files, opt, "word")


@tool("powerpoint_to_pdf")
def powerpoint_to_pdf(files, opt):
    return office_to_pdf(files, opt, "powerpoint")


@tool("excel_to_pdf")
def excel_to_pdf(files, opt):
    return office_to_pdf(files, opt, "excel")


@tool("html_to_pdf")
def html_to_pdf(files, opt):
    url = opt.text("url", "", 4000).strip()
    pages = [f for f in files if f.suffix in (".html", ".htm")]
    if not url and not pages:
        raise ToolError("Enter a web address or choose an .html file.")
    if url:
        if not re.match(r"^https?://", url, re.IGNORECASE):
            url = "https://" + url if "://" not in url else url
        if not re.match(r"^https?://[^\s/]+", url, re.IGNORECASE):
            raise ToolError("Enter a web address that starts with http:// or https://.")
    paper = opt.choice("paper", ("a4", "letter", "legal", "a3"), "a4")
    landscape = opt.choice("orientation", ("portrait", "landscape"), "portrait") == "landscape"
    margin = {"none": 0.0, "small": 0.25, "normal": 0.5}[opt.choice("margin", ("none", "small", "normal"), "small")]
    background = opt.flag("background", True)
    executable = browser.find()
    notes = []
    sources = [(url, None, re.sub(r"[^\w.-]+", "_", re.sub(r"^https?://", "", url))[:60] or "page")] if url else []
    sources += [(None, item.data.decode("utf-8", "replace"), item.stem) for item in pages]
    out = []
    for address, html, name in sources:
        if executable:
            data = browser.print_to_pdf(executable, url=address, html=html, paper=paper, landscape=landscape,
                                        margin=margin, background=background)
        else:
            if address and sys.platform == "emscripten":
                from pyodide.http import open_url
                try:
                    html = open_url(address).read()
                except Exception:
                    raise ToolError("Your browser could not read this website. Save the page as HTML and select that file instead.") from None
            elif address:
                try:
                    request = urllib.request.Request(address, headers={"User-Agent": "Mozilla/5.0 (PageBurrow)"})
                    html = urllib.request.urlopen(request, timeout=30).read().decode("utf-8", "replace")
                except OSError:
                    raise ToolError("The page could not be downloaded. Check the address and the connection.") from None
            html = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", html)
            width, height = pdf.paper_size(paper)
            if landscape:
                width, height = height, width
            data = ooxml.render_html([html], width, height, (margin * 72 + 18,) * 4)
            notes.append("No Chrome, Edge or Chromium was found, so a basic layout without scripts and styles was used.")
        out.append((name + ".pdf", data))
    return Result(out, f"Created {len(out)} PDF file(s).", sorted(set(notes)))
