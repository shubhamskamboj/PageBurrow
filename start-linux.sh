#!/bin/sh
# PageBurrow for Linux. Double-click this file (choose "Run in Terminal" if asked)
# or run:  sh start-linux.sh
# The Linux package brings its own Python (runtime folder), so nothing needs installing.
cd "$(dirname "$0")" || exit 1

# Started from a file manager without a window: reopen in a terminal so the address
# stays visible and the tool can be stopped by closing the window.
if [ ! -t 1 ] && [ -z "$PDF_TOOLS_TERMINAL" ]; then
    PDF_TOOLS_TERMINAL=1
    export PDF_TOOLS_TERMINAL
    for term in x-terminal-emulator gnome-terminal konsole xfce4-terminal mate-terminal xterm; do
        command -v "$term" >/dev/null 2>&1 || continue
        case "$term" in
            gnome-terminal) exec "$term" -- sh "$0" "$@" ;;
            xfce4-terminal|mate-terminal) exec "$term" -x sh "$0" "$@" ;;
            *) exec "$term" -e sh "$0" "$@" ;;
        esac
    done
fi

finish() {
    if [ "$1" -ne 0 ]; then
        printf '\nPageBurrow stopped because of the problem shown above.\nPress Enter to close.'
        read -r _
    fi
    exit "$1"
}

case "$(uname -m)" in
    x86_64|amd64) runtime=runtime/linux-x64 ;;
    aarch64|arm64) runtime=runtime/linux-arm64 ;;
    *) runtime= ;;
esac
if [ -n "$runtime" ] && [ -f "$runtime/bin/python3.12" ]; then
    python="$runtime/bin/python3.12"
    # Some unzip tools drop the "executable" flag; put it back.
    [ -x "$python" ] || chmod +x "$python" 2>/dev/null
    if "$python" -E -s -c 'import pymupdf, PIL' >/dev/null 2>&1; then
        "$python" -E -s app.py "$@"
        finish $?
    fi
    echo "The Python in the runtime folder could not start (this Linux may be older than"
    echo "glibc 2.28). Trying an installed Python instead..."
fi

for PY in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    command -v "$PY" >/dev/null 2>&1 || continue
    if "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        "$PY" launch.py "$@"
        finish $?
    fi
done
echo "PageBurrow needs Python 3.10 or newer, or a package that includes it"
echo "(PageBurrow.zip or PageBurrow-Linux.tar.gz). Install Python with your package manager, for example:"
echo "    sudo apt install python3 python3-venv      (Debian, Ubuntu, Mint)"
echo "    sudo dnf install python3                   (Fedora)"
echo "    sudo pacman -S python                      (Arch)"
finish 1
