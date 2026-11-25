"""Copy verified browser runtime dependencies and package the PDF toolbox."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_DEFLATED

PYODIDE = "0.29.3"
WHEEL = "pymupdf-1.26.7-cp313-none-pyodide_2025_0_wasm32.whl"
PACKAGES = ["pillow", "hashlib", "sqlite3", "lzma"]


def download(url, digest, cache):
    path = cache / url.rsplit("/", 1)[-1]
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
        return path
    with urlopen(url, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"Unexpected checksum for {path.name}")
    path.write_bytes(data)
    return path


def build_runtime(root, output):
    destination = output / "runtime"
    destination.mkdir(exist_ok=True)
    cache = root / "build" / "browser-dependencies"
    cache.mkdir(parents=True, exist_ok=True)
    archive = download(f"https://registry.npmjs.org/pyodide/-/pyodide-{PYODIDE}.tgz",
                       "924f3167d6bf5e553bda392615eaa82edd82a9cffc32a1cc49853a926b148c5c", cache)
    with tarfile.open(archive) as tar:
        for name in ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "pyodide-lock.json", "python_stdlib.zip"]:
            (destination / name).write_bytes(tar.extractfile("package/" + name).read())
    lock = json.loads((destination / "pyodide-lock.json").read_text())["packages"]
    required = set()

    def include(name):
        if name not in required:
            required.add(name)
            for dep in lock[name]["depends"]:
                include(dep)

    for name in PACKAGES:
        include(name)

    def install(name):
        info = lock[name]
        url = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE}/full/{info['file_name']}"
        shutil.copyfile(download(url, info["sha256"], cache), destination / info["file_name"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(install, sorted(required)))
    ocr = download("https://registry.npmjs.org/tesseract.js-core/-/tesseract.js-core-6.1.2.tgz",
                   "1b5863e7d912de9fc639222a38ede7876b2344565f8ad8d9527b242b0d793e24", cache)
    with tarfile.open(ocr) as tar:
        for name in ["tesseract-core-lstm.js", "tesseract-core-lstm.wasm", "LICENSE"]:
            target = "TESSERACT-LICENSE" if name == "LICENSE" else name
            (destination / target).write_bytes(tar.extractfile("package/" + name).read())
    wheel = download(f"https://ghostscript.com/~julian/pyodide/{WHEEL}",
                     "875fc2ad84903c8386d595baec4c10773e57fc09949736f3ed0e9844e83c5c6e", cache)
    shutil.copyfile(wheel, destination / WHEEL)
    with ZipFile(destination / "toolbox.zip", "w", ZIP_DEFLATED) as bundle:
        for file in [root / name for name in ["app.py", "editor.py", "compressor.py", "COPYING"]] + sorted((root / "pdftools").glob("*.py")):
            bundle.write(file, file.relative_to(root))
        bundle.write(root / "pages" / "local_engine.py", "local_engine.py")
        bundle.write(root / "pages" / "srgb.icc", "srgb.icc")
        for file in sorted((root / "tessdata").glob("*.traineddata")):
            bundle.write(file, "tessdata/" + file.name)
    languages = output / "languages"
    languages.mkdir(exist_ok=True)
    for file in sorted((root / "build" / "ocr-languages").glob("*.traineddata")):
        if not (root / "tessdata" / file.name).exists():
            shutil.copyfile(file, languages / file.name)
    (destination / "engine.json").write_text(json.dumps({
        "wheel": WHEEL, "packages": PACKAGES,
        "languages": sorted(file.stem for file in languages.glob("*.traineddata")),
    }))
