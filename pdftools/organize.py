"""Organize: merge, split, remove/extract pages, organize, scan to PDF."""
import io

import pymupdf as pdf
from PIL import Image, ImageFilter, ImageMath, ImageOps

from .common import (Result, ToolError, describe_pages, open_pdf, parse_pages, pdf_inputs, save)
from .registry import tool

IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp")


def image_page(doc, data, page_size="fit", orientation="auto", margin=0):
    """Add one page holding an image. JPEG and PNG data go in unchanged (no quality loss);
    the phone's rotation flag (EXIF) is honoured."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ToolError("One of the images could not be read. Use JPG, PNG, GIF, BMP, TIFF or WEBP.") from None
    orient = image.getexif().get(0x0112, 1) if hasattr(image, "getexif") else 1
    rotate = {3: 180, 6: 270, 8: 90}.get(orient, 0)  # insert_image turns counter-clockwise
    width, height = image.size
    if image.format not in ("JPEG", "PNG") or orient in (2, 4, 5, 7) or getattr(image, "n_frames", 1) > 1:
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "RGBA", "L", "LA"):
            image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        data, rotate = buffer.getvalue(), 0
        width, height = image.size
    elif rotate in (90, 270):
        width, height = height, width
    dpi = image.info.get("dpi", (96, 96))[0] or 96
    if page_size == "fit":
        scale = 72 / max(30, min(dpi, 1200))
        pw, ph = width * scale + 2 * margin, height * scale + 2 * margin
    else:
        pw, ph = pdf.paper_size(page_size)
        landscape = orientation == "landscape" or (orientation == "auto" and width > height)
        if landscape:
            pw, ph = ph, pw
    page = doc.new_page(width=pw, height=ph)
    page.insert_image(pdf.Rect(margin, margin, pw - margin, ph - margin), stream=data, rotate=rotate, keep_proportion=True)
    return page


def as_pdf(item):
    """A PDF document for a PDF or image input."""
    if item.suffix in IMAGE_TYPES:
        doc = pdf.open()
        image_page(doc, item.data)
        return doc
    return open_pdf(item)


@tool("merge")
def merge(files, opt):
    if len(files) < 2:
        raise ToolError("Choose at least two files to merge.")
    out = pdf.open()
    toc = []
    bookmarks = opt.flag("bookmarks", True)
    for item in files:
        src = as_pdf(item)
        start = out.page_count
        out.insert_pdf(src)
        if bookmarks:
            toc.append([1, item.stem, start + 1])
            toc.extend([level + 1, title, page + start] for level, title, page in src.get_toc(simple=True) if page > 0)
    try:
        out.set_toc(toc)
    except (ValueError, RuntimeError):
        out.set_toc([entry for entry in toc if entry[0] == 1])
    name = files[0].stem + "_merged.pdf"
    return Result([(name, save(out))], f"Merged {len(files)} files into {out.page_count} pages.")


def split_by_size(doc, limit):
    chunks, start = [], 0
    while start < doc.page_count:
        end = start
        while end + 1 < doc.page_count:
            trial = pdf.open()
            trial.insert_pdf(doc, from_page=start, to_page=end + 1)
            if len(save(trial, keep_encryption=False)) > limit:
                break
            end += 1
        chunks.append(list(range(start, end + 1)))
        start = end + 1
    return chunks


@tool("split")
def split(files, opt):
    item, = pdf_inputs(files, 1, 1)
    doc = open_pdf(item)
    count = doc.page_count
    mode = opt.choice("mode", ("ranges", "fixed", "extract", "size"), "ranges")
    notes = []
    if mode == "ranges":
        groups = []
        for part in [p for p in opt.text("ranges", "").split(",") if p.strip()] or ["1-"]:
            groups.append(parse_pages(part, count))
    elif mode == "fixed":
        every = opt.number("every", 1, 1, 10000, "pages per file", integer=True)
        groups = [list(range(i, min(i + every, count))) for i in range(0, count, every)]
    elif mode == "extract":
        pages = parse_pages(opt.text("pages", "all"), count)
        groups = [pages] if opt.flag("merge") else [[p] for p in pages]
    else:
        limit = opt.number("max_mb", 5, 0.05, 2000, "maximum size") * 1_000_000
        groups = split_by_size(doc, limit)
        big = [g for g in groups if len(g) == 1]
        if big:
            notes.append("Some single pages are larger than the limit on their own; they are in separate files.")
    if mode == "ranges" and opt.flag("merge"):
        groups = [[p for g in groups for p in g]]
    out = []
    for group in groups:
        part = pdf.open()
        for number in group:
            part.insert_pdf(doc, from_page=number, to_page=number)
        out.append((f"{item.stem}_pages_{describe_pages(group).replace(', ', '_')}.pdf", save(part)))
    return Result(out, f"Created {len(out)} PDF file{'s' if len(out) != 1 else ''}.", notes)


@tool("remove_pages")
def remove_pages(files, opt):
    item, = pdf_inputs(files, 1, 1)
    doc = open_pdf(item)
    pages = sorted(set(parse_pages(opt.text("pages"), doc.page_count, empty_means_all=False)))
    if not pages:
        raise ToolError("Enter the pages to remove.")
    if len(pages) == doc.page_count:
        raise ToolError("A PDF needs at least one page. Leave at least one page.")
    doc.delete_pages(pages)
    return Result([(item.stem + "_removed.pdf", save(doc))], f"Removed {len(pages)} page(s); {doc.page_count} left.")


@tool("extract_pages")
def extract_pages(files, opt):
    item, = pdf_inputs(files, 1, 1)
    doc = open_pdf(item)
    pages = parse_pages(opt.text("pages"), doc.page_count, empty_means_all=False)
    if not pages:
        raise ToolError("Enter the pages to extract.")
    if opt.flag("separate"):
        out = []
        for number in pages:
            part = pdf.open()
            part.insert_pdf(doc, from_page=number, to_page=number)
            out.append((f"{item.stem}_page_{number + 1}.pdf", save(part)))
        return Result(out, f"Extracted {len(out)} pages into separate files.")
    part = pdf.open()
    for number in pages:
        part.insert_pdf(doc, from_page=number, to_page=number)
    return Result([(item.stem + "_extracted.pdf", save(part))], f"Extracted {len(pages)} page(s).")


@tool("organize")
def organize(files, opt):
    """opt.pages: [{"file": i, "page": n, "rotate": 0/90/180/270} or {"blank": true}] in the new order."""
    sources = [as_pdf(item) for item in files]
    plan = opt.get("pages")
    if not isinstance(plan, list) or not plan:
        raise ToolError("Arrange at least one page.")
    out = pdf.open()
    last_size = pdf.paper_size("a4")
    for entry in plan:
        if not isinstance(entry, dict):
            raise ToolError("The page arrangement is not valid.")
        if entry.get("blank"):
            out.new_page(width=last_size[0], height=last_size[1])
            continue
        try:
            src = sources[int(entry["file"])]
            number = int(entry["page"])
            src[number]
        except (KeyError, ValueError, TypeError, IndexError):
            raise ToolError("A page in the arrangement no longer exists. Add the file again.") from None
        out.insert_pdf(src, from_page=number, to_page=number)
        page = out[-1]
        turn = int(entry.get("rotate", 0)) % 360
        if turn not in (0, 90, 180, 270):
            raise ToolError("Pages can only be turned by 90, 180 or 270 degrees.")
        page.set_rotation((page.rotation + turn) % 360)
        last_size = (page.rect.width, page.rect.height)
    name = (files[0].stem if files else "document") + "_organized.pdf"
    return Result([(name, save(out))], f"Created a PDF with {out.page_count} pages.")


# ---------- scan to PDF ----------

def solve(matrix, vector):
    """Gaussian elimination for the 8x8 perspective system."""
    n = len(vector)
    rows = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            raise ToolError("The page corners are too close together. Move them apart.")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(n):
            if r != col:
                factor = rows[r][col] / rows[col][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col])]
    return [rows[i][n] / rows[i][i] for i in range(n)]


def straighten(image, corners):
    """Warp the quadrilateral (top-left, top-right, bottom-right, bottom-left) to a rectangle."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = [(x * image.width, y * image.height) for x, y in corners]
    dist = lambda a, b, c, d: ((a - c) ** 2 + (b - d) ** 2) ** 0.5  # noqa: E731
    width = int(max(dist(x0, y0, x1, y1), dist(x3, y3, x2, y2)))
    height = int(max(dist(x0, y0, x3, y3), dist(x1, y1, x2, y2)))
    if width < 20 or height < 20:
        raise ToolError("The selected page area is too small.")
    target = [(0, 0), (width, 0), (width, height), (0, height)]
    source = [(x0, y0), (x1, y1), (x2, y2), (x3, y3)]
    matrix, vector = [], []
    for (u, v), (x, y) in zip(target, source):  # maps output (u, v) to input (x, y)
        matrix.append([u, v, 1, 0, 0, 0, -u * x, -v * x])
        vector.append(x)
        matrix.append([0, 0, 0, u, v, 1, -u * y, -v * y])
        vector.append(y)
    coeffs = solve(matrix, vector)
    return image.transform((width, height), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)


def enhance(image, mode):
    if mode == "color":
        return image
    gray = image.convert("L")
    if mode == "gray":
        return ImageOps.autocontrast(gray, cutoff=1)
    # "document" and "bw": even out shadows by dividing by the blurred paper brightness.
    small = gray.resize((max(1, gray.width // 8), max(1, gray.height // 8)))
    paper = small.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(6)).resize(gray.size)
    if hasattr(ImageMath, "lambda_eval"):  # Pillow 11+
        flat = ImageMath.lambda_eval(lambda a: a["g"] * 255 / (a["p"] + 1), g=gray, p=paper)
    else:  # older Pillow, e.g. on Termux
        flat = ImageMath.eval("g * 255 / (p + 1)", g=gray, p=paper)
    flat = flat.convert("L")
    flat = ImageOps.autocontrast(flat, cutoff=1)
    if mode == "bw":
        return flat.point(lambda v: 255 if v > 165 else 0, mode="1")
    return flat


@tool("scan")
def scan(files, opt):
    items = opt.get("items") or []
    images = [f for f in files]
    if not images:
        raise ToolError("Take or choose at least one photo.")
    mode = opt.choice("filter", ("color", "gray", "document", "bw"), "document")
    page_size = opt.choice("page", ("a4", "letter", "fit"), "a4")
    out = pdf.open()
    for index, item in enumerate(images):
        try:
            image = ImageOps.exif_transpose(Image.open(io.BytesIO(item.data)))
            image = image.convert("RGB")
        except (OSError, ValueError, Image.DecompressionBombError):
            raise ToolError(f"{item.name} is not a photo that can be read.") from None
        settings = items[index] if index < len(items) and isinstance(items[index], dict) else {}
        corners = settings.get("corners")
        if corners:
            try:
                corners = [(float(x), float(y)) for x, y in corners]
            except (TypeError, ValueError):
                raise ToolError("The page corners are not valid.") from None
            if len(corners) != 4 or not all(-0.01 <= c <= 1.01 for xy in corners for c in xy):
                raise ToolError("The page corners are not valid.")
            image = straighten(image, corners)
        turn = int(settings.get("rotate", 0)) % 360
        if turn:
            image = image.rotate(-turn, expand=True)
        image = enhance(image, mode)
        buffer = io.BytesIO()
        if image.mode == "1":
            image.save(buffer, "PNG", optimize=True)
        else:
            image.save(buffer, "JPEG", quality=85, optimize=True)
        image_page(out, buffer.getvalue(), page_size=page_size, margin=0)
    return Result([("scan.pdf", save(out))], f"Created a {out.page_count}-page PDF from your photos.")
