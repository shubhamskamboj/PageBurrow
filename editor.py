"""PDF text inspection, font matching, and PDF export."""
from collections import defaultdict
from functools import lru_cache
import math
import os
from pathlib import Path
import re
import subprocess
import unicodedata

import pymupdf as pdf

pdf.TOOLS.set_small_glyph_heights(True)

STANDARD = {
    "Helvetica": "helv", "Helvetica-Bold": "hebo", "Helvetica-Oblique": "heit",
    "Helvetica-BoldOblique": "hebi", "Times-Roman": "tiro", "Times-Bold": "tibo",
    "Times-Italic": "tiit", "Times-BoldItalic": "tibi", "Courier": "cour",
    "Courier-Bold": "cobo", "Courier-Oblique": "coit", "Courier-BoldOblique": "cobi",
}
CHOICES = {"Helvetica", "Times-Roman", "Courier", "Helvetica-Bold", "Times-Bold"}


class EditError(ValueError):
    pass


def font_name(name):
    return re.sub(r"^[A-Z]{6}\+", "", name)


def font_key(name):
    return re.sub(r"(regular|mt|ps)$", "", re.sub(r"[^a-z0-9]", "", font_name(name).lower()))


@lru_cache(maxsize=1)
def system_fonts():
    index = defaultdict(set)

    def add(name, path):
        if path.suffix.lower() in {".ttf", ".otf"} and path.is_file():
            index[font_key(name)].add(path)

    if os.name == "nt":
        import winreg
        for scope, folder in (
            (winreg.HKEY_LOCAL_MACHINE, Path(os.environ["WINDIR"]) / "Fonts"),
            (winreg.HKEY_CURRENT_USER, Path(os.environ["LOCALAPPDATA"]) / "Microsoft/Windows/Fonts"),
        ):
            try:
                with winreg.OpenKey(scope, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        name, value, _ = winreg.EnumValue(key, i)
                        if isinstance(value, str):
                            path = folder / os.path.expandvars(value)
                            add(re.sub(r" \([^)]+\)$", "", name), path)
            except OSError:
                pass
    else:
        try:
            result = subprocess.run(
                ["fc-list", "--format", r"%{file}\t%{postscriptname}\n"],
                capture_output=True, text=True, check=True, timeout=8,
            )
            for line in result.stdout.splitlines():
                path, separator, names = line.partition("\t")
                if separator:
                    for name in names.split(","):
                        add(name, Path(path))
        except (OSError, subprocess.SubprocessError):
            pass
    return index


def inspect_page(page):
    """Keep source coordinates and glyph geometry in the unrotated PDF space."""
    hidden = {
        tuple(round(v, 1) for v in char[2])
        for trace in page.get_texttrace()
        if trace["type"] == 3 or trace["opacity"] == 0
        for char in trace["chars"]
    }
    items = {}
    blocks = page.get_text("rawdict", flags=pdf.TEXTFLAGS_RAWDICT & ~pdf.TEXT_PRESERVE_IMAGES)["blocks"]
    for block in blocks:
        for line in block["lines"]:
            horizontal = line["wmode"] == 0 and line["dir"][0] > 0.99999 and abs(line["dir"][1]) < 0.00001
            for span in line["spans"]:
                chars = [ch for ch in span["chars"] if not ch.get("synthetic", False)]
                value = "".join(ch["c"] for ch in span["chars"])
                if not value.strip():
                    continue
                box = pdf.Rect(span["bbox"]) * page.rotation_matrix
                editable = bool(
                    chars and horizontal and span.get("alpha", 255)
                    and not any(tuple(round(v, 1) for v in ch["origin"]) in hidden for ch in chars)
                    and not set(value).intersection({"\ufffd", "\x00"})
                    and all(ord(c) < 0x2e80 or c.isspace() for c in value)
                    and all(pdf.Rect(ch["bbox"]).width > 0 for ch in chars if not ch["c"].isspace())
                )
                items[str(len(items))] = {
                    **{k: span[k] for k in ("origin", "bbox", "size", "color", "alpha", "flags", "font")},
                    "font": font_name(span["font"]), "text": value, "box": tuple(box),
                    "editable": editable, "chars": chars,
                }
    return items


def glyph_boxes(span):
    boxes = []
    for char in span["chars"]:
        box = pdf.Rect(char["bbox"])
        if box.width > 0 and box.height > 0:
            center = (box.tl + box.br) * 0.5
            boxes.append(pdf.Rect(center.x - box.width * 0.08, center.y - box.height * 0.06,
                                  center.x + box.width * 0.08, center.y + box.height * 0.06))
    return boxes


def simple_text(value):
    if not isinstance(value, str) or len(value) > 350:
        raise EditError("Use up to 350 characters in one text edit.")
    for char in value:
        if unicodedata.category(char) in {"Cc", "Cf", "Mn", "Mc", "Me"} or unicodedata.bidirectional(char) in {"R", "AL", "AN"}:
            raise EditError("Use a single line of text that does not require complex-script shaping.")
    return value


def supports(font, value):
    return all(font.has_glyph(ord(char), fallback=False) for char in value)


def standard_font(name, value, matched):
    alias = STANDARD[name]
    font = pdf.Font(alias)
    if not supports(font, value):
        raise EditError(f"{name} does not have every character in this line.")
    # MuPDF's simple-font insert uses Latin-1 input. Embed a Unicode font
    # resource for characters like the euro sign and typographic punctuation.
    use_buffer = any(ord(ch) >= 256 or 128 <= ord(ch) <= 159 for ch in value)
    label = "Original PDF standard font" if matched else "Substitute font"
    if use_buffer and matched:
        label = "Standard font, embedded with Unicode encoding"
    return font, alias, use_buffer, f"{label} · {name}"


def select_font(doc, page, span, value, choice):
    if choice in CHOICES:
        return standard_font(choice, value, span is not None and span["font"] == choice)
    if choice != "match" or span is None:
        raise EditError("Select a font.")
    name = span["font"]
    xrefs = [entry[0] for entry in page.get_fonts(full=True) if font_key(entry[3]) == font_key(name)]
    for xref in dict.fromkeys(xrefs):
        try:
            _, kind, _, data = doc.extract_font(xref)
            if not data or kind not in {"ttf", "otf", "cff"}:
                continue
            font = pdf.Font(fontbuffer=data)
            if supports(font, value):
                return font, None, True, f"Original embedded font · {name}"
        except (ValueError, RuntimeError):
            continue
    if name in STANDARD:
        return standard_font(name, value, True)
    paths = system_fonts().get(font_key(name), set())
    if len(paths) == 1:
        try:
            font = pdf.Font(fontfile=str(next(iter(paths))))
            if supports(font, value):
                return font, None, True, f"Matching installed font · {name}"
        except (OSError, ValueError, RuntimeError):
            pass
    raise EditError(
        f"The original font ({name}) is unavailable for these characters. "
        "Try installing the full font and restarting the editor, or choose a substitute."
    )


def rgb(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise EditError("Choose a valid color.")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))


def point(value, rect):
    try:
        x, y = (float(v) for v in value)
    except (TypeError, ValueError):
        raise EditError("Choose a point on the PDF page.") from None
    if not math.isfinite(x) or not math.isfinite(y) or not (0 <= x <= rect.width and 0 <= y <= rect.height):
        raise EditError("The selection is outside the page.")
    return pdf.Point(x, y)


def stretch_value(edit):
    """Horizontal scale for added text: 1 is normal width, 0.5 is condensed to half."""
    try:
        value = float(edit.get("stretch", 1))
    except (TypeError, ValueError):
        value = math.nan
    if not math.isfinite(value) or not 0.25 <= value <= 4:
        raise EditError("Choose a text width from 25% to 400%.")
    return value


def insert(page, origin, value, size, color, selected, rotation=0, opacity=1, stretch=1):
    font, alias, embed, _ = selected
    resources = page.get_fonts()
    if alias and any(
        entry[4] == alias and (entry[1] != "n/a" or entry[3] != font.name or entry[5] != "WinAnsiEncoding")
        for entry in resources
    ):
        embed = True
    if embed:
        alias = f"LocalEdit{page.get_contents()[-1] if page.get_contents() else 0}"
        existing = {entry[4] for entry in resources}
        while alias in existing:
            alias += "x"
        page.insert_font(fontname=alias, fontbuffer=font.buffer)
    morph = None
    if abs(stretch - 1) > 1e-6:
        # Scale along the text direction. On 90/270 degree pages that is the
        # unrotated y axis; the fixpoint keeps the text start in place.
        morph = (origin, pdf.Matrix(stretch, 1) if rotation % 180 == 0 else pdf.Matrix(1, stretch))
    page.insert_text(origin, value, fontsize=size, fontname=alias, color=color,
                     rotate=rotation, fill_opacity=opacity, morph=morph)


def apply_page(doc, page_number, edits, assets, hidden=frozenset(), objects=None):
    """Apply edits to one page.

    Edits whose id is in `hidden` are validated but not drawn, so the browser can
    show them as a movable preview. `objects` receives the width of added text.
    """
    page = doc[page_number]
    spans = inspect_page(page) if any(edit["type"] == "replace" for edit in edits) else {}
    edited = set()
    placements = []
    notices = {}
    for edit in edits:
        if edit["type"] != "replace":
            continue
        key = edit["span"]
        span = spans.get(key)
        if not span or not span["editable"] or key in edited:
            raise EditError("This text cannot be independently edited.")
        edited.add(key)
        value = simple_text(edit["text"])
        selected = select_font(doc, page, span, value, edit["font"]) if value else None
        if selected:
            if selected[0].text_length(value, fontsize=span["size"]) + span["origin"][0] > (page.rect * page.derotation_matrix).x1 + 0.1:
                raise EditError("This text extends past the page edge. Shorten the replacement.")
            notices[edit["id"]] = selected[3]
        else:
            notices[edit["id"]] = "Original text removed"
        placements.append((edit["id"], span, value, selected))

    if placements:
        if any(page.annots(types=(pdf.PDF_ANNOT_REDACT,))):
            raise EditError("This page contains pending redactions. Resolve them before replacing text on the page.")
        link_areas = [
            link["from"] * page.derotation_matrix for link in page.get_links() if "from" in link
        ]
        neighborhoods = [
            (pdf.Rect(other["bbox"]), [pdf.Rect(ch["bbox"]) for ch in other["chars"]])
            for key, other in spans.items() if key not in edited
        ]
        for edit_id, span, value, selected in placements:
            area = pdf.Rect(span["bbox"])
            neighbors = [ch for bounds, chars in neighborhoods if bounds.intersects(area) for ch in chars]
            boxes = glyph_boxes(span)
            if any(link.intersects(box) for box in boxes for link in link_areas):
                raise EditError("This text intersects an existing hyperlink. The editor cannot safely replace it.")
            if any(ch.intersects(box) for box in boxes for ch in neighbors):
                raise EditError("The selected text overlaps other text. Editing it could remove nearby characters.")
            if selected:
                width = selected[0].text_length(value, fontsize=span["size"])
                old_right = max(area.x1, span["origin"][0])
                if span["origin"][0] + width > old_right + 0.5:
                    extra = pdf.Rect(old_right + 0.5, area.y0 + area.height * 0.2,
                                     span["origin"][0] + width, area.y1 - area.height * 0.2)
                    if any(bounds.intersects(extra) for bounds, _ in neighborhoods):
                        notices[edit_id] += " · check overlap with nearby text"
            for box in boxes:
                page.add_redact_annot(box, fill=False, cross_out=False)
        page.apply_redactions(images=pdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pdf.PDF_REDACT_LINE_ART_NONE,
                              text=pdf.PDF_REDACT_TEXT_REMOVE)
        for _, span, value, selected in placements:
            if selected:
                insert(page, span["origin"], value, span["size"], pdf.sRGB_to_pdf(span["color"]),
                       selected, opacity=span["alpha"] / 255)

    # Eraser patches are made from the original page, so they go below everything the
    # user adds; text placed on an erased area always stays on top.
    erasing = lambda edit: edit["type"] == "whiteout" and edit.get("mode") == "erase"  # noqa: E731
    for edit in sorted((edit for edit in edits if edit["type"] != "replace"), key=lambda edit: not erasing(edit)):
        kind = edit["type"]
        start = point(edit["start"], page.rect)
        if kind == "text":
            value = simple_text(edit["text"])
            size = float(edit["size"])
            if not 4 <= size <= 144 or not value.strip():
                raise EditError("Enter text and a size from 4 to 144 pt.")
            stretch = stretch_value(edit)
            selected = select_font(doc, page, None, value, edit["font"])
            width = selected[0].text_length(value, fontsize=size) * stretch
            if start.x + width > page.rect.width + 0.01 or start.y < size - 0.01:
                raise EditError("Move the new text away from the page edge.")
            color = rgb(edit["color"])
            if objects is not None:
                objects[str(edit["id"])] = round(width, 4)
            if edit.get("id") not in hidden:
                insert(page, start * page.derotation_matrix, value, size, color, selected,
                       page.rotation, stretch=stretch)
            continue
        if kind == "ink":
            points = edit.get("points")
            if not isinstance(points, list) or not 2 <= len(points) <= 5000:
                raise EditError("Draw a longer line.")
            width = float(edit.get("width", 2))
            if not 0.5 <= width <= 30:
                raise EditError("Choose a pen width from 0.5 to 30.")
            shape = page.new_shape()
            shape.draw_polyline([point(p, page.rect) * page.derotation_matrix for p in points])
            shape.finish(color=rgb(edit["color"]), width=width, closePath=False, lineCap=1, lineJoin=1)
            shape.commit()
            continue
        finish = point(edit["end"], page.rect)
        if kind == "line":
            page.draw_line(start * page.derotation_matrix, finish * page.derotation_matrix,
                           color=rgb(edit["color"]), width=float(edit.get("width", 1.5)))
            continue
        rect = pdf.Rect(start, finish).normalize() * page.derotation_matrix
        if min(rect.width, rect.height) < 2:
            raise EditError("Drag to select a larger area.")
        if kind == "image":
            img = assets.get(edit["asset"])
            if img is None:
                raise EditError("The image is missing. Select it again.")
            page.insert_image(rect, stream=img, rotate=page.rotation)
        elif kind == "link":
            url = edit["url"].strip()
            if not re.fullmatch(r"https?://[^\s]+", url, re.IGNORECASE) or len(url) > 2048:
                raise EditError("Enter a complete http:// or https:// link.")
            page.insert_link({"kind": pdf.LINK_URI, "from": rect, "uri": url})
        elif kind == "whiteout" and erasing(edit):
            # The browser rebuilt only the ink pixels from the surrounding paper; the
            # rest of the patch is transparent, so the background stays unchanged.
            # Colors and transparency arrive as separate images so the colors of
            # transparent pixels survive; resampling viewers would otherwise draw a
            # dark outline around the rebuilt letters.
            patch, mask = assets.get(edit.get("asset")), assets.get(edit.get("mask"))
            if patch is None or mask is None:
                raise EditError("An erased area is missing. Undo it and erase the area again.")
            if edit.get("id") not in hidden:
                page.insert_image(rect, stream=patch, mask=mask, rotate=page.rotation, keep_proportion=False)
        elif kind == "whiteout":
            # Scanned pages are rarely pure white; the browser samples the
            # surrounding paper color and sends it with the edit.
            fill = rgb(edit["color"]) if edit.get("color") else (1, 1, 1)
            if edit.get("id") not in hidden:
                page.draw_rect(rect, color=None, fill=fill)
        elif kind == "highlight":
            page.draw_rect(rect, color=None, fill=(1, 0.80, 0.17), fill_opacity=0.30)
        elif kind == "rectangle":
            page.draw_rect(rect, color=rgb(edit["color"]), width=1.5)
        elif kind == "ellipse":
            page.draw_oval(rect, color=rgb(edit["color"]), width=1.5)
        else:
            raise EditError("Unknown edit.")
    return notices
