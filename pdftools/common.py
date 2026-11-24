"""Shared pieces for the PDF tools: inputs, options, page ranges and results."""
from dataclasses import dataclass, field
import io
from pathlib import Path
import re
import zipfile

import pymupdf as pdf

from editor import EditError

ROOT = Path(__file__).resolve().parent.parent


class ToolError(EditError):
    """A problem the person can fix; the message is shown to them."""


@dataclass
class Input:
    name: str
    path: Path | None = None
    raw: bytes | None = None
    password: str = ""

    @property
    def data(self):
        return self.raw if self.raw is not None else self.path.read_bytes()

    @property
    def stem(self):
        return Path(self.name).stem or "document"

    @property
    def suffix(self):
        return Path(self.name).suffix.lower()


@dataclass
class Result:
    files: list = field(default_factory=list)  # [(file name, bytes)]
    message: str = ""
    notes: list = field(default_factory=list)
    data: dict | None = None  # for tools that answer with information instead of a file


# ---------- options ----------

class Options:
    """Typed access to the options sent by the browser, with friendly errors."""

    def __init__(self, values):
        self.values = values if isinstance(values, dict) else {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def text(self, key, default="", limit=2000):
        value = self.values.get(key, default)
        if value is None:
            return default
        if not isinstance(value, str):
            value = str(value)
        return value[:limit]

    def flag(self, key, default=False):
        value = self.values.get(key, default)
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)

    def number(self, key, default, low, high, label=None, integer=False):
        value = self.values.get(key, default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ToolError(f"Enter a number for {label or key}.") from None
        if not low <= value <= high:
            raise ToolError(f"{(label or key).capitalize()} must be between {low:g} and {high:g}.")
        return int(round(value)) if integer else value

    def choice(self, key, choices, default):
        value = self.values.get(key, default)
        if value not in choices:
            raise ToolError(f"Choose a valid option for {key}.")
        return value

    def color(self, key, default="#000000"):
        value = self.values.get(key, default) or default
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ToolError("Choose a valid color.")
        return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))


# ---------- documents ----------

def open_pdf(item):
    try:
        doc = pdf.open(stream=item.data, filetype="pdf")
    except (pdf.FileDataError, pdf.EmptyFileError, RuntimeError, ValueError):
        raise ToolError(f"{item.name} could not be opened as a PDF. If it is damaged, try Repair PDF.") from None
    if doc.needs_pass and not (item.password and doc.authenticate(item.password)):
        doc.close()
        raise ToolError(f"{item.name} is protected with a password. Enter its password first.")
    if doc.page_count == 0:
        doc.close()
        raise ToolError(f"{item.name} has no pages.")
    return doc


def save(doc, keep_encryption=True):
    return doc.tobytes(garbage=3, deflate=True, use_objstms=1,
                       encryption=pdf.PDF_ENCRYPT_KEEP if keep_encryption else pdf.PDF_ENCRYPT_NONE)


def pdf_inputs(files, at_least=1, at_most=None):
    pdfs = [f for f in files if f.suffix == ".pdf" or f.data[:1024].find(b"%PDF-") >= 0]
    if len(pdfs) < at_least:
        raise ToolError("Choose a PDF file." if at_least == 1 else f"Choose at least {at_least} PDF files.")
    if at_most and len(pdfs) > at_most:
        raise ToolError(f"Choose at most {at_most} PDF files.")
    return pdfs


def parse_pages(spec, count, empty_means_all=True):
    """'1-3, 5, 8-' -> zero-based page numbers, in the order given. Also all, odd, even, last."""
    spec = (spec or "").strip().lower()
    if not spec or spec == "all":
        return list(range(count)) if empty_means_all else []
    if spec in ("odd", "even"):
        return list(range(0 if spec == "odd" else 1, count, 2))
    pages = []
    for part in re.split(r"[,;]", spec):
        part = part.strip().replace("last", str(count))
        if not part:
            continue
        match = re.fullmatch(r"(\d*)\s*(?:(-)\s*(\d*))?", part)
        if not match or not (match.group(1) or match.group(3)):
            raise ToolError(f"“{part}” is not a page or page range. Use numbers like 1-3, 5, 8-.")
        first = int(match.group(1)) if match.group(1) else 1
        last = (int(match.group(3)) if match.group(3) else count) if match.group(2) else first
        for number in (first, last):
            if not 1 <= number <= count:
                raise ToolError(f"Page {number} does not exist; this PDF has {count} page{'s' if count != 1 else ''}.")
        step = 1 if last >= first else -1
        pages.extend(range(first - 1, last - 1 + step, step))
    if not pages:
        raise ToolError("Enter the pages to use, for example 1-3, 5.")
    return pages


def describe_pages(pages):
    """[0, 1, 2, 4] -> '1-3, 5'"""
    parts, start = [], None
    for i, page in enumerate(pages):
        if start is None:
            start = page
        if i + 1 == len(pages) or pages[i + 1] != page + 1:
            parts.append(f"{start + 1}" if start == page else f"{start + 1}-{page + 1}")
            start = None
    return ", ".join(parts)


def display_to_page(rect, page):
    """A rectangle in the page as shown (rotation applied) -> PDF page coordinates."""
    return pdf.Rect(rect) * page.derotation_matrix


def zip_files(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in unique_names(files):
            archive.writestr(name, data)
    return out.getvalue()


def unique_names(files):
    seen = {}
    for name, data in files:
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        candidate, n = name, 1
        while candidate.lower() in seen:
            n += 1
            candidate = f"{stem} ({n}){'.' + ext if ext else ''}"
        seen[candidate.lower()] = True
        yield candidate, data


# ---------- text for stamps (page numbers, watermarks, signatures) ----------

FAMILIES = {"sans": "sans-serif", "serif": "serif", "mono": "monospace"}


def html_text(text, family="sans", size=12, color=(0, 0, 0), bold=False, italic=False, underline=False,
              align="left", background=None):
    """HTML for insert_htmlbox. MuPDF shapes complex scripts (e.g. Devanagari) and falls back to
    built-in Noto fonts for characters the chosen family lacks."""
    from html import escape
    rgb = "#%02x%02x%02x" % tuple(round(c * 255) for c in color)
    style = [f"font-family:{FAMILIES.get(family, 'sans-serif')}", f"font-size:{size:.2f}pt", f"color:{rgb}",
             f"text-align:{align}", "margin:0", "line-height:1.15", "white-space:pre-wrap"]
    if bold:
        style.append("font-weight:bold")
    if italic:
        style.append("font-style:italic")
    if underline:
        style.append("text-decoration:underline")
    if background:
        style.append("background-color:#%02x%02x%02x" % tuple(round(c * 255) for c in background))
    return f'<p style="{";".join(style)}">{escape(text)}</p>'


def text_stamp(text, size, **style):
    """A one-page PDF holding just this text, cropped tightly; used with show_pdf_page so the
    text can be placed at any angle and opacity."""
    opacity = style.pop("opacity", 1)
    stamp = pdf.open()
    width = max(40.0, len(text) * size * 0.75 + size * 2)
    page = stamp.new_page(width=width, height=size * 2.2)
    spare, _ = page.insert_htmlbox(page.rect, html_text(text, size=size, **style), opacity=opacity)
    if spare < 0:
        raise ToolError("The text is too long to place.")
    boxes = [pdf.Rect(b[:4]) for b in page.get_text("blocks")]
    if not boxes:
        raise ToolError("The text could not be drawn with the chosen font.")
    bbox = boxes[0]
    for box in boxes[1:]:
        bbox |= box
    page.set_cropbox((bbox + (-1, -1, 1, 1)) & page.rect)
    return stamp


def position_rect(page_rect, width, height, position, margin):
    """Place a width x height box at one of 9 positions ('top-left' ... 'bottom-right')."""
    vertical, _, horizontal = position.partition("-")
    if position == "center":
        vertical = horizontal = "center"
    x = {"left": page_rect.x0 + margin, "center": page_rect.x0 + (page_rect.width - width) / 2,
         "right": page_rect.x1 - margin - width}[horizontal or "center"]
    y = {"top": page_rect.y0 + margin, "middle": page_rect.y0 + (page_rect.height - height) / 2,
         "center": page_rect.y0 + (page_rect.height - height) / 2,
         "bottom": page_rect.y1 - margin - height}[vertical]
    return pdf.Rect(x, y, x + width, y + height)


POSITIONS = ["top-left", "top-center", "top-right", "middle-left", "center", "middle-right",
             "bottom-left", "bottom-center", "bottom-right"]
