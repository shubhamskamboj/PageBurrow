"""Word, Excel and PowerPoint files (Office Open XML) without extra libraries.

Writers build .docx, .xlsx and .pptx from scratch. Readers turn .docx, .xlsx and .pptx into
PDF when LibreOffice is not installed; they cover text, fonts, tables, images and simple
shapes, not every Office feature.
"""
from datetime import datetime, timedelta
from html import escape
import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

import pymupdf as pdf

EMU = 12700  # per point
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def x(text):
    return escape(INVALID_XML.sub("", str(text)), quote=True)


def hex_color(rgb):
    return "%02X%02X%02X" % tuple(max(0, min(255, round(c * 255))) for c in rgb)


def content_types(defaults, overrides):
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
             '<Default Extension="xml" ContentType="application/xml"/>']
    parts += [f'<Default Extension="{ext}" ContentType="{kind}"/>' for ext, kind in defaults.items()]
    parts += [f'<Override PartName="{name}" ContentType="{kind}"/>' for name, kind in overrides]
    return "".join(parts) + "</Types>"


def relationships(rels):
    body = "".join(f'<Relationship Id="{rid}" Type="{REL_TYPE}{kind}" Target="{x(target)}"'
                   + (' TargetMode="External"' if external else "") + "/>" for rid, kind, target, external in rels)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>')


IMAGE_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "gif": "image/gif", "bmp": "image/bmp"}


def package(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files:
            archive.writestr(name, data if isinstance(data, bytes) else data.encode("utf-8"))
    return out.getvalue()


# =========================== writers ===========================

class Docx:
    """Flowing Word document: paragraphs with formatted runs, images, tables, page breaks."""

    def __init__(self, width, height, margins=(72, 72, 72, 72)):
        self.width, self.height, self.margins = width, height, margins
        self.body, self.media, self.links = [], [], []

    def paragraph(self, runs, align="left", space_after=4, outline=None, indent=0, link=None):
        jc = {"left": "left", "center": "center", "right": "right", "justify": "both"}.get(align, "left")
        ppr = f'<w:pPr><w:spacing w:before="0" w:after="{int(space_after * 20)}"/>'
        if indent > 0:
            ppr += f'<w:ind w:left="{int(indent * 20)}"/>'
        ppr += f'<w:jc w:val="{jc}"/>'
        if outline is not None:
            ppr += f'<w:outlineLvl w:val="{outline}"/>'
        ppr += "</w:pPr>"
        self.body.append(f"<w:p>{ppr}{''.join(self.run(text, style) for text, style in runs)}</w:p>")

    @staticmethod
    def run(text, style):
        rpr = ""
        font = style.get("font")
        if font:
            rpr += f'<w:rFonts w:ascii="{x(font)}" w:hAnsi="{x(font)}" w:cs="{x(font)}"/>'
        if style.get("bold"):
            rpr += "<w:b/>"
        if style.get("italic"):
            rpr += "<w:i/>"
        if style.get("color") and style["color"] != "000000":
            rpr += f'<w:color w:val="{style["color"]}"/>'
        if style.get("size"):
            half = max(2, int(round(style["size"] * 2)))
            rpr += f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/>'
        if style.get("underline"):
            rpr += '<w:u w:val="single"/>'
        if style.get("superscript"):
            rpr += '<w:vertAlign w:val="superscript"/>'
        pieces = []
        for i, part in enumerate(str(text).split("\t")):
            if i:
                pieces.append("<w:tab/>")
            if part:
                pieces.append(f'<w:t xml:space="preserve">{x(part)}</w:t>')
        return f"<w:r>{'<w:rPr>' + rpr + '</w:rPr>' if rpr else ''}{''.join(pieces)}</w:r>"

    def image(self, data, ext, width, height, align="left"):
        ext = "jpeg" if ext in ("jpg", "jpeg") else ext
        if ext not in IMAGE_TYPES:
            return
        usable = self.width - self.margins[1] - self.margins[3]
        if width > usable:
            height, width = height * usable / width, usable
        n = len(self.media) + 1
        self.media.append((f"media/image{n}.{ext}", data))
        rid = f"rIdImg{n}"
        cx, cy = int(width * EMU), int(height * EMU)
        drawing = (
            f'<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{n}" name="Picture {n}"/><wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/>'
            '</wp:cNvGraphicFramePr><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{n}" name="image{n}.{ext}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            "</wp:inline></w:drawing>")
        jc = {"center": "center", "right": "right"}.get(align, "left")
        self.body.append(f'<w:p><w:pPr><w:jc w:val="{jc}"/></w:pPr><w:r>{drawing}</w:r></w:p>')

    def table(self, rows):
        rows = [[("" if c is None else str(c)) for c in row] for row in rows if row]
        if not rows:
            return
        cols = max(len(r) for r in rows)
        usable = (self.width - self.margins[1] - self.margins[3]) * 20
        col_w = int(usable / cols)
        border = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
                         for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
        xml = (f'<w:tbl><w:tblPr><w:tblW w:w="{int(usable)}" w:type="dxa"/><w:tblBorders>{border}</w:tblBorders>'
               f'<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>{"".join(f"<w:gridCol w:w=\"{col_w}\"/>" for _ in range(cols))}</w:tblGrid>')
        for r, row in enumerate(rows):
            xml += "<w:tr>"
            for c in range(cols):
                text = row[c] if c < len(row) else ""
                lines = text.split("\n")
                paragraphs = "".join(f"<w:p>{self.run(line, {'bold': r == 0})}</w:p>" for line in lines)
                xml += f'<w:tc><w:tcPr><w:tcW w:w="{col_w}" w:type="dxa"/></w:tcPr>{paragraphs}</w:tc>'
            xml += "</w:tr>"
        self.body.append(xml + "</w:tbl><w:p/>")

    def page_break(self):
        self.body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')

    def build(self):
        top, right, bottom, left = (int(m * 20) for m in self.margins)
        w, h = int(self.width * 20), int(self.height * 20)
        orient = ' w:orient="landscape"' if w > h else ""
        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{NS["w"]}" xmlns:r="{NS["r"]}" xmlns:wp="{NS["wp"]}" xmlns:a="{NS["a"]}" xmlns:pic="{NS["pic"]}">'
            f'<w:body>{"".join(self.body) or "<w:p/>"}<w:sectPr><w:pgSz w:w="{w}" w:h="{h}"{orient}/>'
            f'<w:pgMar w:top="{top}" w:right="{right}" w:bottom="{bottom}" w:left="{left}" w:header="708" w:footer="708" w:gutter="0"/>'
            "</w:sectPr></w:body></w:document>")
        styles = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:styles xmlns:w="{NS["w"]}"><w:docDefaults><w:rPrDefault><w:rPr>'
            '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr>'
            '</w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="80"/></w:pPr></w:pPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style></w:styles>')
        rels = [("rIdStyles", "styles", "styles.xml", False)]
        rels += [(f"rIdImg{i + 1}", "image", name, False) for i, (name, _) in enumerate(self.media)]
        return package([
            ("[Content_Types].xml", content_types(
                {"png": IMAGE_TYPES["png"], "jpeg": IMAGE_TYPES["jpeg"], "gif": IMAGE_TYPES["gif"], "bmp": IMAGE_TYPES["bmp"]},
                [("/word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
                 ("/word/styles.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml")])),
            ("_rels/.rels", relationships([("rId1", "officeDocument", "word/document.xml", False)])),
            ("word/document.xml", document),
            ("word/styles.xml", styles),
            ("word/_rels/document.xml.rels", relationships(rels)),
        ] + [(f"word/{name}", data) for name, data in self.media])


def column_name(index):
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


class Xlsx:
    def __init__(self):
        self.sheets = []

    def sheet(self, name, rows, header=True):
        name = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:31] or "Sheet"
        taken = {s[0].lower() for s in self.sheets}
        base, n = name, 1
        while name.lower() in taken:
            n += 1
            name = f"{base[:28]} {n}"
        self.sheets.append((name, rows, header))

    def build(self):
        files, overrides = [], []
        sheet_rels = []
        for i, (name, rows, header) in enumerate(self.sheets, 1):
            widths = {}
            xml_rows = []
            for r, row in enumerate(rows, 1):
                cells = []
                for c, value in enumerate(row):
                    if value is None or value == "":
                        continue
                    ref = f"{column_name(c)}{r}"
                    style = ' s="1"' if header and r == 1 else ""
                    if isinstance(value, bool):
                        cells.append(f'<c r="{ref}" t="b"{style}><v>{int(value)}</v></c>')
                    elif isinstance(value, (int, float)):
                        cells.append(f'<c r="{ref}"{style}><v>{value!r}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{x(value)}</t></is></c>')
                    widths[c] = max(widths.get(c, 8), min(60, len(str(value)) + 2))
                xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
            cols = "".join(f'<col min="{c + 1}" max="{c + 1}" width="{w}" customWidth="1"/>' for c, w in sorted(widths.items()))
            sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     f'<worksheet xmlns="{NS["s"]}">' + (f"<cols>{cols}</cols>" if cols else "")
                     + f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
            files.append((f"xl/worksheets/sheet{i}.xml", sheet))
            overrides.append((f"/xl/worksheets/sheet{i}.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"))
            sheet_rels.append((f"rId{i}", "worksheet", f"worksheets/sheet{i}.xml", False))
        if not self.sheets:
            raise ValueError("no sheets")
        workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    f'<workbook xmlns="{NS["s"]}" xmlns:r="{NS["r"]}"><sheets>'
                    + "".join(f'<sheet name="{x(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _, _) in enumerate(self.sheets, 1))
                    + "</sheets></workbook>")
        styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  f'<styleSheet xmlns="{NS["s"]}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
                  '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                  '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
                  '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                  '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                  '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                  '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
                  '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        sheet_rels.append((f"rId{len(self.sheets) + 1}", "styles", "styles.xml", False))
        return package([
            ("[Content_Types].xml", content_types({}, [
                ("/xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
                ("/xl/styles.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml")] + overrides)),
            ("_rels/.rels", relationships([("rId1", "officeDocument", "xl/workbook.xml", False)])),
            ("xl/workbook.xml", workbook),
            ("xl/_rels/workbook.xml.rels", relationships(sheet_rels)),
            ("xl/styles.xml", styles),
        ] + files)


THEME = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         f'<a:theme xmlns:a="{NS["a"]}" name="Office Theme"><a:themeElements><a:clrScheme name="Office">'
         '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
         '<a:dk2><a:srgbClr val="44546A"/></a:dk2><a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>'
         '<a:accent1><a:srgbClr val="4472C4"/></a:accent1><a:accent2><a:srgbClr val="ED7D31"/></a:accent2>'
         '<a:accent3><a:srgbClr val="A5A5A5"/></a:accent3><a:accent4><a:srgbClr val="FFC000"/></a:accent4>'
         '<a:accent5><a:srgbClr val="5B9BD5"/></a:accent5><a:accent6><a:srgbClr val="70AD47"/></a:accent6>'
         '<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme>'
         '<a:fontScheme name="Office"><a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
         '<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
         '<a:fmtScheme name="Office"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
         '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
         '<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
         '<a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
         '<a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
         '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle>'
         '<a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst>'
         '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
         '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
GROUP = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm>'
         '<a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>')
PNS = f'xmlns:a="{NS["a"]}" xmlns:r="{NS["r"]}" xmlns:p="{NS["p"]}"'


class Pptx:
    """Slides with an optional full-slide background picture, pictures and text boxes."""

    def __init__(self, width, height):
        clamp = lambda v: max(914400, min(51206400, int(v * EMU)))  # noqa: E731
        self.cx, self.cy = clamp(width), clamp(height)
        self.scale = self.cx / (width * EMU)
        self.slides, self.media = [], []

    def add_media(self, data, ext):
        ext = "jpeg" if ext in ("jpg", "jpeg") else ext
        name = f"media/image{len(self.media) + 1}.{ext}"
        self.media.append((name, data))
        return name

    def slide(self, background=None, pictures=(), boxes=()):
        """background/pictures: (bytes, ext[, rect]); boxes: (rect, [paragraph: [(text, style)]])."""
        rels = [("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml", False)]
        shapes, bg, n = [], "", 2

        def emu(rect):
            return [int(v * EMU * self.scale) for v in (rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])]

        if background:
            target = self.add_media(*background[:2])
            rels.append(("rIdBg", "image", "../" + target, False))
            bg = ('<p:bg><p:bgPr><a:blipFill dpi="0" rotWithShape="1"><a:blip r:embed="rIdBg"/><a:srcRect/>'
                  '<a:stretch><a:fillRect/></a:stretch></a:blipFill><a:effectLst/></p:bgPr></p:bg>')
        for data, ext, rect in pictures:
            target = self.add_media(data, ext)
            rid = f"rIdP{n}"
            rels.append((rid, "image", "../" + target, False))
            x0, y0, w, h = emu(rect)
            shapes.append(f'<p:pic><p:nvPicPr><p:cNvPr id="{n}" name="Picture {n}"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/>'
                          f'</p:cNvPicPr><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/>'
                          f'</a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="{x0}" y="{y0}"/><a:ext cx="{max(w, 1)}" cy="{max(h, 1)}"/>'
                          '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')
            n += 1
        for rect, paragraphs, *turn in boxes:
            x0, y0, w, h = emu(rect)
            angle = round((turn[0] if turn else 0) % 360 * 60000) % 21600000
            rot = f' rot="{angle}"' if angle else ""
            body = ""
            for runs in paragraphs:
                body += "<a:p>"
                for text, style in runs:
                    size = max(100, min(400000, int(round(style.get("size", 12) * 100 * self.scale))))
                    attrs = f' lang="en-US" sz="{size}"' + (' b="1"' if style.get("bold") else "") + (' i="1"' if style.get("italic") else "")
                    fill = f'<a:solidFill><a:srgbClr val="{style.get("color", "000000")}"/></a:solidFill>'
                    font = f'<a:latin typeface="{x(style["font"])}"/>' if style.get("font") else ""
                    body += f'<a:r><a:rPr{attrs} dirty="0">{fill}{font}</a:rPr><a:t>{x(text)}</a:t></a:r>'
                body += "</a:p>"
            shapes.append(f'<p:sp><p:nvSpPr><p:cNvPr id="{n}" name="TextBox {n}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
                          f'<p:spPr><a:xfrm{rot}><a:off x="{x0}" y="{y0}"/><a:ext cx="{max(w, 1)}" cy="{max(h, 1)}"/></a:xfrm>'
                          '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
                          '<p:txBody><a:bodyPr wrap="none" lIns="0" tIns="0" rIns="0" bIns="0" rtlCol="0" anchor="t"><a:noAutofit/>'
                          f'</a:bodyPr><a:lstStyle/>{body or "<a:p/>"}</p:txBody></p:sp>')
            n += 1
        xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld {PNS}><p:cSld>{bg}<p:spTree>{GROUP}'
               f'{"".join(shapes)}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')
        self.slides.append((xml, rels))

    def build(self):
        count = len(self.slides)
        files = []
        for i, (xml, rels) in enumerate(self.slides, 1):
            files.append((f"ppt/slides/slide{i}.xml", xml))
            files.append((f"ppt/slides/_rels/slide{i}.xml.rels", relationships(rels)))
        presentation = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation {PNS} saveSubsetFonts="1">'
                        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>'
                        + "".join(f'<p:sldId id="{255 + i}" r:id="rId{i + 2}"/>' for i in range(1, count + 1))
                        + f'</p:sldIdLst><p:sldSz cx="{self.cx}" cy="{self.cy}"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
        pres_rels = [("rId1", "slideMaster", "slideMasters/slideMaster1.xml", False), ("rId2", "theme", "theme/theme1.xml", False)]
        pres_rels += [(f"rId{i + 2}", "slide", f"slides/slide{i}.xml", False) for i in range(1, count + 1)]
        master = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldMaster {PNS}><p:cSld><p:spTree>{GROUP}</p:spTree></p:cSld>'
                  '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
                  'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
                  '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst></p:sldMaster>')
        layout = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout {PNS} type="blank" preserve="1">'
                  f'<p:cSld name="Blank"><p:spTree>{GROUP}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
        overrides = [("/ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"),
                     ("/ppt/slideMasters/slideMaster1.xml", "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"),
                     ("/ppt/slideLayouts/slideLayout1.xml", "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"),
                     ("/ppt/theme/theme1.xml", "application/vnd.openxmlformats-officedocument.theme+xml")]
        overrides += [(f"/ppt/slides/slide{i}.xml", "application/vnd.openxmlformats-officedocument.presentationml.slide+xml")
                      for i in range(1, count + 1)]
        return package([
            ("[Content_Types].xml", content_types({"png": IMAGE_TYPES["png"], "jpeg": IMAGE_TYPES["jpeg"]}, overrides)),
            ("_rels/.rels", relationships([("rId1", "officeDocument", "ppt/presentation.xml", False)])),
            ("ppt/presentation.xml", presentation),
            ("ppt/_rels/presentation.xml.rels", relationships(pres_rels)),
            ("ppt/slideMasters/slideMaster1.xml", master),
            ("ppt/slideMasters/_rels/slideMaster1.xml.rels", relationships([
                ("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml", False), ("rId2", "theme", "../theme/theme1.xml", False)])),
            ("ppt/slideLayouts/slideLayout1.xml", layout),
            ("ppt/slideLayouts/_rels/slideLayout1.xml.rels", relationships([("rId1", "slideMaster", "../slideMasters/slideMaster1.xml", False)])),
            ("ppt/theme/theme1.xml", THEME),
        ] + files + [(f"ppt/{name}", data) for name, data in self.media])


# =========================== readers (Office -> PDF) ===========================

def q(prefix, tag):
    return f"{{{NS[prefix]}}}{tag}"


class Package:
    def __init__(self, data):
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ValueError("not an Office file") from None

    def xml(self, name):
        try:
            return ET.fromstring(self.zip.read(name))
        except KeyError:
            return None

    def read(self, name):
        try:
            return self.zip.read(name)
        except KeyError:
            return None

    def rels(self, part):
        folder, base = posixpath.split(part)
        tree = self.xml(posixpath.join(folder, "_rels", base + ".rels"))
        result = {}
        if tree is not None:
            for rel in tree:
                target = rel.get("Target", "")
                external = rel.get("TargetMode") == "External"
                result[rel.get("Id")] = (target if external else posixpath.normpath(posixpath.join(folder, target)),
                                         rel.get("Type", "").rsplit("/", 1)[-1], external)
        return result


def family_for(font):
    font = (font or "").lower()
    if any(k in font for k in ("courier", "consolas", "mono", "code")):
        return "monospace"
    if any(k in font for k in ("times", "georgia", "cambria", "garamond", "serif", "book", "palatino", "mincho")) and "sans" not in font:
        return "serif"
    return "sans-serif"


def render_html(chunks, width, height, margins, archive=None, css=""):
    """Lay out HTML chunks (each starts on a new page) with MuPDF's HTML engine."""
    out = io.BytesIO()
    writer = pdf.DocumentWriter(out)
    page_rect = pdf.Rect(0, 0, width, height)
    top, right, bottom, left = margins
    where = pdf.Rect(left, top, width - right, height - bottom)
    pages = 0
    for html in chunks:
        story = pdf.Story(html=html, user_css=css, archive=archive)
        more = 1
        while more:
            device = writer.begin_page(page_rect)
            more, _ = story.place(where)
            story.draw(device)
            writer.end_page()
            pages += 1
            if pages > 5000:
                raise ValueError("document too long")
    writer.close()
    return out.getvalue()


BASE_CSS = ("body{font-family:sans-serif;font-size:11pt;line-height:1.25} p{margin:0 0 4pt 0} "
            "table{border-collapse:collapse} td,th{border:0.5pt solid #999;padding:2pt 4pt;vertical-align:top} "
            "h1,h2,h3,h4,h5,h6{margin:6pt 0 4pt 0}")


def docx_to_pdf(data):
    pkg = Package(data)
    document = pkg.xml("word/document.xml")
    if document is None:
        raise ValueError("no document part")
    rels = pkg.rels("word/document.xml")
    archive = pdf.Archive()
    styles = {}
    default_size = 11.0
    style_tree = pkg.xml("word/styles.xml")
    if style_tree is not None:
        size = style_tree.find(f".//{q('w', 'rPrDefault')}//{q('w', 'sz')}")
        if size is not None:
            default_size = int(size.get(q("w", "val"), 22)) / 2
        for style in style_tree.findall(q("w", "style")):
            name = (style.find(q("w", "name")).get(q("w", "val")) if style.find(q("w", "name")) is not None else "").lower()
            entry = {}
            match = re.match(r"heading\s*(\d)", name)
            if match:
                entry["heading"] = min(6, int(match.group(1)))
            elif name == "title":
                entry["heading"] = 1
            rpr = style.find(q("w", "rPr"))
            if rpr is not None:
                sz = rpr.find(q("w", "sz"))
                if sz is not None:
                    entry["size"] = int(sz.get(q("w", "val"), 22)) / 2
                entry["bold"] = rpr.find(q("w", "b")) is not None
            styles[style.get(q("w", "styleId"))] = entry
    numbering = {}
    num_tree = pkg.xml("word/numbering.xml")
    if num_tree is not None:
        abstract = {}
        for item in num_tree.findall(q("w", "abstractNum")):
            levels = {}
            for lvl in item.findall(q("w", "lvl")):
                fmt = lvl.find(q("w", "numFmt"))
                levels[int(lvl.get(q("w", "ilvl"), 0))] = fmt.get(q("w", "val")) if fmt is not None else "bullet"
            abstract[item.get(q("w", "abstractNumId"))] = levels
        for num in num_tree.findall(q("w", "num")):
            ref = num.find(q("w", "abstractNumId"))
            if ref is not None:
                numbering[num.get(q("w", "numId"))] = abstract.get(ref.get(q("w", "val")), {})
    counters = {}
    images = {}

    def run_html(run, link=None):
        rpr = run.find(q("w", "rPr"))
        css, wrap = [], []
        if rpr is not None:
            if rpr.find(q("w", "b")) is not None and rpr.find(q("w", "b")).get(q("w", "val")) not in ("0", "false"):
                wrap.append("b")
            if rpr.find(q("w", "i")) is not None and rpr.find(q("w", "i")).get(q("w", "val")) not in ("0", "false"):
                wrap.append("i")
            if rpr.find(q("w", "u")) is not None and rpr.find(q("w", "u")).get(q("w", "val")) not in ("none", None):
                wrap.append("u")
            color = rpr.find(q("w", "color"))
            if color is not None and re.fullmatch(r"[0-9A-Fa-f]{6}", color.get(q("w", "val"), "")):
                css.append(f"color:#{color.get(q('w', 'val'))}")
            size = rpr.find(q("w", "sz"))
            if size is not None:
                css.append(f"font-size:{int(size.get(q('w', 'val'), 22)) / 2}pt")
            fonts = rpr.find(q("w", "rFonts"))
            if fonts is not None and fonts.get(q("w", "ascii")):
                css.append(f"font-family:{family_for(fonts.get(q('w', 'ascii')))}")
            vert = rpr.find(q("w", "vertAlign"))
            if vert is not None and vert.get(q("w", "val")) in ("superscript", "subscript"):
                wrap.append("sup" if vert.get(q("w", "val")) == "superscript" else "sub")
        parts = []
        for child in run:
            tag = child.tag
            if tag == q("w", "t"):
                parts.append(escape(child.text or ""))
            elif tag == q("w", "tab"):
                parts.append("&#160;&#160;&#160;&#160;")
            elif tag == q("w", "br"):
                parts.append("<!--PAGEBREAK-->" if child.get(q("w", "type")) == "page" else "<br/>")
            elif tag == q("w", "drawing"):
                blip = child.find(f".//{q('a', 'blip')}")
                extent = child.find(f".//{q('wp', 'extent')}")
                rid = blip.get(q("r", "embed")) if blip is not None else None
                if rid in rels and not rels[rid][2]:
                    target = rels[rid][0]
                    if target not in images:
                        content = pkg.read(target)
                        if content:
                            name = f"img{len(images)}{posixpath.splitext(target)[1].lower()}"
                            archive.add(content, name)
                            images[target] = name
                    if target in images:
                        w = int(extent.get("cx", 0)) / EMU if extent is not None else 200
                        h = int(extent.get("cy", 0)) / EMU if extent is not None else 150
                        parts.append(f'<img src="{images[target]}" style="width:{w:.1f}pt;height:{h:.1f}pt"/>')
        html = "".join(parts)
        for tag in wrap:
            html = f"<{tag}>{html}</{tag}>"
        if css:
            html = f'<span style="{";".join(css)}">{html}</span>'
        if link:
            html = f'<a href="{escape(link)}">{html}</a>'
        return html

    def paragraph_html(par):
        ppr = par.find(q("w", "pPr"))
        tag, css, prefix = "p", [], ""
        if ppr is not None:
            style_ref = ppr.find(q("w", "pStyle"))
            style = styles.get(style_ref.get(q("w", "val")) if style_ref is not None else None, {})
            if style.get("heading"):
                tag = f"h{style['heading']}"
            if style.get("size"):
                css.append(f"font-size:{style['size']}pt")
            jc = ppr.find(q("w", "jc"))
            if jc is not None:
                align = {"center": "center", "right": "right", "end": "right", "both": "justify"}.get(jc.get(q("w", "val")))
                if align:
                    css.append(f"text-align:{align}")
            spacing = ppr.find(q("w", "spacing"))
            if spacing is not None:
                if spacing.get(q("w", "after")):
                    css.append(f"margin-bottom:{int(spacing.get(q('w', 'after'))) / 20}pt")
                if spacing.get(q("w", "before")):
                    css.append(f"margin-top:{int(spacing.get(q('w', 'before'))) / 20}pt")
            ind = ppr.find(q("w", "ind"))
            indent = int(ind.get(q("w", "left"), ind.get(q("w", "start"), 0)) or 0) / 20 if ind is not None else 0
            num = ppr.find(q("w", "numPr"))
            if num is not None and num.find(q("w", "numId")) is not None:
                num_id = num.find(q("w", "numId")).get(q("w", "val"))
                level = int(num.find(q("w", "ilvl")).get(q("w", "val"), 0)) if num.find(q("w", "ilvl")) is not None else 0
                fmt = numbering.get(num_id, {}).get(level, "bullet")
                key = (num_id, level)
                counters[key] = counters.get(key, 0) + 1
                for other in list(counters):
                    if other[0] == num_id and other[1] > level:
                        del counters[other]
                prefix = ("•" if fmt in ("bullet", "none") else f"{counters[key]}.") + "&#160;&#160;"
                indent = indent or 18 * (level + 1)
            if indent:
                css.append(f"margin-left:{indent:.1f}pt")
        body = []
        for child in par:
            if child.tag == q("w", "r"):
                body.append(run_html(child))
            elif child.tag == q("w", "hyperlink"):
                rid = child.get(q("r", "id"))
                link = rels[rid][0] if rid in rels and rels[rid][2] else None
                body.extend(run_html(r, link) for r in child.findall(q("w", "r")))
        content = prefix + "".join(body)
        style = f' style="{";".join(css)}"' if css else ""
        return f"<{tag}{style}>{content or '&#160;'}</{tag}>"

    def table_html(table):
        rows = []
        for tr in table.findall(q("w", "tr")):
            cells = []
            for tc in tr.findall(q("w", "tc")):
                tcpr = tc.find(q("w", "tcPr"))
                span = tcpr.find(q("w", "gridSpan")) if tcpr is not None else None
                merge = tcpr.find(q("w", "vMerge")) if tcpr is not None else None
                if merge is not None and merge.get(q("w", "val")) != "restart":
                    cells.append("<td></td>")
                    continue
                inner = "".join(paragraph_html(p) if p.tag == q("w", "p") else table_html(p) for p in tc
                                if p.tag in (q("w", "p"), q("w", "tbl")))
                colspan = f' colspan="{span.get(q("w", "val"))}"' if span is not None else ""
                cells.append(f"<td{colspan}>{inner}</td>")
            rows.append(f"<tr>{''.join(cells)}</tr>")
        return f'<table style="width:100%">{"".join(rows)}</table>'

    body = document.find(q("w", "body"))
    html, width, height, margins = [], 612.0, 792.0, (72, 72, 72, 72)
    for child in body:
        if child.tag == q("w", "p"):
            html.append(paragraph_html(child))
        elif child.tag == q("w", "tbl"):
            html.append(table_html(child))
        elif child.tag == q("w", "sectPr"):
            size = child.find(q("w", "pgSz"))
            if size is not None:
                width = int(size.get(q("w", "w"), 12240)) / 20
                height = int(size.get(q("w", "h"), 15840)) / 20
            mar = child.find(q("w", "pgMar"))
            if mar is not None:
                margins = tuple(max(18, int(mar.get(q("w", k), 1440)) / 20) for k in ("top", "right", "bottom", "left"))
    chunks = "".join(html).split("<!--PAGEBREAK-->")
    css = BASE_CSS.replace("11pt", f"{default_size:g}pt")
    return render_html([f"<body>{c}</body>" for c in chunks], width, height, margins, archive, css)


def excel_value(raw, kind, fmt_code):
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE"
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return raw or ""
    code = (fmt_code or "").lower()
    if code and re.search(r"[dmyh]", re.sub(r'"[^"]*"|\[[^\]]*\]', "", code)) and 0 < number < 2958466:
        moment = datetime(1899, 12, 30) + timedelta(days=number)
        has_time = "h" in code or ("s" in code and "ss" in code)
        has_date = any(k in code for k in ("d", "y")) or ("m" in code and "h" not in code)
        if has_date and has_time:
            return moment.strftime("%Y-%m-%d %H:%M")
        return moment.strftime("%H:%M:%S" if has_time else "%Y-%m-%d")
    if "%" in code:
        decimals = len(code.split(".")[1].split("%")[0]) if "." in code else 0
        return f"{number * 100:.{decimals}f}%"
    if code and "0.00" in code:
        text = f"{number:,.2f}" if "," in code else f"{number:.2f}"
        return text
    if number.is_integer() and abs(number) < 1e15:
        return f"{int(number):,}" if "#,##" in code else str(int(number))
    return f"{number:.10g}"


BUILTIN_FORMATS = {9: "0%", 10: "0.00%", 14: "yyyy-mm-dd", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy", 18: "h:mm AM/PM",
                   19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "yyyy-mm-dd h:mm", 2: "0.00", 3: "#,##0", 4: "#,##0.00"}


def cell_index(ref):
    match = re.match(r"([A-Z]+)(\d+)", ref or "")
    if not match:
        return None
    col = 0
    for ch in match.group(1):
        col = col * 26 + ord(ch) - 64
    return int(match.group(2)) - 1, col - 1


def xlsx_to_pdf(data):
    pkg = Package(data)
    workbook = pkg.xml("xl/workbook.xml")
    if workbook is None:
        raise ValueError("no workbook")
    rels = pkg.rels("xl/workbook.xml")
    shared = []
    sst = pkg.xml("xl/sharedStrings.xml")
    if sst is not None:
        for si in sst.findall(q("s", "si")):
            shared.append("".join(t.text or "" for t in si.iter(q("s", "t"))))
    formats, xfs = dict(BUILTIN_FORMATS), []
    style_tree = pkg.xml("xl/styles.xml")
    bold_fonts, fills = set(), []
    if style_tree is not None:
        for fmt in style_tree.iter(q("s", "numFmt")):
            formats[int(fmt.get("numFmtId"))] = fmt.get("formatCode", "")
        fonts = style_tree.find(q("s", "fonts"))
        for i, font in enumerate(fonts if fonts is not None else []):
            if font.find(q("s", "b")) is not None:
                bold_fonts.add(i)
        fill_list = style_tree.find(q("s", "fills"))
        for fill in fill_list if fill_list is not None else []:
            color = fill.find(f".//{q('s', 'fgColor')}")
            rgb = color.get("rgb") if color is not None else None
            fills.append(rgb[-6:] if rgb and len(rgb) >= 6 and fill.find(q("s", "patternFill")) is not None
                         and fill.find(q("s", "patternFill")).get("patternType") == "solid" else None)
        cell_xfs = style_tree.find(q("s", "cellXfs"))
        for xf in cell_xfs if cell_xfs is not None else []:
            align = xf.find(q("s", "alignment"))
            xfs.append({"fmt": int(xf.get("numFmtId", 0)), "bold": int(xf.get("fontId", 0)) in bold_fonts,
                        "fill": fills[int(xf.get("fillId", 0))] if int(xf.get("fillId", 0)) < len(fills) else None,
                        "align": align.get("horizontal") if align is not None else None})
    chunks, widest = [], 0.0
    for sheet in workbook.iter(q("s", "sheet")):
        if sheet.get("state") == "hidden":
            continue
        rid = sheet.get(q("r", "id"))
        if rid not in rels:
            continue
        tree = pkg.xml(rels[rid][0])
        if tree is None:
            continue
        grid, max_col = {}, -1
        for row in tree.iter(q("s", "row")):
            if row.get("hidden") == "1":
                continue
            for cell in row.findall(q("s", "c")):
                pos = cell_index(cell.get("r"))
                if pos is None:
                    continue
                kind = cell.get("t", "n")
                style = xfs[int(cell.get("s", 0))] if int(cell.get("s", 0)) < len(xfs) else {"fmt": 0}
                value_node = cell.find(q("s", "v"))
                raw = value_node.text if value_node is not None else None
                if kind == "s" and raw is not None:
                    text = shared[int(raw)] if int(raw) < len(shared) else ""
                elif kind == "inlineStr":
                    text = "".join(t.text or "" for t in cell.iter(q("s", "t")))
                elif kind in ("str", "e"):
                    text = raw or ""
                else:
                    text = excel_value(raw, kind, formats.get(style.get("fmt", 0), "")) if raw is not None else ""
                if text != "" or style.get("fill"):
                    grid[pos] = (text, style, kind)
                    max_col = max(max_col, pos[1])
        if not grid:
            continue
        widths = {}
        for col in tree.iter(q("s", "col")):
            for c in range(int(col.get("min", 1)) - 1, min(int(col.get("max", 1)), max_col + 1)):
                widths[c] = float(col.get("width", 9)) * 5.25
        merged, covered = {}, set()
        for merge in tree.iter(q("s", "mergeCell")):
            a, _, b = merge.get("ref", "").partition(":")
            start, end = cell_index(a), cell_index(b)
            if start and end:
                merged[start] = (end[0] - start[0] + 1, end[1] - start[1] + 1)
                covered |= {(r, c) for r in range(start[0], end[0] + 1) for c in range(start[1], end[1] + 1)} - {start}
        max_row = max(r for r, _ in grid)
        col_widths = [widths.get(c, 48.0) for c in range(max_col + 1)]
        widest = max(widest, sum(col_widths))
        rows = []
        for r in range(max_row + 1):
            cells = []
            for c in range(max_col + 1):
                if (r, c) in covered:
                    continue
                text, style, kind = grid.get((r, c), ("", {}, ""))
                css = [f"width:{col_widths[c]:.0f}pt"]
                if style.get("bold"):
                    css.append("font-weight:bold")
                if style.get("fill"):
                    css.append(f"background-color:#{style['fill']}")
                align = style.get("align") or ("right" if kind == "n" and text and re.match(r"^[-\d.,%: ]+$", text) else None)
                if align in ("center", "right"):
                    css.append(f"text-align:{align}")
                span = ""
                if (r, c) in merged:
                    rs, cs = merged[(r, c)]
                    span = (f' rowspan="{rs}"' if rs > 1 else "") + (f' colspan="{cs}"' if cs > 1 else "")
                cells.append(f'<td{span} style="{";".join(css)}">{escape(text) or "&#160;"}</td>')
            rows.append(f"<tr>{''.join(cells)}</tr>")
        chunks.append(f'<h3>{escape(sheet.get("name", ""))}</h3><table>{"".join(rows)}</table>')
    if not chunks:
        raise ValueError("empty workbook")
    landscape = widest > 540
    width, height = (842.0, 595.0) if landscape else (595.0, 842.0)
    usable = width - 72
    scale = min(1.0, usable / widest) if widest else 1.0
    size = max(5.0, 9 * scale)
    css = BASE_CSS + f" td{{font-size:{size:.1f}pt;padding:1pt 2pt}} h3{{font-size:12pt}}"
    return render_html([f"<body>{c}</body>" for c in chunks], width, height, (36, 36, 36, 36), None, css)


# ---------- PowerPoint ----------

SCHEME_MAP = {"tx1": "dk1", "bg1": "lt1", "tx2": "dk2", "bg2": "lt2"}


def pptx_to_pdf(data):
    pkg = Package(data)
    presentation = pkg.xml("ppt/presentation.xml")
    if presentation is None:
        raise ValueError("no presentation")
    size = presentation.find(q("p", "sldSz"))
    width = int(size.get("cx", 9144000)) / EMU if size is not None else 720
    height = int(size.get("cy", 6858000)) / EMU if size is not None else 540
    rels = pkg.rels("ppt/presentation.xml")
    theme = {}
    theme_part = next((t for t, kind, _ in rels.values() if kind == "theme"), None)
    tree = pkg.xml(theme_part) if theme_part else None
    if tree is not None:
        scheme = tree.find(f".//{q('a', 'clrScheme')}")
        for entry in scheme if scheme is not None else []:
            name = entry.tag.split("}")[1]
            srgb = entry.find(q("a", "srgbClr"))
            sys_clr = entry.find(q("a", "sysClr"))
            theme[name] = srgb.get("val") if srgb is not None else (sys_clr.get("lastClr") if sys_clr is not None else None)

    def color_of(node):
        if node is None:
            return None
        srgb = node.find(q("a", "srgbClr"))
        if srgb is not None:
            return srgb.get("val")
        scheme = node.find(q("a", "schemeClr"))
        if scheme is not None:
            return theme.get(SCHEME_MAP.get(scheme.get("val"), scheme.get("val")))
        return None

    def rgb(value):
        return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)) if value and len(value) == 6 else None

    def placeholders(part):
        found = {}
        tree = pkg.xml(part)
        if tree is None:
            return found, tree
        for shape in tree.iter(q("p", "sp")):
            ph = shape.find(f".//{q('p', 'ph')}")
            xfrm = shape.find(f"{q('p', 'spPr')}/{q('a', 'xfrm')}")
            if ph is not None and xfrm is not None:
                found[("idx", ph.get("idx"))] = xfrm
                found[("type", ph.get("type", "body"))] = xfrm
        return found, tree

    def background(tree):
        if tree is None:
            return None
        bg = tree.find(f".//{q('p', 'bg')}")
        if bg is None:
            return None
        fill = bg.find(f".//{q('a', 'solidFill')}")
        return color_of(fill) if fill is not None else None

    out = pdf.open()
    slide_ids = presentation.find(q("p", "sldIdLst"))
    for sld in slide_ids if slide_ids is not None else []:
        rid = sld.get(q("r", "id"))
        if rid not in rels:
            continue
        part = rels[rid][0]
        slide = pkg.xml(part)
        if slide is None or slide.get("show") == "0":
            continue
        srels = pkg.rels(part)
        layout_part = next((t for t, kind, _ in srels.values() if kind == "slideLayout"), None)
        layout_ph, layout_tree = placeholders(layout_part) if layout_part else ({}, None)
        master_part = next((t for t, kind, _ in pkg.rels(layout_part).values() if kind == "slideMaster"), None) if layout_part else None
        master_ph, master_tree = placeholders(master_part) if master_part else ({}, None)
        page = out.new_page(width=width, height=height)
        fill = background(slide) or background(layout_tree) or background(master_tree)
        if fill and rgb(fill):
            page.draw_rect(page.rect, color=None, fill=rgb(fill))
        blip_bg = slide.find(f".//{q('p', 'bg')}//{q('a', 'blip')}")
        if blip_bg is not None and blip_bg.get(q("r", "embed")) in srels:
            content = pkg.read(srels[blip_bg.get(q("r", "embed"))][0])
            if content:
                try:
                    page.insert_image(page.rect, stream=content, keep_proportion=False)
                except (ValueError, RuntimeError):
                    pass

        def frame(shape):
            xfrm = shape.find(f"{q('p', 'spPr')}/{q('a', 'xfrm')}")
            if xfrm is None:
                xfrm = shape.find(q("p", "xfrm"))
            if xfrm is None:
                ph = shape.find(f".//{q('p', 'ph')}")
                if ph is not None:
                    for source in (layout_ph, master_ph):
                        xfrm = source.get(("idx", ph.get("idx"))) if ph.get("idx") else None
                        xfrm = xfrm if xfrm is not None else source.get(("type", ph.get("type", "body")))
                        if xfrm is not None:
                            break
            if xfrm is None:
                return None
            off, ext = xfrm.find(q("a", "off")), xfrm.find(q("a", "ext"))
            if off is None or ext is None:
                return None
            x0, y0 = int(off.get("x", 0)) / EMU, int(off.get("y", 0)) / EMU
            return pdf.Rect(x0, y0, x0 + int(ext.get("cx", 0)) / EMU, y0 + int(ext.get("cy", 0)) / EMU)

        for shape in slide.iter():
            tag = shape.tag
            if tag == q("p", "sp"):
                rect = frame(shape)
                if rect is None or rect.is_empty:
                    continue
                sppr = shape.find(q("p", "spPr"))
                geometry = sppr.find(q("a", "prstGeom")) if sppr is not None else None
                fill_node = sppr.find(q("a", "solidFill")) if sppr is not None else None
                line = sppr.find(q("a", "ln")) if sppr is not None else None
                fill_rgb = rgb(color_of(fill_node))
                line_rgb = rgb(color_of(line.find(q("a", "solidFill")))) if line is not None and line.find(q("a", "solidFill")) is not None else None
                if fill_rgb or line_rgb:
                    kind = geometry.get("prst") if geometry is not None else "rect"
                    if kind == "ellipse":
                        page.draw_oval(rect, color=line_rgb, fill=fill_rgb, width=1)
                    else:
                        page.draw_rect(rect, color=line_rgb, fill=fill_rgb, width=1, radius=0.1 if kind == "roundRect" else None)
                body = shape.find(q("p", "txBody"))
                if body is None:
                    continue
                ph = shape.find(f".//{q('p', 'ph')}")
                kind = ph.get("type", "body") if ph is not None else None
                default = 40 if kind in ("title", "ctrTitle") else 24 if kind in ("body", "subTitle", "obj") or (ph is not None) else 18
                paragraphs = []
                for par in body.findall(q("a", "p")):
                    ppr = par.find(q("a", "pPr"))
                    align = {"ctr": "center", "r": "right", "just": "justify"}.get(ppr.get("algn") if ppr is not None else None, "left")
                    if kind in ("title", "ctrTitle", "subTitle") and ppr is None and kind != "title":
                        align = "center"
                    bullet = ""
                    if ppr is not None and ppr.find(q("a", "buChar")) is not None:
                        bullet = escape(ppr.find(q("a", "buChar")).get("char", "•")) + "&#160;"
                    elif kind in ("body", "obj") and ppr is None:
                        bullet = "•&#160;"
                    runs = []
                    for node in par:
                        if node.tag == q("a", "r"):
                            rpr = node.find(q("a", "rPr"))
                            text = escape(node.findtext(q("a", "t")) or "")
                            css = []
                            sz = rpr.get("sz") if rpr is not None else None
                            css.append(f"font-size:{int(sz) / 100 if sz else default}pt")
                            if rpr is not None:
                                if rpr.get("b") == "1":
                                    css.append("font-weight:bold")
                                if rpr.get("i") == "1":
                                    css.append("font-style:italic")
                                c = rgb(color_of(rpr.find(q("a", "solidFill"))))
                                if c:
                                    css.append("color:#%02x%02x%02x" % tuple(round(v * 255) for v in c))
                                latin = rpr.find(q("a", "latin"))
                                if latin is not None:
                                    css.append(f"font-family:{family_for(latin.get('typeface'))}")
                            runs.append(f'<span style="{";".join(css)}">{text}</span>')
                        elif node.tag == q("a", "br"):
                            runs.append("<br/>")
                    if runs:
                        paragraphs.append(f'<p style="text-align:{align};margin:0 0 4pt 0">{bullet}{"".join(runs)}</p>')
                    else:
                        paragraphs.append(f'<p style="margin:0;font-size:{default * 0.6}pt">&#160;</p>')
                if any("<span" in p for p in paragraphs):
                    try:
                        page.insert_htmlbox(rect + (4, 3, -4, -3), "".join(paragraphs), scale_low=0.25,
                                            css="body{font-family:sans-serif;line-height:1.15}")
                    except (ValueError, RuntimeError):
                        pass
            elif tag == q("p", "pic"):
                rect = frame(shape)
                blip = shape.find(f".//{q('a', 'blip')}")
                if rect is None or blip is None or blip.get(q("r", "embed")) not in srels:
                    continue
                content = pkg.read(srels[blip.get(q("r", "embed"))][0])
                if content:
                    try:
                        page.insert_image(rect, stream=content, keep_proportion=False)
                    except (ValueError, RuntimeError):
                        pass
            elif tag == q("p", "graphicFrame"):
                rect = frame(shape)
                table = shape.find(f".//{q('a', 'tbl')}")
                if rect is None or table is None:
                    continue
                rows = []
                for tr in table.findall(q("a", "tr")):
                    cells = "".join(f"<td>{escape(''.join(t.text or '' for t in tc.iter(q('a', 't'))))}</td>" for tc in tr.findall(q("a", "tc")))
                    rows.append(f"<tr>{cells}</tr>")
                try:
                    page.insert_htmlbox(rect, f'<table style="width:100%">{"".join(rows)}</table>', scale_low=0.25,
                                        css="td{border:0.5pt solid #888;padding:2pt 4pt;font-size:14pt} table{border-collapse:collapse}")
                except (ValueError, RuntimeError):
                    pass
    if not out.page_count:
        raise ValueError("no slides")
    return out.tobytes(garbage=3, deflate=True)
