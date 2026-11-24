"""Offline OCR with the Tesseract engine built into PyMuPDF.

Only the language files (tessdata/*.traineddata, 1-15 MB each) are needed. The text found is
laid over the original page as invisible text, so the page keeps its original look and
quality and becomes searchable and selectable.
"""
import re
import urllib.request

import pymupdf as pdf

from .common import ROOT, ToolError

TESSDATA = ROOT / "tessdata"
DOWNLOAD = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{code}.traineddata"
NAMES = {
    "eng": "English", "hin": "Hindi", "mar": "Marathi", "ben": "Bengali", "guj": "Gujarati", "pan": "Punjabi",
    "tam": "Tamil", "tel": "Telugu", "kan": "Kannada", "mal": "Malayalam", "ori": "Odia", "urd": "Urdu",
    "san": "Sanskrit", "nep": "Nepali", "ara": "Arabic", "chi_sim": "Chinese (Simplified)",
    "chi_tra": "Chinese (Traditional)", "jpn": "Japanese", "kor": "Korean", "rus": "Russian", "ukr": "Ukrainian",
    "fra": "French", "deu": "German", "spa": "Spanish", "por": "Portuguese", "ita": "Italian", "nld": "Dutch",
    "pol": "Polish", "tur": "Turkish", "vie": "Vietnamese", "tha": "Thai", "ind": "Indonesian", "heb": "Hebrew",
    "ell": "Greek", "ces": "Czech", "swe": "Swedish", "dan": "Danish", "fin": "Finnish", "nor": "Norwegian",
    "hun": "Hungarian", "ron": "Romanian", "equ": "Math / equations",
}


def installed():
    if not TESSDATA.is_dir():
        return []
    return sorted(p.stem for p in TESSDATA.glob("*.traineddata") if p.stem != "osd")


def check(languages):
    languages = [code for code in languages if code] or ["eng"]
    missing = [code for code in languages if code not in installed()]
    if missing:
        raise ToolError("OCR language not installed: " + ", ".join(NAMES.get(c, c) for c in missing)
                        + ". Add it under OCR PDF > Add a language.")
    return "+".join(languages)


def download(code):
    """Fetch a language file (needs the internet once)."""
    if code not in NAMES:
        raise ToolError("Choose a language from the list.")
    TESSDATA.mkdir(exist_ok=True)
    target = TESSDATA / f"{code}.traineddata"
    partial = target.with_suffix(".part")
    try:
        urllib.request.urlretrieve(DOWNLOAD.format(code=code), partial)
    except OSError:
        partial.unlink(missing_ok=True)
        raise ToolError("The language could not be downloaded. Check the internet connection.") from None
    partial.replace(target)
    return target.stat().st_size


def has_text(page, minimum=20):
    return len(page.get_text().strip()) >= minimum


def wordlike(word):
    """Real words: letters only, normal capitalisation, and (for Latin script) a vowel.
    Sideways text makes the OCR produce many letter jumbles like 'fHlI' that fail this."""
    word = word.strip(".,:;()!?\"'")
    if len(word) < 3 or not word.isalpha() or not (word.islower() or word.isupper() or word.istitle()):
        return False
    return not all(ord(c) < 0x250 for c in word) or bool(re.search(r"[aeiouyAEIOUY]", word))


def orientation(page, language):
    """Extra turn (0/90/180/270) that makes the page's text upright, e.g. for a sideways scan.
    Each angle gets a quick low-resolution pass, scored by how much of it reads as real words.
    The page is only turned when another angle wins clearly."""
    def score(angle):
        pix = page.get_pixmap(matrix=pdf.Matrix(100 / 72, 100 / 72).prerotate(angle))
        words = [w[4] for w in pdf.open("pdf", pix.pdfocr_tobytes(language=language, tessdata=str(TESSDATA)))[0].get_text("words")]
        good = sum(map(wordlike, words))
        return good * good / max(1, len(words))

    upright = score(0)
    if upright >= 6:
        return 0  # clearly readable as it is
    best, best_score = max(((angle, score(angle)) for angle in (90, 180, 270)), key=lambda item: item[1])
    return best if best_score >= max(3.0, 2 * upright) else 0


def text_layer(page, language, dpi=300, angle=0):
    """A one-page PDF with only the invisible OCR text of `page` (no picture)."""
    pix = page.get_pixmap(matrix=pdf.Matrix(dpi / 72, dpi / 72).prerotate(angle))
    layer = pdf.open("pdf", pix.pdfocr_tobytes(language=language, tessdata=str(TESSDATA)))
    lpage = layer[0]
    lpage.clean_contents()
    for xref in lpage.get_contents():
        layer.update_stream(xref, re.sub(rb"/[A-Za-z0-9_.]+\s+Do", b"", layer.xref_stream(xref)))
    # Drop the picture itself so it is not copied along with the text.
    kind, value = layer.xref_get_key(lpage.xref, "Resources")
    if kind == "xref":
        layer.xref_set_key(int(value.split()[0]), "XObject", "null")
    else:
        layer.xref_set_key(lpage.xref, "Resources/XObject", "null")
    return layer


def add_text_layer(page, language, dpi=300, auto_rotate=True):
    angle = orientation(page, language) if auto_rotate else 0
    layer = text_layer(page, language, dpi, angle)
    # The layer was made from the page as displayed and turned by `angle`; this placement
    # (page rotation + angle) was verified for every rotation combination.
    page.show_pdf_page(page.rect * page.derotation_matrix, layer, 0, rotate=(page.rotation + angle) % 360,
                       keep_proportion=False)
    return len(layer[0].get_text("words"))


def make_searchable(doc, language, dpi=300, skip_text=True, pages=None, auto_rotate=True):
    """OCR pages in place. Returns (pages OCRed, words found)."""
    done = words = 0
    for number in pages if pages is not None else range(doc.page_count):
        page = doc[number]
        if skip_text and has_text(page):
            continue
        words += add_text_layer(page, language, dpi, auto_rotate)
        done += 1
    return done, words
