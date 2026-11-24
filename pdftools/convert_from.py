"""Convert from PDF: images, Word, PowerPoint, Excel and Markdown."""
from collections import Counter
import math
import re

import pymupdf as pdf

from . import ocr
from .common import Result, ToolError, open_pdf, parse_pages, pdf_inputs, zip_files
from .ooxml import Docx, Pptx, Xlsx
from .registry import tool

FONT_MAP = {"helvetica": "Arial", "arial": "Arial", "times": "Times New Roman", "timesnewroman": "Times New Roman",
            "courier": "Courier New", "couriernew": "Courier New", "symbol": "Symbol"}


def clean_font(name):
    name = re.sub(r"^[A-Z]{6}\+", "", name or "")
    if not name or name == "GlyphLessFont":
        return None
    base = re.split(r"[-,]", name)[0]
    base = re.sub(r"(MT|PS|Std|Pro)$", "", base)
    key = base.lower().replace(" ", "")
    for prefix, mapped in FONT_MAP.items():
        if key.startswith(prefix):
            return mapped
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base)


def span_style(span):
    font = span.get("font", "")
    lower = font.lower()
    return {"size": round(span["size"], 1),
            "bold": bool(span["flags"] & 16) or any(k in lower for k in ("bold", "black", "heavy", "semibold")),
            "italic": bool(span["flags"] & 2) or "italic" in lower or "oblique" in lower,
            "mono": bool(span["flags"] & 8) or "courier" in lower or "mono" in lower,
            "color": "%06X" % (span.get("color", 0) & 0xFFFFFF), "font": clean_font(font),
            "superscript": bool(span["flags"] & 1)}


def ocr_if_needed(doc, enabled, languages):
    """Give scanned pages a text layer. Returns the set of page numbers that were OCRed."""
    done = set()
    if not enabled:
        return done
    if not ocr.installed():
        return done
    language = ocr.check(languages or ["eng"])
    for page in doc:
        if not ocr.has_text(page):
            ocr.add_text_layer(page, language, 300)
            done.add(page.number)
    return done


def page_layout(page, include_images=True):
    """Reading-order items: ("text", block) / ("table", rows, bbox) / ("image", xref, bbox)."""
    items = []
    tables = []
    try:
        tables = [t for t in page.find_tables().tables if t.row_count >= 2 and t.col_count >= 2]
    except (ValueError, RuntimeError, AttributeError):
        tables = []
    boxes = [pdf.Rect(t.bbox) for t in tables]
    for table, box in zip(tables, boxes):
        rows = [[(c or "").strip() for c in row] for row in table.extract()]
        items.append((box.y0, box.x0, "table", rows, box))
    data = page.get_text("dict", sort=True, flags=pdf.TEXTFLAGS_DICT & ~pdf.TEXT_PRESERVE_IMAGES)
    for block in data["blocks"]:
        if block.get("type") != 0:
            continue
        box = pdf.Rect(block["bbox"])
        center = pdf.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
        if any(center in t for t in boxes):
            continue
        if any(span["text"].strip() for line in block["lines"] for span in line["spans"]):
            items.append((box.y0, box.x0, "text", block, box))
    if include_images:
        for info in page.get_image_info(xrefs=True):
            box = pdf.Rect(info["bbox"]) & page.rect
            if info.get("xref") and box.width > 8 and box.height > 8:
                items.append((box.y0, box.x0, "image", info["xref"], box))
    items.sort(key=lambda i: (round(i[0] / 3), i[1]))
    return [i[2:] for i in items]


def block_paragraphs(block):
    """Lines of a block joined into paragraph text, with run styles."""
    runs = []
    lines = block["lines"]
    for index, line in enumerate(lines):
        for span in line["spans"]:
            text = span["text"]
            if text:
                runs.append([text, span_style(span)])
        if index + 1 < len(lines) and runs:
            last = runs[-1][0]
            if last.endswith("-") and len(last) > 1 and last[-2].isalpha():
                runs[-1][0] = last[:-1]
            elif not last.endswith(" "):
                runs[-1][0] = last + " "
    merged = []
    for text, style in runs:
        if merged and merged[-1][1] == style:
            merged[-1][0] += text
        else:
            merged.append([text, style])
    return [(t, s) for t, s in merged]


def body_size(doc, sample=20):
    sizes = Counter()
    for page in list(doc)[:sample]:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    sizes[round(span["size"])] += len(span["text"].strip())
    return sizes.most_common(1)[0][0] if sizes else 11


def image_bytes(doc, xref):
    try:
        info = doc.extract_image(xref)
    except (ValueError, RuntimeError):
        return None, None
    if not info or not info.get("image"):
        return None, None
    ext = info.get("ext", "png").lower()
    if info.get("smask") or ext not in ("png", "jpeg", "jpg"):
        try:
            pix = pdf.Pixmap(doc, xref)
            if info.get("smask"):
                pix = pdf.Pixmap(pix, pdf.Pixmap(doc, info["smask"]))
            if pix.colorspace and pix.colorspace.n > 3:
                pix = pdf.Pixmap(pdf.csRGB, pix)
            return pix.tobytes("png"), "png"
        except (ValueError, RuntimeError):
            return None, None
    return info["image"], "jpeg" if ext == "jpg" else ext


@tool("pdf_to_images")
def pdf_to_images(files, opt):
    mode = opt.choice("mode", ("pages", "extract"), "pages")
    fmt = opt.choice("format", ("jpg", "png"), "jpg")
    dpi = opt.number("dpi", 150, 36, 600, "resolution", integer=True)
    quality = opt.number("quality", 90, 30, 100, "quality", integer=True)
    out = []
    for item in pdf_inputs(files):
        doc = open_pdf(item)
        pages = parse_pages(opt.text("pages", "all"), doc.page_count)
        if mode == "pages":
            for number in pages:
                page = doc[number]
                scale = dpi / 72
                pixels = page.rect.width * scale * page.rect.height * scale
                if pixels > 80_000_000:
                    scale *= (80_000_000 / pixels) ** 0.5
                pix = page.get_pixmap(matrix=pdf.Matrix(scale, scale), alpha=False)
                data = pix.tobytes("jpeg", jpg_quality=quality) if fmt == "jpg" else pix.tobytes("png")
                out.append((f"{item.stem}_page_{number + 1}.{fmt}", data))
        else:
            seen = set()
            for number in pages:
                for index, image in enumerate(doc[number].get_images(full=True), 1):
                    xref = image[0]
                    if xref in seen or image[2] < 8 or image[3] < 8:
                        continue
                    seen.add(xref)
                    data, ext = image_bytes(doc, xref)
                    if data:
                        out.append((f"{item.stem}_page_{number + 1}_image_{index}.{'jpg' if ext == 'jpeg' else ext}", data))
    if not out:
        raise ToolError("No images were found in the chosen pages." if mode == "extract" else "No pages were converted.")
    return Result(out, f"Created {len(out)} image(s).")


@tool("pdf_to_word")
def pdf_to_word(files, opt):
    out, notes = [], []
    for item in pdf_inputs(files):
        doc = open_pdf(item)
        scanned = ocr_if_needed(doc, opt.flag("ocr", True), opt.get("languages"))
        first = doc[0].rect
        body = body_size(doc)
        lefts = [b[0] for p in list(doc)[:5] for b in p.get_text("blocks")]
        margin = max(36.0, min(90.0, min(lefts) if lefts else 72.0))
        word = Docx(first.width, first.height, (margin, margin, margin, margin))
        for page in doc:
            if page.number:
                word.page_break()
            for entry in page_layout(page, include_images=page.number not in scanned):
                kind = entry[0]
                if kind == "table":
                    word.table(entry[1])
                elif kind == "image":
                    data, ext = image_bytes(doc, entry[1])
                    if data:
                        box = entry[2]
                        word.image(data, ext, box.width, box.height, "center" if abs((box.x0 + box.x1) / 2 - page.rect.width / 2) < 20 else "left")
                else:
                    block, box = entry[1], entry[2]
                    runs = block_paragraphs(block)
                    if not runs:
                        continue
                    top = max((s["size"] for _, s in runs), default=body)
                    outline = 0 if top >= body * 1.45 else 1 if top >= body * 1.18 and len("".join(t for t, _ in runs)) < 200 else None
                    width = page.rect.width
                    centered = abs((box.x0 + box.x1) / 2 - width / 2) < width * 0.04 and box.width < width * 0.75
                    right = box.x1 > width - margin - 4 and box.x0 > width * 0.55
                    for text, style in runs:
                        if style.get("mono") and not style.get("font"):
                            style["font"] = "Courier New"
                    word.paragraph(runs, "center" if centered else "right" if right else "left",
                                   indent=max(0, box.x0 - margin) if box.x0 - margin > 12 else 0, outline=outline)
        out.append((item.stem + ".docx", word.build()))
        if scanned:
            notes.append(f"{item.name}: {len(scanned)} scanned page(s) were read with OCR.")
    if opt.flag("ocr", True) and not ocr.installed():
        notes.append("OCR languages are not installed, so scanned pages could not be read.")
    return Result(out, f"Converted {len(out)} file(s) to Word.", notes)


def without_text(doc, number):
    """The page rendered with its visible text removed (graphics and pictures kept)."""
    copy = pdf.open()
    copy.insert_pdf(doc, from_page=number, to_page=number)
    page = copy[0]
    page.set_rotation(0)
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["text"].strip():
                    page.add_redact_annot(pdf.Rect(span["bbox"]), fill=False)
    page.apply_redactions(images=pdf.PDF_REDACT_IMAGE_NONE, graphics=pdf.PDF_REDACT_LINE_ART_NONE,
                          text=pdf.PDF_REDACT_TEXT_REMOVE)
    page.set_rotation(doc[number].rotation)
    return page


def hidden_origins(page):
    return {tuple(round(v, 1) for v in char[2]) for trace in page.get_texttrace()
            if trace["type"] == 3 or trace["opacity"] == 0 for char in trace["chars"]}


@tool("pdf_to_powerpoint")
def pdf_to_powerpoint(files, opt):
    out, notes = [], []
    for item in pdf_inputs(files):
        doc = open_pdf(item)
        first = doc[0].rect
        deck = Pptx(first.width, first.height)
        pictures_only = 0
        for page in doc:
            scale = first.width / page.rect.width
            hidden = hidden_origins(page)
            clean = without_text(doc, page.number)
            pix = clean.get_pixmap(dpi=150)
            image_heavy = len(pix.samples) > 4_000_000
            background = (pix.tobytes("jpeg", jpg_quality=88), "jpeg") if image_heavy else (pix.tobytes("png"), "png")
            boxes = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    runs = []
                    for span in line["spans"]:
                        if not span["text"]:
                            continue
                        origin = tuple(round(v, 1) for v in span["origin"])
                        if origin in hidden:
                            continue
                        style = span_style(span)
                        style["size"] *= scale
                        runs.append((span["text"], style))
                    if runs and "".join(t for t, _ in runs).strip():
                        # Text running in any direction: an unrotated box of the line's length and
                        # height, centred on the line and turned to its angle as shown.
                        dx, dy = line["dir"]
                        m = page.rotation_matrix
                        angle = math.degrees(math.atan2(dx * m.b + dy * m.d, dx * m.a + dy * m.c))
                        unrotated = pdf.Rect(line["bbox"])
                        length, thick = ((unrotated.width, unrotated.height) if abs(dx) >= abs(dy)
                                         else (unrotated.height, unrotated.width))
                        shown = unrotated * page.rotation_matrix
                        cx, cy = (shown.x0 + shown.x1) / 2, (shown.y0 + shown.y1) / 2
                        rect = ((cx - length / 2) * scale, (cy - thick / 2) * scale,
                                (cx + length / 2 + 2) * scale, (cy + thick / 2 + 1) * scale)
                        boxes.append((rect, [runs], angle))
            if not boxes:
                pictures_only += 1
            deck.slide(background=background, boxes=boxes)
        out.append((item.stem + ".pptx", deck.build()))
        if pictures_only:
            notes.append(f"{item.name}: {pictures_only} page(s) have no text (for example scans) and became picture slides.")
    return Result(out, f"Converted {len(out)} file(s) to PowerPoint.", notes)


NUMBER = re.compile(r"^\(?-?[\$€£₹¥]?\s?\d{1,3}(?:[,  ]\d{2,3})*(?:\.\d+)?\)?$|^\(?-?[\$€£₹¥]?\s?\d+(?:\.\d+)?\)?$")


def as_number(text):
    text = (text or "").strip()
    if not text or not NUMBER.match(text):
        return text
    negative = text.startswith("(") and text.endswith(")") or text.startswith("-")
    digits = re.sub(r"[^\d.]", "", text)
    if digits.count(".") > 1 or not digits.strip("."):
        return text
    value = float(digits)
    value = -value if negative else value
    return int(value) if value.is_integer() and "." not in digits else value


@tool("pdf_to_excel")
def pdf_to_excel(files, opt):
    out, notes = [], []
    for item in pdf_inputs(files):
        doc = open_pdf(item)
        scanned = ocr_if_needed(doc, opt.flag("ocr", True), opt.get("languages"))
        book = Xlsx()
        for page in doc:
            try:
                tables = page.find_tables().tables
            except (ValueError, RuntimeError):
                tables = []
            for index, table in enumerate(tables, 1):
                rows = [[as_number((c or "").replace("\n", " ")) for c in row] for row in table.extract()]
                if any(any(c not in ("", None) for c in row) for row in rows):
                    book.sheet(f"Page {page.number + 1} Table {index}", rows, header=True)
        if not book.sheets:
            # No ruled tables: put each line on a row, splitting columns at wide gaps.
            rows = []
            for page in doc:
                lines = {}
                for w in page.get_text("words", sort=True):
                    key = round((w[1] + w[3]) / 2 / 4)
                    lines.setdefault(key, []).append(w)
                for key in sorted(lines):
                    words = sorted(lines[key], key=lambda w: w[0])
                    cells, current, last = [], [], None
                    for w in words:
                        if last is not None and w[0] - last > max(12, (w[3] - w[1]) * 1.2):
                            cells.append(" ".join(current))
                            current = []
                        current.append(w[4])
                        last = w[2]
                    cells.append(" ".join(current))
                    rows.append([as_number(c) for c in cells])
            if not rows:
                raise ToolError(f"{item.name} has no text to put in a spreadsheet.")
            book.sheet("Text", rows, header=False)
            notes.append(f"{item.name}: no tables with clear rows and columns were found, so each line became a row.")
        out.append((item.stem + ".xlsx", book.build()))
        if scanned:
            notes.append(f"{item.name}: {len(scanned)} scanned page(s) were read with OCR.")
    return Result(out, f"Converted {len(out)} file(s) to Excel.", notes)


def md_escape(text):
    return re.sub(r"([\\`*_\[\]<>|])", r"\\\1", text)


@tool("pdf_to_markdown")
def pdf_to_markdown(files, opt):
    include_images = opt.flag("images", False)
    out, notes = [], []
    for item in pdf_inputs(files):
        doc = open_pdf(item)
        scanned = ocr_if_needed(doc, opt.flag("ocr", True), opt.get("languages"))
        body = body_size(doc)
        sizes = sorted({round(s["size"]) for p in doc for b in p.get_text("dict")["blocks"] for l in b.get("lines", [])
                        for s in l["spans"] if s["text"].strip() and round(s["size"]) > body * 1.12}, reverse=True)
        levels = {size: min(i + 1, 4) for i, size in enumerate(sizes[:4])}
        lines, images = [f"<!-- Converted from {item.name} with PageBurrow -->", ""], []
        for page in doc:
            links = [(pdf.Rect(link["from"]), link["uri"]) for link in page.get_links() if link.get("uri")]
            for entry in page_layout(page, include_images=include_images and page.number not in scanned):
                if entry[0] == "table":
                    rows = entry[1]
                    width = max(len(r) for r in rows)
                    rows = [[md_escape((c or "").replace("\n", " ")) for c in r] + [""] * (width - len(r)) for r in rows]
                    lines.append("| " + " | ".join(rows[0]) + " |")
                    lines.append("|" + " --- |" * width)
                    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                    lines.append("")
                elif entry[0] == "image":
                    data, ext = image_bytes(doc, entry[1])
                    if data:
                        name = f"images/page{page.number + 1}_{len(images) + 1}.{'jpg' if ext == 'jpeg' else ext}"
                        images.append((name, data))
                        lines += [f"![]({name})", ""]
                else:
                    block = entry[1]
                    spans = [s for l in block["lines"] for s in l["spans"] if s["text"]]
                    if not spans:
                        continue
                    if all(span_style(s)["mono"] for s in spans if s["text"].strip()):
                        code = "\n".join("".join(s["text"] for s in l["spans"]) for l in block["lines"])
                        lines += ["```", code, "```", ""]
                        continue
                    top = max(round(s["size"]) for s in spans if s["text"].strip()) if any(s["text"].strip() for s in spans) else body
                    text = ""
                    for line_index, line in enumerate(block["lines"]):
                        for span in line["spans"]:
                            piece = md_escape(span["text"])
                            style = span_style(span)
                            if piece.strip() and top not in levels:
                                if style["bold"] and style["italic"]:
                                    piece = f"***{piece.strip()}*** "
                                elif style["bold"]:
                                    piece = f"**{piece.strip()}** "
                                elif style["italic"]:
                                    piece = f"*{piece.strip()}* "
                            box = pdf.Rect(span["bbox"])
                            for rect, uri in links:
                                if abs(box & rect) > 0.5 * abs(box) and piece.strip():
                                    piece = f"[{piece.strip()}]({uri}) "
                                    break
                            text += piece
                        if line_index + 1 < len(block["lines"]):
                            text = text[:-1] if text.endswith("-") else text.rstrip() + " "
                    text = re.sub(r"\s+", " ", text).strip()
                    if not text:
                        continue
                    if top in levels:
                        lines += ["#" * levels[top] + " " + text.replace("\\", ""), ""]
                    elif re.match(r"^[•●▪◦‣·∙–\-\*]\s", text.replace("\\", "")):
                        lines += ["- " + re.sub(r"^\\?[•●▪◦‣·∙–\-\*]\s+", "", text), ""]
                    elif re.match(r"^\(?\d{1,3}[.)]\s", text):
                        lines += [re.sub(r"^\(?(\d{1,3})[.)]\s+", r"\1. ", text), ""]
                    else:
                        lines += [text, ""]
            if opt.flag("page_breaks", False) and page.number + 1 < doc.page_count:
                lines += ["---", ""]
        markdown = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
        if images:
            out.append((item.stem + "_markdown.zip", zip_files([(item.stem + ".md", markdown.encode())] + images)))
        else:
            out.append((item.stem + ".md", markdown.encode()))
        if scanned:
            notes.append(f"{item.name}: {len(scanned)} scanned page(s) were read with OCR.")
    return Result(out, f"Converted {len(out)} file(s) to Markdown.", notes)
