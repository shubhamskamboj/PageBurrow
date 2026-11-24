"""Optimize: compress, repair, OCR, and PDF to PDF/A."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html import escape

import pymupdf as pdf

from . import ocr
from .common import Result, ToolError, open_pdf, pdf_inputs, save
from .registry import tool


@tool("compress")
def compress(files, opt):
    try:
        from compressor import compress_pdf
    except ImportError:
        raise ToolError("Compression needs the Pillow package. Start PageBurrow with its launcher.") from None
    try:
        target = Decimal(str(opt.get("target", "10")))
    except InvalidOperation:
        raise ToolError("Enter a maximum size in MB.") from None
    if not Decimal("0.01") <= target <= 4000:
        raise ToolError("Enter a maximum size between 0.01 and 4000 MB.")
    a4 = opt.choice("page", ("a4", "original"), "original") == "a4"
    jpeg = opt.choice("mode", ("lossless", "jpeg"), "jpeg") == "jpeg"
    out, lines = [], []
    for item in pdf_inputs(files):
        if item.password:
            raise ToolError(f"{item.name} is password-protected. Unlock it first, then compress.")
        try:
            result = compress_pdf(item.data, int(target * 1_000_000), a4, jpeg)
        except (pdf.FileDataError, pdf.EmptyFileError):
            raise ToolError(f"{item.name} could not be opened. Try Repair PDF first.") from None
        except ValueError as error:
            raise ToolError(f"{item.name}: {error}") from None
        before, after = len(item.data), len(result.data)
        lines.append(f"{item.name}: {before / 1e6:.2f} MB → {after / 1e6:.2f} MB"
                     + ("" if after <= target * 1_000_000 else " (above the limit)"))
        out.append((item.stem + "_compressed.pdf", result.data))
    return Result(out, "\n".join(lines))


def salvage(data):
    """A file cut off inside an object (e.g. an interrupted download): keep everything up to
    the last complete object so MuPDF can rebuild the rest."""
    end = data.rfind(b"endobj")
    return data[:end + 6] + b"\n%%EOF\n" if end > 0 else None


@tool("repair")
def repair(files, opt):
    out, notes = [], []
    for item in pdf_inputs(files):
        pdf.TOOLS.mupdf_warnings(reset=True)
        data = item.data
        try:
            doc = pdf.open(stream=data, filetype="pdf")
        except (pdf.FileDataError, pdf.EmptyFileError, RuntimeError, ValueError):
            rescued = salvage(data)
            try:
                doc = pdf.open(stream=rescued, filetype="pdf") if rescued else None
            except (pdf.FileDataError, pdf.EmptyFileError, RuntimeError, ValueError):
                doc = None
            if doc is None or not doc.page_count:
                raise ToolError(f"{item.name} is too damaged: no pages could be recovered.") from None
            notes.append(f"{item.name}: the end of the file was missing or broken; everything before the damage was recovered.")
        if doc.needs_pass and not (item.password and doc.authenticate(item.password)):
            raise ToolError(f"{item.name} is protected with a password. Enter its password first.")
        rebuilt = doc.is_repaired
        fixed = pdf.open()
        lost = []
        for number in range(doc.page_count):
            try:
                doc[number].get_pixmap(dpi=8)  # parse everything on the page
                fixed.insert_pdf(doc, from_page=number, to_page=number)
            except (RuntimeError, ValueError, IndexError):
                lost.append(number + 1)
        if not fixed.page_count:
            raise ToolError(f"{item.name}: no readable pages were found.")
        try:
            fixed.set_metadata({k: v for k, v in (doc.metadata or {}).items() if v and k != "encryption"})
            if not lost:
                fixed.set_toc(doc.get_toc())
        except (ValueError, RuntimeError):
            pass
        warnings = [w for w in pdf.TOOLS.mupdf_warnings(reset=True).splitlines() if w.strip()]
        data = fixed.tobytes(garbage=4, deflate=True, clean=True)
        if rebuilt:
            notes.append(f"{item.name}: the file's internal structure was damaged and has been rebuilt.")
        if warnings:
            notes.append(f"{item.name}: {len(warnings)} problem(s) were found and fixed while reading it.")
        if lost:
            notes.append(f"{item.name}: page(s) {', '.join(map(str, lost))} could not be recovered.")
        if not (rebuilt or warnings or lost):
            notes.append(f"{item.name}: no damage was found; the file was cleaned and saved again.")
        out.append((item.stem + "_repaired.pdf", data))
    return Result(out, f"Repaired {len(out)} file(s).", notes)


@tool("ocr")
def ocr_pdf(files, opt):
    language = ocr.check(opt.get("languages") or ["eng"])
    dpi = opt.number("dpi", 300, 100, 600, "resolution", integer=True)
    skip = opt.flag("skip_text", True)
    out, lines = [], []
    for item in pdf_inputs(files):
        doc = open_pdf(item)
        pages, words = ocr.make_searchable(doc, language, dpi, skip, auto_rotate=opt.flag("auto_rotate", True))
        if pages:
            lines.append(f"{item.name}: recognised {words} words on {pages} page(s).")
        else:
            lines.append(f"{item.name}: every page already had text, so nothing needed OCR.")
        out.append((item.stem + "_ocr.pdf", save(doc)))
    return Result(out, "\n".join(lines))


# ---------- PDF/A ----------

def srgb_profile():
    from PIL import ImageCms
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def pdf_date(moment):
    offset = moment.strftime("%z") or "+0000"
    return moment.strftime("D:%Y%m%d%H%M%S") + f"{offset[:3]}'{offset[3:]}'"


def xmp(meta, moment):
    def alt(tag, value):
        return f"<{tag}><rdf:Alt><rdf:li xml:lang=\"x-default\">{escape(value)}</rdf:li></rdf:Alt></{tag}>" if value else ""
    iso = moment.isoformat(timespec="seconds")
    author = f"<dc:creator><rdf:Seq><rdf:li>{escape(meta['author'])}</rdf:li></rdf:Seq></dc:creator>" if meta.get("author") else ""
    keywords = f"<pdf:Keywords>{escape(meta['keywords'])}</pdf:Keywords>" if meta.get("keywords") else ""
    creator = f"<xmp:CreatorTool>{escape(meta['creator'])}</xmp:CreatorTool>" if meta.get("creator") else ""
    return ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            '<rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
            'xmlns:pdf="http://ns.adobe.com/pdf/1.3/">'
            '<pdfaid:part>2</pdfaid:part><pdfaid:conformance>B</pdfaid:conformance>'
            + alt("dc:title", meta.get("title")) + author + alt("dc:description", meta.get("subject"))
            + keywords + creator +
            f"<xmp:CreateDate>{iso}</xmp:CreateDate><xmp:ModifyDate>{iso}</xmp:ModifyDate>"
            f"<xmp:MetadataDate>{iso}</xmp:MetadataDate><pdf:Producer>{escape(meta['producer'])}</pdf:Producer>"
            '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>')


def missing_fonts(doc):
    return sorted({font[3] for page in doc for font in page.get_fonts() if font[1] == "n/a"})


@tool("pdfa")
def pdfa(files, opt):
    out, notes = [], []
    for item in pdf_inputs(files):
        doc = open_pdf(item)
        report = []
        if doc.is_encrypted or item.password:
            report.append("encryption removed (PDF/A does not allow it)")
        if doc.embfile_count():
            report.append(f"{doc.embfile_count()} attached file(s) removed")
        doc.scrub(attached_files=True, clean_pages=False, embedded_files=True, hidden_text=False, javascript=True,
                  metadata=False, redactions=False, remove_links=False, reset_fields=False, reset_responses=False,
                  thumbnails=False, xml_metadata=True)
        fonts = missing_fonts(doc)
        if fonts:
            # MuPDF's PDF writer embeds every font it draws. Bookmarks and links are put back.
            toc = doc.get_toc(simple=False)
            links = [[link for link in page.get_links() if link.get("kind") in (pdf.LINK_URI, pdf.LINK_GOTO)] for page in doc]
            meta = dict(doc.metadata or {})
            doc = pdf.open("pdf", doc.convert_to_pdf())
            for page, page_links in zip(doc, links):
                for link in page_links:
                    page.insert_link(link)
            try:
                doc.set_toc(toc)
            except (ValueError, RuntimeError):
                pass
            doc.set_metadata({k: v for k, v in meta.items() if v and k != "encryption"})
            report.append(f"embedded {len(fonts)} font(s) that were missing: {', '.join(fonts[:6])}")
        moment = datetime.now().astimezone()
        meta = {k: (doc.metadata or {}).get(k) or "" for k in ("title", "author", "subject", "keywords", "creator")}
        meta["title"] = meta["title"] or item.stem
        meta["producer"] = "PageBurrow (PyMuPDF)"
        doc.set_metadata({"title": meta["title"], "author": meta["author"], "subject": meta["subject"],
                          "keywords": meta["keywords"], "creator": meta["creator"], "producer": meta["producer"],
                          "creationDate": pdf_date(moment), "modDate": pdf_date(moment)})
        doc.set_xml_metadata(xmp(meta, moment))
        icc = doc.get_new_xref()
        doc.update_object(icc, "<</N 3>>")
        doc.update_stream(icc, srgb_profile(), compress=True)
        intent = doc.get_new_xref()
        doc.update_object(intent, f"<</Type/OutputIntent/S/GTS_PDFA1/OutputConditionIdentifier(sRGB IEC61966-2.1)"
                                  f"/Info(sRGB IEC61966-2.1)/DestOutputProfile {icc} 0 R>>")
        doc.xref_set_key(doc.pdf_catalog(), "OutputIntents", f"[{intent} 0 R]")
        data = doc.tobytes(garbage=3, deflate=True, encryption=pdf.PDF_ENCRYPT_NONE)
        check = pdf.open("pdf", data)
        still = missing_fonts(check)
        status = "all fonts embedded" if not still else f"fonts still not embedded: {', '.join(still)}"
        notes.append(f"{item.name}: PDF/A-2b structure added ({status}"
                     + (f"; {'; '.join(report)}" if report else "") + ").")
        out.append((item.stem + "_pdfa.pdf", data))
    notes.append("The files carry the PDF/A-2b markers, colour profile and metadata. They have not been checked by an "
                 "independent PDF/A validator (such as veraPDF); use one if you need certified compliance.")
    return Result(out, f"Converted {len(out)} file(s) to PDF/A-2b.", notes)
