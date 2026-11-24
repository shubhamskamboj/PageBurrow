#!/bin/sh
# PageBurrow for macOS. Double-click this file to start; it opens in Terminal.
# If macOS says it cannot be opened: right-click it and choose Open (macOS 14 and older),
# or allow it under System Settings > Privacy & Security > Open Anyway (macOS 15 and newer).
# The macOS package brings its own Python (runtime folder), so nothing needs installing.
cd "$(dirname "$0")" || exit 1

finish() {
    if [ "$1" -ne 0 ]; then
        printf '\nPageBurrow stopped because of the problem shown above.\nPress Return to close.'
        read -r _
    fi
    exit "$1"
}

if [ -d runtime ]; then
    # Files unpacked from a download are quarantined, and macOS would block the bundled
    # Python. You started this file, so allow the rest of this package's files too.
    xattr -dr com.apple.quarantine . 2>/dev/null
    if [ "$(uname -m)" = arm64 ]; then candidates="runtime/macos-arm64 runtime/macos-x64"; else candidates="runtime/macos-x64"; fi
    for runtime in $candidates; do
        python="$runtime/bin/python3.12"
        [ -f "$python" ] || continue
        # Some unzip tools drop the "executable" flag; put it back.
        [ -x "$python" ] || chmod +x "$python" 2>/dev/null
        if "$python" -E -s -c 'import pymupdf, PIL' >/dev/null 2>&1; then
            "$python" -E -s app.py "$@"
            finish $?
        fi
    done
    echo "The Python in the runtime folder could not start. Trying an installed Python instead..."
fi

for PY in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
          /opt/homebrew/bin/python3 /usr/local/bin/python3 \
          python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    found=$(command -v "$PY" 2>/dev/null) || continue
    # Apple's /usr/bin/python3 is too old, and calling it can open an installer prompt.
    [ "$found" = /usr/bin/python3 ] && continue
    if "$found" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        "$found" launch.py "$@"
        finish $?
    fi
done
echo "PageBurrow needs Python 3.10 or newer, or a package that includes it"
echo "(PageBurrow.zip or PageBurrow-macOS.tar.gz). Install Python from https://www.python.org/downloads/macos/"
echo "(or run: brew install python), then double-click this file again."
finish 1
