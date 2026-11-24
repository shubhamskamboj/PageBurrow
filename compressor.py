"""PDF optimization and optional A4 page fitting."""
from dataclasses import dataclass
from io import BytesIO
from struct import unpack_from

import pymupdf as fitz
from PIL import Image

A4 = (210 * 72 / 25.4, 297 * 72 / 25.4)
MIN_JPEG_QUALITY = 60
MAX_JPEG_QUALITY = 95


@dataclass
class Result:
    data: bytes
    pages: int
    jpeg_quality: int | None = None


def save_pdf(doc):
    return doc.tobytes(garbage=3, deflate=True, use_objstms=1)


def equal_size(actual, expected):
    return all(abs(x - y) < 0.1 for x, y in zip(actual, expected))


def fit_to_a4(doc):
    """Scale the visible PDF content without rasterizing the page."""
    resize = []
    for page in doc:
        width, height = A4 if page.rect.width <= page.rect.height else A4[::-1]
        media_size = (page.mediabox.width, page.mediabox.height)
        if page.rotation in (90, 270):
            media_size = media_size[::-1]
        if not equal_size((page.rect.width, page.rect.height), (width, height)) or not equal_size(media_size, (width, height)):
            resize.append((page.number, width, height))

    if not resize:
        return False
    if doc.is_form_pdf or doc.get_toc() or any(page.first_annot or page.first_link for page in doc):
        raise ValueError('A4 resizing is unavailable for PDFs with links, bookmarks, forms, or annotations. Choose Original page size to preserve them.')

    for number, width, height in resize:
        page = doc[number]
        if doc.xref_get_key(page.xref, 'UserUnit')[1] not in ('null', '1'):
            raise ValueError('This PDF uses a custom page scale. Choose Original page size.')
        rotation = page.rotation
        crop = page.cropbox
        left, bottom = crop.x0, page.mediabox.y1 - crop.y1
        cw, ch = crop.width, crop.height
        if rotation not in (0, 90, 180, 270) or min(cw, ch) <= 0:
            raise ValueError('The PDF has unsupported page geometry. Choose Original page size.')
        vw, vh = (ch, cw) if rotation in (90, 270) else (cw, ch)
        if not equal_size((page.rect.width, page.rect.height), (vw, vh)):
            raise ValueError('The PDF has unsupported page geometry. Choose Original page size.')
        a, b, c, d, e, f = {
            0: (1, 0, 0, 1, -left, -bottom),
            90: (0, -1, 1, 0, -bottom, left + cw),
            180: (-1, 0, 0, -1, left + cw, bottom + ch),
            270: (0, 1, -1, 0, bottom + ch, -left),
        }[rotation]
        scale = min(width / vw, height / vh)
        offset_x = (width - scale * vw) / 2
        offset_y = (height - scale * vh) / 2
        matrix = (a * scale, b * scale, c * scale, d * scale, e * scale + offset_x, f * scale + offset_y)
        contents = page.get_contents()
        if contents:
            numbers = ' '.join(f'{x:.12f}' for x in matrix)
            setup = f'q\n{numbers} cm\n{left:.8f} {bottom:.8f} {cw:.8f} {ch:.8f} re W n\n'
            streams = []
            for data in (setup.encode('ascii'), b'\nQ\n'):
                xref = doc.get_new_xref()
                doc.update_object(xref, '<<>>')
                doc.update_stream(xref, data)
                streams.append(xref)
            before, after = streams
            refs = ' '.join(f'{xref} 0 R' for xref in [before, *contents, after])
            doc.xref_set_key(page.xref, 'Contents', f'[{refs}]')
        page.set_rotation(0)
        page.set_mediabox(fitz.Rect(0, 0, width, height))
        doc.xref_set_key(page.xref, 'CropBox', f'[0 0 {width:.10f} {height:.10f}]')
    return True


def image_info(doc, xref):
    """Select ordinary opaque 8-bit image objects with known PDF color semantics."""
    def value(key):
        return doc.xref_get_key(xref, key)[1]

    if not doc.xref_is_stream(xref) or value('Subtype') != '/Image':
        return None
    color = value('ColorSpace')
    method = value('Filter')
    if color not in ('/DeviceRGB', '/DeviceGray') or value('BitsPerComponent') != '8':
        return None
    if method not in ('/DCTDecode', '/FlateDecode', 'null'):
        return None
    if value('ImageMask') not in ('false', 'null') or value('SMaskInData') not in ('0', 'null'):
        return None
    if any(value(key) != 'null' for key in ('Decode', 'Mask', 'SMask')):
        return None
    # Only handle predictor parameters written by this tool or an unparameterized stream.
    params = value('DecodeParms')
    if params != 'null':
        mode = 'RGB' if color == '/DeviceRGB' else 'L'
        cols = value('Width')
        expected = f'<</Predictor 15/Colors {len(mode)}/BitsPerComponent 8/Columns {cols}>>'
        if method != '/FlateDecode' or ''.join(params.split()) != ''.join(expected.split()):
            return None
    width, height = int(value('Width')), int(value('Height'))
    if width < 1 or height < 1 or width * height > 40_000_000:
        return None
    return method, 'RGB' if color == '/DeviceRGB' else 'L', (width, height)


def read_image(doc, xref, info):
    method, mode, size = info
    data = doc.xref_stream(xref)
    if method == '/DCTDecode':
        with Image.open(BytesIO(data)) as image:
            if image.mode != mode or image.size != size:
                return None
            return image.copy()
    if len(data) != size[0] * size[1] * len(mode):
        return None
    return Image.frombytes(mode, size, data)


def png_predictor(image):
    """Extract the PNG predictor and zlib data, which PDF can store directly."""
    output = BytesIO()
    image.save(output, format='PNG', compress_level=5)
    data = output.getbuffer()
    pos = 8
    chunks = []
    while pos < len(data):
        size, kind = unpack_from('>I4s', data, pos)
        if kind == b'IDAT':
            chunks.append(data[pos + 8:pos + 8 + size])
        pos += size + 12
    return b''.join(chunks)


def optimize_images(doc, quality=None):
    changed = 0
    for xref in range(1, doc.xref_length()):
        info = image_info(doc, xref)
        if info is None or (quality is None and info[0] == '/DCTDecode'):
            continue
        try:
            image = read_image(doc, xref, info)
        except (OSError, RuntimeError, ValueError):
            continue
        if image is None:
            continue
        with image:
            if quality is None:
                data = png_predictor(image)
                params = f'<</Predictor 15 /Colors {len(image.mode)} /BitsPerComponent 8 /Columns {image.width}>>'
                method = '/FlateDecode'
            else:
                output = BytesIO()
                image.save(output, format='JPEG', quality=quality, subsampling=0, optimize=True)
                data = output.getvalue()
                params = 'null'
                method = '/DCTDecode'
        if len(data) + 128 >= len(doc.xref_stream_raw(xref)):
            continue
        doc.update_stream(xref, data, compress=False)
        doc.xref_set_key(xref, 'Filter', method)
        doc.xref_set_key(xref, 'DecodeParms', params)
        changed += 1
    return changed


def compress_pdf(source, target_bytes, a4, allow_jpeg):
    with fitz.open(stream=source, filetype='pdf') as doc:
        if not doc.is_pdf or doc.page_count == 0:
            raise ValueError('Choose a PDF that contains at least one page.')
        if doc.needs_pass or doc.is_encrypted:
            raise ValueError('This PDF is password-protected. Open and save an unlocked copy first.')
        if doc.get_sigflags() in (1, 2, 3):
            raise ValueError('This PDF contains signature fields. Compression could invalidate a digital signature.')
        pages = doc.page_count
        resized = fit_to_a4(doc) if a4 else False
        if not resized and len(source) <= target_bytes:
            return Result(source, pages)
        base = save_pdf(doc)
        best = base if resized or len(base) < len(source) else source
        if len(best) <= target_bytes:
            return Result(best, pages)
        if optimize_images(doc):
            lossless = save_pdf(doc)
            if len(lossless) < len(best):
                best = lossless

    if len(best) <= target_bytes or not allow_jpeg:
        return Result(best, pages)

    def encode(quality):
        with fitz.open(stream=base, filetype='pdf') as candidate:
            if optimize_images(candidate, quality):
                return save_pdf(candidate)
        return None

    low, high = MIN_JPEG_QUALITY, MAX_JPEG_QUALITY
    smallest = encode(low)
    if smallest is None or len(smallest) >= len(best):
        return Result(best, pages)
    result = Result(smallest, pages, low)
    if len(smallest) > target_bytes:
        return result
    while low < high:
        quality = (low + high + 1) // 2
        data = encode(quality)
        if data is not None and len(data) <= target_bytes:
            low = quality
            result = Result(data, pages, quality)
        else:
            high = quality - 1
    return result
