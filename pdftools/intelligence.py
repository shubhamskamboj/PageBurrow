"""Compare, summarize and translate."""
from collections import Counter
import difflib
import io
import math
import re

import pymupdf as pdf
from PIL import Image, ImageChops

from . import ocr
from .common import Result, ToolError, html_text, open_pdf, pdf_inputs, save
from .registry import tool

RED, GREEN, ORANGE = (0.86, 0.15, 0.15), (0.1, 0.62, 0.3), (0.95, 0.55, 0.05)


def words_of(doc):
    return [(page.number, pdf.Rect(w[:4]), w[4]) for page in doc for w in page.get_text("words", sort=True)]


def visual_changes(page_a, page_b, dpi=60):
    """Rectangles (in each page's own display coordinates) where the pages look different."""
    if abs(page_a.rect.width - page_b.rect.width) > 1 or abs(page_a.rect.height - page_b.rect.height) > 1:
        return None
    pa = page_a.get_pixmap(dpi=dpi, colorspace=pdf.csGRAY, alpha=False)
    pb = page_b.get_pixmap(dpi=dpi, colorspace=pdf.csGRAY, alpha=False)
    a = Image.frombytes("L", (pa.width, pa.height), pa.samples)
    b = Image.frombytes("L", (pb.width, pb.height), pb.samples).resize(a.size)
    diff = ImageChops.difference(a, b).point(lambda v: 255 if v > 40 else 0)
    cell = 8
    grid = diff.resize((max(1, a.width // cell), max(1, a.height // cell)), Image.Resampling.BOX)
    gw, gh = grid.size
    marked = {(x, y) for y in range(gh) for x in range(gw) if grid.getpixel((x, y)) > 4}
    rects, seen = [], set()
    for start in marked:
        if start in seen:
            continue
        stack, cells = [start], []
        seen.add(start)
        while stack:
            cx, cy = stack.pop()
            cells.append((cx, cy))
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1), (cx + 1, cy + 1), (cx - 1, cy - 1)):
                if (nx, ny) in marked and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        xs, ys = [c[0] for c in cells], [c[1] for c in cells]
        scale = cell * 72 / dpi  # grid cells -> points
        rects.append(pdf.Rect(min(xs) * scale, min(ys) * scale, (max(xs) + 1) * scale, (max(ys) + 1) * scale))
    return rects


@tool("compare")
def compare(files, opt):
    first, second = pdf_inputs(files, 2, 2)
    a, b = open_pdf(first), open_pdf(second)
    mode = opt.choice("mode", ("text", "visual", "both"), "both")
    removed, added, changes = {}, {}, []
    if mode in ("text", "both"):
        wa, wb = words_of(a), words_of(b)
        if len(wa) + len(wb) > 400_000:
            raise ToolError("These documents are too long to compare word by word. Compare visually instead.")
        matcher = difflib.SequenceMatcher(None, [w[2] for w in wa], [w[2] for w in wb], autojunk=False)
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                continue
            for page, rect, _ in wa[i1:i2]:
                removed.setdefault(page, []).append(rect)
            for page, rect, _ in wb[j1:j2]:
                added.setdefault(page, []).append(rect)
            changes.append({"kind": {"delete": "Removed", "insert": "Added", "replace": "Changed"}[op],
                            "before": " ".join(w[2] for w in wa[i1:i2])[:160], "after": " ".join(w[2] for w in wb[j1:j2])[:160],
                            "page": (wa[i1][0] if i1 < len(wa) else wb[j1][0]) + 1})
    visual = {}
    if mode in ("visual", "both"):
        for number in range(min(a.page_count, b.page_count)):
            rects = visual_changes(a[number], b[number])
            if rects:
                visual[number] = rects
    report = pdf.open()
    summary = report.new_page(width=595, height=842)
    lines = [f"<h2>Comparison report</h2><p><b>Original:</b> {first.name} ({a.page_count} pages)<br/>"
             f"<b>Changed:</b> {second.name} ({b.page_count} pages)</p>"]
    if mode in ("text", "both"):
        lines.append(f"<p><b>{len(changes)}</b> text change(s): "
                     f"<span style='color:#d62626'>removed text in red</span>, <span style='color:#1a9e4d'>added text in green</span>.</p>")
    if mode in ("visual", "both"):
        lines.append(f"<p>Visual differences on <b>{len(visual)}</b> page(s), marked in orange.</p>")
    if a.page_count != b.page_count:
        lines.append(f"<p>The documents have a different number of pages ({a.page_count} and {b.page_count}).</p>")
    from html import escape
    rows = "".join(f"<tr><td>{c['page']}</td><td>{c['kind']}</td><td>{escape(c['before'])}</td><td>{escape(c['after'])}</td></tr>"
                   for c in changes[:60])
    if rows:
        lines.append("<table style='border-collapse:collapse;width:100%;font-size:8pt'><tr><th>Page</th><th>Change</th>"
                     f"<th>Before</th><th>After</th></tr>{rows}</table>")
        if len(changes) > 60:
            lines.append(f"<p>…and {len(changes) - 60} more; see the highlighted pages.</p>")
    summary.insert_htmlbox(pdf.Rect(40, 40, 555, 802), "".join(lines), scale_low=0.3,
                           css="body{font-family:sans-serif;font-size:10pt} td,th{border:0.5pt solid #bbb;padding:2pt;vertical-align:top;text-align:left}")
    for number in range(max(a.page_count, b.page_count)):
        pa = a[number] if number < a.page_count else None
        pb = b[number] if number < b.page_count else None
        if mode == "visual" and number not in visual:
            continue
        if mode == "text" and number not in removed and number not in added:
            continue
        wa = pa.rect.width if pa else pb.rect.width
        wb_ = pb.rect.width if pb else wa
        height = max(pa.rect.height if pa else 0, pb.rect.height if pb else 0)
        gap, top = 24, 30
        page = report.new_page(width=wa + wb_ + gap * 3, height=height + top + gap)
        page.insert_text((gap, 20), f"Page {number + 1} — original: {first.name}", fontsize=9, color=(0.3, 0.3, 0.3))
        page.insert_text((gap * 2 + wa, 20), f"changed: {second.name}", fontsize=9, color=(0.3, 0.3, 0.3))
        for src, x0, marks, color, vis in ((pa, gap, removed.get(number, []), RED, visual.get(number, [])),
                                           (pb, gap * 2 + wa, added.get(number, []), GREEN, visual.get(number, []))):
            frame = pdf.Rect(x0, top, x0 + (src.rect.width if src else wa), top + (src.rect.height if src else height))
            if src is None:
                page.draw_rect(frame, color=(0.7, 0.7, 0.7), dashes="[4] 0")
                page.insert_text((frame.x0 + 10, frame.y0 + 20), "No page", fontsize=11, color=(0.5, 0.5, 0.5))
                continue
            page.show_pdf_page(frame, src.parent, src.number)
            page.draw_rect(frame, color=(0.75, 0.75, 0.75), width=0.5)
            for rect in marks:
                shown = rect * src.rotation_matrix + (x0, top, x0, top)
                page.draw_rect(shown, color=None, fill=color, fill_opacity=0.28)
            for rect in vis:
                page.draw_rect(rect + (x0, top, x0, top), color=ORANGE, width=1.2)
    message = []
    if mode in ("text", "both"):
        message.append(f"{len(changes)} text change(s)")
    if mode in ("visual", "both"):
        message.append(f"visual differences on {len(visual)} page(s)")
    data = {"changes": changes[:60], "total_changes": len(changes), "visual_pages": [n + 1 for n in sorted(visual)]}
    return Result([(f"{first.stem}_vs_{second.stem}_comparison.pdf", save(report))], "Found " + " and ".join(message) + ".",
                  data=data)


STOPWORDS = set("""a about above after again against all am an and any are aren't as at be because been before being below
between both but by can cannot could did do does doing down during each few for from further had has have having he her here
hers herself him himself his how i if in into is it its itself just me more most my myself no nor not now of off on once only
or other ought our ours ourselves out over own same she should so some such than that the their theirs them themselves then
there these they this those through to too under until up very was we were what when where which while who whom why will with
would you your yours yourself yourselves also may might must shall upon within without however therefore thus page""".split())


def sentences_of(text):
    text = re.sub(r"-\n(?=[a-z])", "", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    parts = re.split(r"(?<=[.!?।])\s+(?=[\"'(\[]?[A-Z0-9ऀ-ॿ])", text)
    return [p.strip() for p in parts if 30 <= len(p.strip()) <= 600 and len(re.findall(r"\w+", p)) >= 5]


@tool("summarize")
def summarize(files, opt):
    item, = pdf_inputs(files, 1, 1)
    doc = open_pdf(item)
    if opt.flag("ocr", True) and ocr.installed():
        language = ocr.check(opt.get("languages") or ["eng"])
        for page in doc:
            if not ocr.has_text(page):
                ocr.add_text_layer(page, language, 300)
    text = "\n".join(page.get_text() for page in doc)
    sentences = sentences_of(text)
    if len(sentences) < 3:
        raise ToolError("There is not enough running text to summarize (a summary needs at least a few full sentences).")
    ratio = {"short": 0.06, "medium": 0.12, "long": 0.22}[opt.choice("length", ("short", "medium", "long"), "medium")]
    count = max(3, min(25, round(len(sentences) * ratio)))
    tokens = [[w for w in re.findall(r"[^\W\d_]{3,}", s.lower()) if w not in STOPWORDS] for s in sentences]
    frequency = Counter(w for words in tokens for w in words)
    top = max(frequency.values()) if frequency else 1
    scores = []
    for index, words in enumerate(tokens):
        if not words:
            scores.append(0)
            continue
        score = sum(frequency[w] / top for w in words) / (len(words) ** 0.6)
        score *= 1.25 if index < len(sentences) * 0.1 else 1.0  # openings tend to state the point
        scores.append(score)
    chosen = sorted(sorted(range(len(sentences)), key=lambda i: -scores[i])[:count])
    bigrams = Counter(f"{a} {b}" for words in tokens for a, b in zip(words, words[1:]))
    terms = [t for t, n in bigrams.most_common(8) if n > 1] + [w for w, _ in frequency.most_common(12)]
    seen, key_terms = set(), []
    for term in terms:
        if term not in seen and not any(term in s for s in seen):
            seen.add(term)
            key_terms.append(term)
    key_terms = key_terms[:12]
    points = [sentences[i] for i in chosen]
    words_total = len(re.findall(r"\w+", text))
    markdown = (f"# Summary of {item.name}\n\n*Key sentences picked offline by PageBurrow from "
                f"{words_total:,} words; this is not an AI-written summary.*\n\n## Key points\n\n"
                + "\n".join(f"- {p}" for p in points) + "\n\n## Key terms\n\n" + ", ".join(key_terms) + "\n")
    return Result([(item.stem + "_summary.md", markdown.encode())], f"Picked {len(points)} key sentences from {words_total:,} words.",
                  data={"points": points, "terms": key_terms})


def translatable_blocks(doc):
    for page in doc:
        for index, block in enumerate(page.get_text("dict", sort=True)["blocks"]):
            if block.get("type") != 0:
                continue
            lines = []
            for line in block["lines"]:
                lines.append("".join(span["text"] for span in line["spans"]))
            text = ""
            for line in lines:
                if text.endswith("-") and line[:1].islower():
                    text = text[:-1] + line
                else:
                    text = (text + " " + line).strip()
            if re.search(r"[^\W\d_]{2,}", text):
                yield page, f"{page.number}:{index}", block, text


@tool("translate")
def translate(files, opt):
    item, = pdf_inputs(files, 1, 1)
    doc = open_pdf(item)
    step = opt.choice("step", ("extract", "apply"), "extract")
    if step == "extract":
        segments = [{"id": key, "text": text} for _, key, _, text in translatable_blocks(doc)]
        if not segments:
            raise ToolError("This PDF has no text to translate. For a scan, run OCR PDF first.")
        return Result(data={"segments": segments})
    translations = opt.get("translations") or {}
    if not isinstance(translations, dict) or not translations:
        raise ToolError("No translations were received.")
    plan = {}
    for page, key, block, _ in translatable_blocks(doc):
        if isinstance(translations.get(key), str) and translations[key].strip():
            plan.setdefault(page.number, []).append((block, translations[key]))
    replaced = 0
    for number, entries in plan.items():
        page = doc[number]
        for block, _ in entries:
            for line in block["lines"]:
                page.add_redact_annot(pdf.Rect(line["bbox"]), fill=False)
        page.apply_redactions(images=pdf.PDF_REDACT_IMAGE_NONE, graphics=pdf.PDF_REDACT_LINE_ART_NONE,
                              text=pdf.PDF_REDACT_TEXT_REMOVE)
        for block, text in entries:
            spans = [s for l in block["lines"] for s in l["spans"] if s["text"].strip()]
            main = max(spans, key=lambda s: len(s["text"])) if spans else {"size": 11, "color": 0, "flags": 0, "font": ""}
            color = tuple(((main.get("color", 0) >> shift) & 255) / 255 for shift in (16, 8, 0))
            lower = main.get("font", "").lower()
            family = "serif" if any(k in lower for k in ("times", "serif", "georgia", "cambria")) and "sans" not in lower else \
                "mono" if "courier" in lower or "mono" in lower else "sans"
            html = html_text(text, family=family, size=main["size"], color=color, bold=bool(main["flags"] & 16) or "bold" in lower,
                             italic=bool(main["flags"] & 2))
            box = pdf.Rect(block["bbox"])
            box.x1 = max(box.x1, min(page.rect.width * 0.98, box.x0 + box.width * 1.15))
            page.insert_htmlbox(box, html, rotate=page.rotation, scale_low=0.35)
            replaced += 1
    return Result([(item.stem + "_translated.pdf", save(doc))], f"Replaced {replaced} paragraph(s) with their translation.",
                  ["Layout is kept by fitting each translated paragraph into the space of the original; very long "
                   "translations are set in a smaller size."])
