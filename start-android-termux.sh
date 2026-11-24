#!/data/data/com.termux/files/usr/bin/sh
# PageBurrow for Android, running inside the free Termux app
# (install Termux from F-Droid or GitHub; the old Google Play version is outdated).
#
# In Termux, run:   sh /path/to/this/folder/start-android-termux.sh
# Add --lan to let other devices on the same Wi-Fi (e.g. an iPhone) use it too.
# The first start installs Python, PyMuPDF and Pillow from Termux's own packages.
cd "$(dirname "$0")" || exit 1

if ! command -v python >/dev/null 2>&1; then
    echo "Installing Python (first run only; needs the internet)..."
    pkg install -y python || exit 1
fi

# Keep Termux running while you switch to the browser (release with termux-wake-unlock).
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock

# Home-screen shortcut for the optional Termux:Widget app.
if mkdir -p "$HOME/.shortcuts" 2>/dev/null; then
    printf '#!/data/data/com.termux/files/usr/bin/sh\nsh "%s/start-android-termux.sh" "$@"\n' "$(pwd)" > "$HOME/.shortcuts/PageBurrow"
    chmod 700 "$HOME/.shortcuts/PageBurrow"
fi

exec python launch.py --system "$@"
