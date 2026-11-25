"""Build the standalone, browser-only GitHub Pages distribution."""
from pathlib import Path
import shutil

from install_mupdf_js import FILES, VERSION, main as install_engine

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
OUTPUT = ROOT / "dist" / "pages"


def main():
    install_engine()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = (WEB / "index.html").read_text()
    start = source.index('<section id="large-pdf"')
    end = source.index("</section>", start) + len("</section>")
    template = (ROOT / "pages" / "index.html").read_text()
    (OUTPUT / "index.html").write_text(template.replace("<!-- LARGE_PDF_FORM -->", source[start:end]))
    for name in ("icon-192.png", "style.css", "large-pdf.js", "large-pdf-worker.js"):
        shutil.copyfile(WEB / name, OUTPUT / name)
    vendor = Path("vendor") / f"mupdf-{VERSION}"
    (OUTPUT / vendor).mkdir(parents=True, exist_ok=True)
    for name in (*FILES, "LICENSE"):
        shutil.copyfile(WEB / vendor / name, OUTPUT / vendor / name)


if __name__ == "__main__":
    main()
