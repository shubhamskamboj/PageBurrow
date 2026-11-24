"""Install the pinned MuPDF.js browser runtime into the container."""
import base64
import hashlib
import io
from pathlib import Path
import tarfile
from urllib.request import urlopen

VERSION = "1.28.6"
SHA512 = "LsNqk3a9TNJGjJKWVOUK1YMlWJNxFh8bIf+SSxGI+A+WXDlkwc4R2PW/n1qINb4YpqZfOazjPdRqw95WpmCrfw=="
FILES = ("mupdf.js", "mupdf-wasm.js", "mupdf-wasm.wasm")


def main():
    url = f"https://registry.npmjs.org/mupdf/-/mupdf-{VERSION}.tgz"
    with urlopen(url, timeout=30) as response:
        package = response.read()
    if hashlib.sha512(package).digest() != base64.b64decode(SHA512):
        raise SystemExit("MuPDF.js package integrity check failed.")
    target = Path(__file__).resolve().parents[1] / "web" / "vendor" / f"mupdf-{VERSION}"
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(package), mode="r:gz") as archive:
        members = [f"dist/{name}{suffix}" for name in FILES for suffix in ("", ".br")]
        for member in ["LICENSE", *members]:
            with archive.extractfile(f"package/{member}") as file:
                (target / Path(member).name).write_bytes(file.read())


if __name__ == "__main__":
    main()
