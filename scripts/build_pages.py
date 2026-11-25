"""Build the standalone, browser-only GitHub Pages distribution."""
from pathlib import Path
import shutil
import json

from browser_runtime import build_runtime

from install_mupdf_js import FILES, VERSION, main as install_engine

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
OUTPUT = ROOT / "dist" / "pages"


def main():
    install_engine()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = (WEB / "index.html").read_text()
    source = source.replace('href="/', 'href="./').replace('src="/', 'src="./')
    source = source.replace('<script src="./preview.js"', '<script src="./toolbox-client.js" defer></script>\n  <script src="./large-pdf.js" defer></script>\n  <script src="./preview.js"')
    source = source.replace('<main id="welcome"', '<p id="engine-status" class="engine-status" role="status" hidden></p>\n  <main id="welcome"')
    source = source.replace("Every PDF tool, on your own device", "Your PDF toolbox")
    source = source.replace("Your files are never uploaded to the internet, there are no limits, and it works offline.", "Files up to 200 MB are processed in your browser.")
    source = source.replace("● Works offline · Files stay on your device", '<a href="https://github.com/shubhamskamboj/PageBurrow">Source code</a> · Files stay on your device')
    (OUTPUT / "index.html").write_text(source)
    manifest = json.loads((WEB / "manifest.webmanifest").read_text())
    manifest.update(start_url="./", scope="./")
    for icon in manifest["icons"]:
        icon["src"] = "." + icon["src"]
    (OUTPUT / "manifest.webmanifest").write_text(json.dumps(manifest))
    for file in WEB.iterdir():
        if file.suffix in {".js", ".css", ".png"}:
            shutil.copyfile(file, OUTPUT / file.name)
    for name in ("toolbox-client.js", "toolbox-worker.js"):
        shutil.copyfile(ROOT / "pages" / name, OUTPUT / name)
    build_runtime(ROOT, OUTPUT)
    vendor = Path("vendor") / f"mupdf-{VERSION}"
    (OUTPUT / vendor).mkdir(parents=True, exist_ok=True)
    for name in (*FILES, "LICENSE"):
        shutil.copyfile(WEB / vendor / name, OUTPUT / vendor / name)


if __name__ == "__main__":
    main()
