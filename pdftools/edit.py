"""Edit: rotate, page numbers, watermark, crop, and PDF forms."""
import io
import math
import re

import pymupdf as pdf
from PIL import Image

from .common import (POSITIONS, Result, ToolError, html_text, open_pdf, parse_pages, pdf_inputs, position_rect, save,
                     text_stamp)
from .registry import tool

IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp")


def image_parts(data, opacity=1.0):
    """(RGB PNG, alpha PNG or None, width, height). Colours and transparency are kept apart so
    resampling viewers do not draw dark edges, and transparent pixels take the ink colour."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ToolError("The image could not be read. Use PNG or JPG.") from None
    from PIL import ImageOps
    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
    if not has_alpha and opacity >= 1:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, "PNG")
        return buffer.getvalue(), None, image.width, image.height
    rgba = image.convert("RGBA")
    visible = rgba.getchannel("A").point(lambda a: 255 if a else 0)
    alpha = rgba.getchannel("A")
    if opacity < 1:
        alpha = alpha.point(lambda a: round(a * opacity))
    # Transparent pixels get the average visible colour instead of black.
    small = rgba.resize((32, 32))
    opaque = [p[:3] for p in small.getdata() if p[3] > 32]
    fill = tuple(sum(c[i] for c in opaque) // len(opaque) for i in range(3)) if opaque else (0, 0, 0)
    rgb = Image.new("RGB", rgba.size, fill)
    rgb.paste(rgba.convert("RGB"), mask=visible)
    color, mask = io.BytesIO(), io.BytesIO()
    rgb.save(color, "PNG")
    alpha.save(mask, "PNG")
    return color.getvalue(), mask.getvalue(), image.width, image.height


def rotated_size(width, height, angle):
    radians = math.radians(angle)
    return (abs(width * math.cos(radians)) + abs(height * math.sin(radians)),
            abs(width * math.sin(radians)) + abs(height * math.cos(radians)))


@tool("rotate")
def rotate(files, opt):
    angle = int(str(opt.get("angle", "90")))
    if angle not in (90, 180, 270):
        raise ToolError("Choose 90, 180 or 270 degrees.")
    out = []
    for item in pdf_inputs(files):
        doc = open_pdf(item)
        pages = parse_pages(opt.text("pages", "all"), doc.page_count)
        for number in set(pages):
            page = doc[number]
            page.set_rotation((page.rotation + angle) % 360)
        out.append((item.stem + "_rotated.pdf", save(doc)))
    return Result(out, f"Rotated pages in {len(out)} file(s) by {angle}°.")


def number_text(template, n, total, in_range, first):
    text = template.replace("{rf}", str(first + in_range - 1)).replace("{r}", str(in_range))
    return text.replace("{n}", str(n)).replace("{p}", str(total))


@tool("page_numbers")
def page_numbers(files, opt):
    layout = opt.choice("layout", ("single", "facing"), "single")
    position = opt.choice("position", [p for p in POSITIONS if not p.startswith("middle") and p != "center"], "bottom-center")
    margin = {"small": 18, "medium": 30, "big": 48}[opt.choice("margin", ("small", "medium", "big"), "medium")]
    first = opt.number("first", 1, -1_000_000, 1_000_000, "first number", integer=True)
    template = opt.text("format", "{n}", 120) or "{n}"
    size = opt.number("size", 11, 5, 96, "font size")
    style = {"family": opt.choice("family", ("sans", "serif", "mono"), "sans"), "color": opt.color("color", "#000000"),
             "bold": opt.flag("bold"), "italic": opt.flag("italic")}
    opacity = opt.number("opacity", 100, 5, 100, "opacity") / 100
    cover = opt.flag("cover", True)
    out = []
    for item in pdf_inputs(files):
        doc = open_pdf(item)
        pages = parse_pages(opt.text("pages", "all"), doc.page_count)
        for index, number in enumerate(pages):
            page = doc[number]
            vertical, horizontal = position.split("-")
            if layout == "facing" and horizontal != "center":
                # On left-hand pages "outside" and "inside" swap sides.
                left_hand = (number % 2 == 1) if cover else (number % 2 == 0)
                if left_hand:
                    horizontal = "left" if horizontal == "right" else "right"
            text = number_text(template, first + index, doc.page_count, len(pages), first)
            height = size * 1.7
            area = page.rect
            box = pdf.Rect(area.x0 + margin, 0, area.x1 - margin, height)
            box.y0 = area.y0 + margin if vertical == "top" else area.y1 - margin - height
            box.y1 = box.y0 + height
            html = html_text(text, size=size, align=horizontal, **style)
            spare, _ = page.insert_htmlbox(box * page.derotation_matrix, html, rotate=page.rotation, opacity=opacity,
                                           scale_low=0.4)
            if spare < 0:
                raise ToolError("The page number text is too long for the page. Shorten it or use a smaller size.")
        out.append((item.stem + "_numbered.pdf", save(doc)))
    return Result(out, f"Added page numbers to {len(out)} file(s).")


@tool("watermark")
def watermark(files, opt):
    pdfs = pdf_inputs(files)
    kind = opt.choice("type", ("text", "image"), "text")
    position = opt.choice("position", POSITIONS + ["mosaic"], "center")
    angle = opt.number("angle", 45, -360, 360, "rotation")
    opacity = opt.number("opacity", 40, 1, 100, "opacity") / 100
    over = opt.choice("layer", ("over", "under"), "over") == "over"
    if kind == "text":
        text = opt.text("text", "CONFIDENTIAL", 300).strip()
        if not text:
            raise ToolError("Enter the watermark text.")
        size = opt.number("size", 48, 4, 400, "font size")
        stamp = text_stamp(text, size, family=opt.choice("family", ("sans", "serif", "mono"), "sans"),
                           color=opt.color("color", "#d0021b"), bold=opt.flag("bold", True), italic=opt.flag("italic"),
                           underline=opt.flag("underline"), opacity=opacity)
        stamp_w, stamp_h = stamp[0].rect.width, stamp[0].rect.height
    else:
        images = [f for f in files if f.suffix in IMAGE_TYPES]
        if not images:
            raise ToolError("Choose the image to use as the watermark.")
        color, mask, width, height = image_parts(images[-1].data, opacity)
        stamp = pdf.open()
        sp = stamp.new_page(width=width, height=height)
        sp.insert_image(sp.rect, stream=color, mask=mask, keep_proportion=False) if mask else sp.insert_image(sp.rect, stream=color)
        scale = opt.number("scale", 40, 1, 100, "image size") / 100
    out, notes = [], []
    hidden = False
    for item in pdfs:
        doc = open_pdf(item)
        for number in set(parse_pages(opt.text("pages", "all"), doc.page_count)):
            page = doc[number]
            if kind == "image":
                stamp_w = page.rect.width * scale
                stamp_h = stamp_w * stamp[0].rect.height / stamp[0].rect.width
            box_w, box_h = rotated_size(stamp_w, stamp_h, angle)
            if position == "mosaic":
                step_x, step_y = box_w + max(36, stamp_w * 0.25), box_h + max(36, stamp_h * 1.5)
                cols = max(1, math.ceil(page.rect.width / step_x) + 1)
                rows = max(1, math.ceil(page.rect.height / step_y) + 1)
                spots = [pdf.Rect(c * step_x - box_w / 4 + (step_x / 2 if r % 2 else 0), r * step_y - box_h / 4, 0, 0)
                         for r in range(rows) for c in range(cols)]
                spots = [pdf.Rect(s.x0, s.y0, s.x0 + box_w, s.y0 + box_h) for s in spots]
            else:
                spots = [position_rect(page.rect, box_w, box_h, position, 24)]
            for spot in spots:
                page.show_pdf_page(spot * page.derotation_matrix, stamp, 0, rotate=angle - page.rotation,
                                   overlay=over, keep_proportion=True)
            if not over and not hidden:
                images = page.get_image_info()
                hidden = any(abs(pdf.Rect(i["bbox"]) & page.rect) > 0.5 * abs(page.rect) for i in images)
        out.append((item.stem + "_watermarked.pdf", save(doc)))
    if hidden:
        notes.append("Some pages are scans or full-page pictures: a watermark placed below the content is hidden "
                     "behind them. Choose “Over the content” to see it on those pages.")
    return Result(out, f"Added the watermark to {len(out)} file(s).", notes)


def content_box(page, padding):
    """Smallest area holding anything visible (works for scans too), in display coordinates."""
    dpi = 50
    pix = page.get_pixmap(dpi=dpi, colorspace=pdf.csGRAY, alpha=False)
    dark = bytes(1 if v < 235 else 0 for v in range(256))
    samples, stride, width = pix.samples, pix.stride, pix.width
    top = bottom = None
    left, right = width, -1
    for y in range(pix.height):
        row = samples[y * stride:y * stride + width].translate(dark)
        first = row.find(1)
        if first < 0:
            continue
        top = y if top is None else top
        bottom = y
        left = min(left, first)
        right = max(right, row.rfind(1))
    if top is None:
        return None
    scale = 72 / dpi
    box = pdf.Rect(left * scale - padding, top * scale - padding, (right + 1) * scale + padding, (bottom + 1) * scale + padding)
    return box & page.rect


@tool("crop")
def crop(files, opt):
    mode = opt.choice("mode", ("auto", "area", "margins"), "auto")
    true_crop = opt.flag("remove_outside")
    out, notes = [], []
    for item in pdf_inputs(files):
        doc = open_pdf(item)
        changed = 0
        for number in parse_pages(opt.text("pages", "all"), doc.page_count):
            page = doc[number]
            area = page.rect
            if mode == "auto":
                box = content_box(page, opt.number("padding", 8, 0, 144, "padding"))
                if box is None:
                    continue
            elif mode == "area":
                values = opt.get("area")
                try:
                    x0, y0, x1, y1 = (float(v) for v in values)
                except (TypeError, ValueError):
                    raise ToolError("Draw the area to keep on the page.") from None
                box = pdf.Rect(x0 * area.width, y0 * area.height, x1 * area.width, y1 * area.height).normalize() & area
            else:
                mm = 72 / 25.4
                box = pdf.Rect(area.x0 + opt.number("left", 10, 0, 1000, "left margin") * mm,
                               area.y0 + opt.number("top", 10, 0, 1000, "top margin") * mm,
                               area.x1 - opt.number("right", 10, 0, 1000, "right margin") * mm,
                               area.y1 - opt.number("bottom", 10, 0, 1000, "bottom margin") * mm)
            if box.is_empty or box.width < 10 or box.height < 10:
                raise ToolError(f"The area to keep on page {number + 1} is too small.")
            if true_crop:
                for strip in (pdf.Rect(area.x0, area.y0, area.x1, box.y0), pdf.Rect(area.x0, box.y1, area.x1, area.y1),
                              pdf.Rect(area.x0, box.y0, box.x0, box.y1), pdf.Rect(box.x1, box.y0, area.x1, box.y1)):
                    if not strip.is_empty and strip.width > 0.1 and strip.height > 0.1:
                        page.add_redact_annot(strip * page.derotation_matrix, fill=False)
                page.apply_redactions(images=pdf.PDF_REDACT_IMAGE_PIXELS,
                                      graphics=pdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                                      text=pdf.PDF_REDACT_TEXT_REMOVE)
            page.set_cropbox(box * page.derotation_matrix)
            changed += 1
        out.append((item.stem + "_cropped.pdf", save(doc)))
        if not changed:
            notes.append(f"{item.name}: no page was cropped (the pages are empty).")
    if true_crop:
        notes.append("Content outside the kept area was deleted from the file, not just hidden.")
    return Result(out, f"Cropped {len(out)} file(s).", notes)


# ---------- forms ----------

TYPES = {"text": pdf.PDF_WIDGET_TYPE_TEXT, "checkbox": pdf.PDF_WIDGET_TYPE_CHECKBOX,
         "combobox": pdf.PDF_WIDGET_TYPE_COMBOBOX, "listbox": pdf.PDF_WIDGET_TYPE_LISTBOX,
         "radio": pdf.PDF_WIDGET_TYPE_RADIOBUTTON}
TYPE_NAMES = {v: k for k, v in TYPES.items()}
TYPE_NAMES[pdf.PDF_WIDGET_TYPE_SIGNATURE] = "signature"
TYPE_NAMES[pdf.PDF_WIDGET_TYPE_BUTTON] = "button"


def field_list(doc):
    fields = []
    for page in doc:
        for widget in page.widgets():
            kind = TYPE_NAMES.get(widget.field_type, "other")
            entry = {"name": widget.field_name, "type": kind, "page": page.number,
                     "rect": list(widget.rect * page.rotation_matrix), "value": widget.field_value,
                     "readonly": bool(widget.field_flags & 1), "label": widget.field_label or ""}
            if kind in ("combobox", "listbox"):
                entry["options"] = [c if isinstance(c, str) else c[0] for c in (widget.choice_values or [])]
            if kind in ("checkbox", "radio"):
                entry["on"] = widget.on_state() if widget.on_state() not in (False, None) else "Yes"
                entry["value"] = widget.field_value not in ("Off", False, "", None)
            fields.append(entry)
    return fields


def slug(text):
    words = re.findall(r"[A-Za-z0-9]+", text.lower())[:4]
    return "_".join(words) or "field"


def detect_fields(page):
    """Likely form fields on a flat page: underscore runs, lines to write on, empty boxes."""
    words = page.get_text("words")
    text_boxes = [pdf.Rect(w[:4]) for w in words if "_" not in w[4]]
    found = []

    def free(rect):
        return not any(rect.intersects(t) and abs(rect & t) > 0.3 * abs(t) for t in text_boxes)

    def label_for(rect):
        same_line = [w for w in words if abs((w[1] + w[3]) / 2 - (rect.y0 + rect.y1) / 2) < 10 and w[2] <= rect.x0 + 2
                     and rect.x0 - w[2] < 160 and "_" not in w[4]]
        same_line.sort(key=lambda w: w[0])
        return " ".join(w[4] for w in same_line[-4:]).rstrip(":")

    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            chars = [c for span in line["spans"] for c in span["chars"]]
            run = []
            for char in chars + [None]:
                if char is not None and char["c"] == "_":
                    run.append(pdf.Rect(char["bbox"]))
                    continue
                if len(run) >= 3:
                    box = run[0]
                    for r in run[1:]:
                        box |= r
                    found.append(("text", pdf.Rect(box.x0, box.y1 - 16, box.x1, box.y1 + 1)))
                run = []
    for path in page.get_drawings():
        for entry in path["items"]:
            if entry[0] == "l":
                a, b = entry[1], entry[2]
                if abs(a.y - b.y) < 1 and abs(a.x - b.x) >= 50:
                    x0, x1 = sorted((a.x, b.x))
                    box = pdf.Rect(x0, a.y - 16, x1, a.y + 1)
                    if free(box):
                        found.append(("text", box))
            elif entry[0] == "re":
                rect = pdf.Rect(entry[1])
                if rect.height < 1.6 and rect.width >= 50:
                    box = pdf.Rect(rect.x0, rect.y0 - 16, rect.x1, rect.y0 + 1)
                    if free(box):
                        found.append(("text", box))
                elif 6 <= rect.width <= 20 and abs(rect.width - rect.height) < 2.5 and free(rect):
                    found.append(("checkbox", rect))
                elif rect.width >= 40 and 12 <= rect.height <= 40 and free(rect + (-1, -1, 1, 1)):
                    found.append(("text", rect))
    unique = []
    for kind, rect in found:
        if any(abs(rect & other) > 0.5 * min(abs(rect), abs(other)) for _, other in unique):
            continue
        unique.append((kind, rect))
    return [{"type": kind, "rect": list(rect * page.rotation_matrix), "page": page.number,
             "name": slug(label_for(rect))} for kind, rect in unique]


def unique_name(name, taken):
    base, n = name, 1
    while name in taken:
        n += 1
        name = f"{base}_{n}"
    taken.add(name)
    return name


@tool("forms")
def forms(files, opt):
    item, = pdf_inputs(files, 1, 1)
    doc = open_pdf(item)
    action = opt.choice("action", ("list", "detect", "fill"), "list")
    if action == "list":
        return Result(data={"fields": field_list(doc)})
    if action == "detect":
        candidates = [c for page in doc for c in detect_fields(page)]
        return Result(data={"candidates": candidates})
    # fill: set values of existing fields, create new ones, optionally flatten
    taken = {w.field_name for page in doc for w in page.widgets()}
    created = 0
    for spec in opt.get("create") or []:
        try:
            page = doc[int(spec["page"])]
            rect = pdf.Rect(spec["rect"]) * page.derotation_matrix
        except (KeyError, ValueError, TypeError, IndexError):
            raise ToolError("A new field has an invalid position.") from None
        kind = spec.get("type", "text")
        if kind not in TYPES or rect.is_empty or rect.width < 4 or rect.height < 4:
            raise ToolError("A new field is too small or of an unknown type.")
        widget = pdf.Widget()
        widget.field_type = TYPES[kind]
        widget.field_name = unique_name(slug(str(spec.get("name") or kind)), taken)
        widget.rect = rect
        widget.text_fontsize = 0
        if kind in ("combobox", "listbox"):
            choices = [str(c) for c in spec.get("options") or [] if str(c).strip()]
            if not choices:
                raise ToolError("Give the list field at least one choice.")
            widget.choice_values = choices
            widget.field_value = choices[0]
        elif kind in ("checkbox", "radio"):
            widget.field_value = False
        page.add_widget(widget)
        created += 1
    values = opt.get("values") or {}
    filled = 0
    for page in doc:
        for widget in page.widgets():
            if widget.field_name not in values:
                continue
            value = values[widget.field_name]
            kind = TYPE_NAMES.get(widget.field_type)
            if kind == "checkbox":
                widget.field_value = widget.on_state() if value else "Off"
            elif kind == "radio":
                widget.field_value = widget.on_state() if str(value) == str(widget.on_state()) else "Off"
            elif kind in ("combobox", "listbox"):
                choices = [c if isinstance(c, str) else c[0] for c in (widget.choice_values or [])]
                if str(value) not in choices and kind == "listbox":
                    raise ToolError(f"“{value}” is not one of the choices of {widget.field_name}.")
                widget.field_value = str(value)
            elif kind == "text":
                widget.field_value = str(value)
            else:
                continue
            widget.update()
            filled += 1
    if opt.flag("flatten"):
        doc.bake(annots=False, widgets=True)
    message = f"Filled {filled} field value(s)" + (f", created {created} field(s)" if created else "") + \
        (", and flattened the form" if opt.flag("flatten") else "") + "."
    return Result([(item.stem + "_form.pdf", save(doc))], message)
