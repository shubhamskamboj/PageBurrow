"""Security: unlock, protect, sign and redact."""
import re

import pymupdf as pdf

from . import ocr
from .common import Result, ToolError, html_text, open_pdf, parse_pages, pdf_inputs, save
from .edit import IMAGE_TYPES, image_parts
from .registry import tool


@tool("unlock")
def unlock(files, opt):
    out, lines = [], []
    for item in pdf_inputs(files):
        try:
            doc = pdf.open(stream=item.data, filetype="pdf")
        except (pdf.FileDataError, pdf.EmptyFileError, RuntimeError):
            raise ToolError(f"{item.name} could not be opened. Try Repair PDF.") from None
        if not doc.is_encrypted and not doc.needs_pass:
            lines.append(f"{item.name}: it was not protected.")
        elif doc.needs_pass:
            if not (item.password and doc.authenticate(item.password)):
                raise ToolError(f"Enter the correct password for {item.name}.")
            lines.append(f"{item.name}: password removed.")
        else:
            lines.append(f"{item.name}: printing, copying and editing restrictions removed.")
        out.append((item.stem + "_unlocked.pdf", doc.tobytes(garbage=3, deflate=True, encryption=pdf.PDF_ENCRYPT_NONE)))
    return Result(out, "\n".join(lines))


PERMISSIONS = {"print": pdf.PDF_PERM_PRINT | pdf.PDF_PERM_PRINT_HQ, "copy": pdf.PDF_PERM_COPY | pdf.PDF_PERM_ACCESSIBILITY,
               "edit": pdf.PDF_PERM_MODIFY | pdf.PDF_PERM_ASSEMBLE, "annotate": pdf.PDF_PERM_ANNOTATE | pdf.PDF_PERM_FORM}


@tool("protect")
def protect(files, opt):
    user = opt.text("password", "", 128)
    owner = opt.text("owner_password", "", 128)
    if not user and not owner:
        raise ToolError("Enter a password.")
    if user and user != opt.text("confirm", user, 128):
        raise ToolError("The passwords do not match.")
    allowed = opt.get("allow") or ["print", "copy", "edit", "annotate"]
    permissions = 0
    for name in allowed:
        permissions |= PERMISSIONS.get(name, 0)
    if not owner:
        # Restrictions need an owner password different from the open password.
        import secrets
        owner = user + secrets.token_urlsafe(16)
    out = []
    for item in pdf_inputs(files):
        doc = open_pdf(item)
        out.append((item.stem + "_protected.pdf", doc.tobytes(garbage=3, deflate=True, encryption=pdf.PDF_ENCRYPT_AES_256,
                                                              user_pw=user, owner_pw=owner, permissions=permissions)))
    restricted = [n for n in PERMISSIONS if n not in allowed]
    message = f"Protected {len(out)} file(s) with AES-256 encryption."
    notes = [f"Not allowed without the owner password: {', '.join(restricted)}."] if restricted else []
    if not user:
        notes.append("No open password was set: anyone can open the file, but the restrictions apply.")
    return Result(out, message, notes)


@tool("sign")
def sign(files, opt):
    document, = pdf_inputs(files, 1, 1)
    images = [f for f in files if f.suffix in IMAGE_TYPES]
    items = opt.get("items")
    if not isinstance(items, list) or not items:
        raise ToolError("Place at least one signature or field on the page.")
    doc = open_pdf(document)
    prepared = {}
    placed = 0
    for spec in items:
        if not isinstance(spec, dict):
            raise ToolError("A placed item is not valid.")
        try:
            rect = pdf.Rect([float(v) for v in spec["rect"]])
            first = int(spec.get("page", 0))
            doc[first]
        except (KeyError, ValueError, TypeError, IndexError):
            raise ToolError("A placed item has an invalid position.") from None
        pages = parse_pages(spec["pages"], doc.page_count) if spec.get("pages") else [first]
        for number in pages:
            page = doc[number]
            box = (rect & page.rect) * page.derotation_matrix
            if box.is_empty:
                continue
            if spec.get("kind") == "image":
                index = int(spec.get("image", 0))
                if not 0 <= index < len(images):
                    raise ToolError("A signature image is missing. Create it again.")
                if index not in prepared:
                    prepared[index] = image_parts(images[index].data)
                color, mask, _, _ = prepared[index]
                page.insert_image(box, stream=color, mask=mask, rotate=page.rotation, keep_proportion=True)
            else:
                text = str(spec.get("text", "")).strip()
                if not text:
                    continue
                size = max(4.0, min(float(spec.get("size", 12)), 200.0))
                color = spec.get("color", "#000000")
                rgb = tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)) if re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)) else (0, 0, 0)
                html = html_text(text, family=spec.get("family", "sans") if spec.get("family") in ("sans", "serif", "mono") else "sans",
                                 size=size, color=rgb, italic=bool(spec.get("italic")), bold=bool(spec.get("bold")))
                page.insert_htmlbox(box, html, rotate=page.rotation, scale_low=0.3)
            placed += 1
    return Result([(document.stem + "_signed.pdf", save(doc))], f"Placed {placed} item(s) on the document.",
                  ["These are visual signatures. They do not contain a digital certificate."])


# ---------- redaction ----------

def luhn(digits):
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


VERHOEFF_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
              [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
              [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
              [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
VERHOEFF_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
              [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
              [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff(digits):
    check = 0
    for i, d in enumerate(reversed(digits)):
        check = VERHOEFF_D[check][VERHOEFF_P[i % 8][int(d)]]
    return check == 0


def only_digits(text):
    return re.sub(r"\D", "", text)


PATTERNS = {
    "email": (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", None),
    "phone": (r"(?<![\w+])\+?\d[\d ().-]{8,16}\d(?!\w)", lambda m: 10 <= len(only_digits(m)) <= 13),
    "card": (r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)", lambda m: 13 <= len(only_digits(m)) <= 19 and luhn(only_digits(m))),
    "aadhaar": (r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)", lambda m: verhoeff(only_digits(m))),
    "pan": (r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b", None),
}


def text_lines(page, textpage=None):
    """(line text, per-character boxes) for each line, in PDF page coordinates."""
    for block in page.get_text("rawdict", textpage=textpage)["blocks"]:
        for line in block.get("lines", []):
            chars = [(c["c"], pdf.Rect(c["bbox"])) for span in line["spans"] for c in span["chars"]]
            if chars:
                yield "".join(c for c, _ in chars), [box for _, box in chars]


def find_matches(page, rules, textpage=None):
    """Rules are tried in priority order; a match inside text already claimed by an earlier
    rule (e.g. phone-like digits within a card number) is skipped."""
    found = []
    for text, boxes in text_lines(page, textpage):
        claimed = []
        for kind, regex, validate in rules:
            for match in regex.finditer(text):
                if validate and not validate(match.group()):
                    continue
                if any(match.start() < end and start < match.end() for start, end in claimed):
                    continue
                claimed.append((match.start(), match.end()))
                parts = [b for b in boxes[match.start():match.end()] if not b.is_empty]
                if not parts:
                    continue
                rect = parts[0]
                for part in parts[1:]:
                    rect |= part
                found.append((kind, match.group(), rect))
    return found


@tool("redact")
def redact(files, opt):
    item, = pdf_inputs(files, 1, 1)
    doc = open_pdf(item)
    flags = 0 if opt.flag("match_case") else re.IGNORECASE
    rules = []
    for term in opt.get("terms") or []:
        term = str(term).strip()
        if term:
            body = re.escape(term)
            if opt.flag("whole_words", True):
                body = rf"(?<!\w){body}(?!\w)"
            rules.append(("text", re.compile(body, flags), None))
    wanted = set(opt.get("patterns") or [])
    for name in ("email", "card", "aadhaar", "pan", "phone"):  # most specific first
        if name in wanted:
            regex, validate = PATTERNS[name]
            rules.append((name, re.compile(regex), validate))
    use_ocr = opt.flag("ocr") and ocr.installed()
    language = ocr.check(opt.get("languages") or ["eng"]) if use_ocr else None
    areas = opt.get("areas") or []
    whole = set(parse_pages(opt.text("pages"), doc.page_count, empty_means_all=False)) if opt.text("pages").strip() else set()
    matches = []
    for page in doc:
        textpage = None
        if rules and use_ocr and not ocr.has_text(page):
            textpage = page.get_textpage_ocr(language=language, dpi=300, full=True, tessdata=str(ocr.TESSDATA))
        if rules:
            for kind, text, rect in find_matches(page, rules, textpage):
                matches.append({"page": page.number, "kind": kind, "text": text, "rect": list(rect * page.rotation_matrix)})
    if opt.flag("preview"):
        return Result(data={"matches": matches})
    color = opt.color("color", "#000000")
    count = 0
    for page in doc:
        rects = [pdf.Rect(m["rect"]) * page.derotation_matrix for m in matches if m["page"] == page.number]
        for area in areas:
            try:
                if int(area["page"]) == page.number:
                    rects.append(pdf.Rect([float(v) for v in area["rect"]]) * page.derotation_matrix)
            except (KeyError, ValueError, TypeError):
                raise ToolError("A drawn area is not valid.") from None
        if page.number in whole:
            rects.append(page.rect * page.derotation_matrix)
        for rect in rects:
            page.add_redact_annot(rect + (-0.5, -0.5, 0.5, 0.5), fill=color)
        if rects:
            page.apply_redactions(images=pdf.PDF_REDACT_IMAGE_PIXELS, graphics=pdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                                  text=pdf.PDF_REDACT_TEXT_REMOVE)
            count += len(rects)
    cleaned = []
    if opt.flag("remove_annotations", True):
        removed = 0
        for page in doc:
            for annot in list(page.annots()):
                page.delete_annot(annot)
                removed += 1
        if removed:
            cleaned.append(f"{removed} comment(s)/annotation(s)")
    if opt.flag("clean", True):
        doc.scrub(attached_files=True, clean_pages=True, embedded_files=True, hidden_text=True, javascript=True,
                  metadata=True, redactions=False, remove_links=False, reset_fields=False, reset_responses=True,
                  thumbnails=True, xml_metadata=True)
        cleaned.append("metadata, hidden text, attachments and scripts")
    if not count and not cleaned:
        raise ToolError("Nothing was found to redact. Add words, patterns or areas.")
    notes = ["The covered text and image pixels were removed from the file, not just covered."]
    if cleaned:
        notes.append("Also removed: " + "; ".join(cleaned) + ".")
    if rules and not use_ocr and any(not ocr.has_text(p) for p in doc):
        notes.append("Some pages have no text (scans). Turn on OCR to search them, or draw areas by hand.")
    return Result([(item.stem + "_redacted.pdf", save(doc))],
                  f"Redacted {count} area(s).", notes)
