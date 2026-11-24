"""Starts PageBurrow on Windows, macOS, Linux or Android (Termux).

The launchers (Start-Windows.cmd, Start-macOS.command, start-linux.sh,
start-android-termux.sh) run this file. On the first run it creates a private Python
environment for this computer and installs PyMuPDF and Pillow, from the wheelhouse
folder when it holds matching files, otherwise from the internet.

Options (passed on to the app): --lan, --port N, --host ADDRESS, --no-browser
Launcher option: --system  use the Python packages already installed on this device
                           (automatic on Termux, where pip cannot build PyMuPDF)
"""
# Keep this file free of syntax newer than Python 3.6, so that an old Python can still
# print the "Python 3.10 or newer is required" message instead of a syntax error.
import os
import platform
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")
WHEELHOUSE = os.path.join(ROOT, "wheelhouse")
CHECK = (
    "import sys, pymupdf, PIL\n"
    "version = getattr(pymupdf, 'VersionBind', None) or pymupdf.__version__\n"
    "sys.exit(0 if tuple(int(p) for p in version.split('.')[:2]) >= (1, 24) else 3)\n"
)


def say(*lines):
    print("\n".join(lines), flush=True)


def is_termux():
    return "com.termux" in os.environ.get("PREFIX", "") or bool(os.environ.get("TERMUX_VERSION"))


def system_name():
    if os.name == "nt":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def python_hint():
    return {
        "windows": "Install it from https://www.python.org/downloads/ and tick \"Add python.exe to PATH\".",
        "macos": "Install it from https://www.python.org/downloads/macos/ (or run: brew install python).",
        "linux": "Install it with your package manager, for example: sudo apt install python3 python3-venv",
    }[system_name()]


def ready(python):
    """True when this Python can import PyMuPDF and Pillow."""
    try:
        return subprocess.call([python, "-c", CHECK], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    except OSError:
        return False


def runs(python):
    try:
        return subprocess.call([python, "-c", "pass"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    except OSError:
        return False


def venv_paths():
    # One environment per system, so the folder can move between computers.
    folder = os.path.join(ROOT, ".venv" if os.name == "nt" else ".venv-" + system_name())
    python = os.path.join(folder, "Scripts", "python.exe") if os.name == "nt" else os.path.join(folder, "bin", "python")
    return folder, python


def install(python):
    command = [python, "-m", "pip", "--disable-pip-version-check", "install", "--only-binary=:all:", "-r", REQUIREMENTS]
    has_wheels = os.path.isdir(WHEELHOUSE) and any(name.endswith(".whl") for name in os.listdir(WHEELHOUSE))
    if has_wheels:
        say("Installing PyMuPDF and Pillow from the wheelhouse folder...")
        if subprocess.call(command + ["--no-index", "--find-links", WHEELHOUSE]) == 0:
            return True
        say("The wheelhouse folder has no files for this computer. Trying the internet instead...")
    else:
        say("Installing PyMuPDF and Pillow (first run only; needs the internet)...")
    return subprocess.call(command) == 0


def prepare_venv():
    folder, python = venv_paths()
    if runs(python) and ready(python):
        return python
    if not runs(python):
        say("Setting up PageBurrow for this computer (first run only)...")
        try:
            import venv
            venv.EnvBuilder(with_pip=True, clear=os.path.exists(folder)).create(folder)
        except Exception as error:  # e.g. Debian and Ubuntu ship venv as a separate package
            say("Could not create a Python environment: {}".format(error),
                "On Debian or Ubuntu, run:  sudo apt install python3-venv",
                "Or install PyMuPDF and Pillow yourself and start with the --system option.")
            return None
    if install(python) and ready(python):
        return python
    say("", "PyMuPDF and Pillow could not be installed.",
        "Check the internet connection and the messages above, then start again.")
    if system_name() == "linux":
        say("On computers without PyMuPDF downloads (for example 32-bit ARM), install the system packages",
            "instead, e.g.  sudo apt install python3-pymupdf python3-pil  and start with the --system option.")
    return None


def prepare_system():
    python = sys.executable
    if ready(python):
        return python
    if is_termux():
        say("Installing PyMuPDF and Pillow for Termux (first run only; needs the internet)...")
        subprocess.call(["pkg", "install", "-y", "python-pymupdf", "python-pillow"])
        if ready(python):
            return python
        say("Installation failed. Run  pkg update  and then start again.")
        return None
    say("This Python cannot load PyMuPDF and Pillow. Install them, or start without --system.")
    return None


def main():
    args = sys.argv[1:]
    use_system = "--system" in args or is_termux()
    args = [arg for arg in args if arg != "--system"]
    if sys.version_info < (3, 10):
        say("PageBurrow needs Python 3.10 or newer. This is Python {}.".format(platform.python_version()),
            python_hint())
        return 1
    python = prepare_system() if use_system else prepare_venv()
    if not python:
        return 1
    try:
        return subprocess.call([python, os.path.join(ROOT, "app.py")] + args, cwd=ROOT)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
