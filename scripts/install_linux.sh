#!/usr/bin/env bash
# Install WarcraftLogs Analyzer from this checkout on Linux (tested on AlmaLinux 9; other dnf-based
# EL 9 systems such as RHEL and Rocky work the same way).
#
#   scripts/install_linux.sh             # system packages, .venv, launchers and a desktop menu entry
#   scripts/install_linux.sh --dev       # also the dev tools (pytest, ruff, ...)
#
# Run it again after `git pull` to update. See guides/linux_install.md.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${WCL_VENV:-$REPO_DIR/.venv}"
case "$VENV_DIR" in
    /*) ;;
    *) VENV_DIR="$PWD/$VENV_DIR" ;;  # the launchers and menu entry need an absolute path
esac
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$APPS_DIR/warcraftlogs-analyzer.desktop"

SYSTEM_DEPS=1
DESKTOP=1
EXTRAS="gui"
PYTHON="${PYTHON:-}"

usage() {
    cat <<'EOF'
Usage: scripts/install_linux.sh [options]

  --dev              also install the dev tools (the [dev] extra)
  --python PATH      the Python 3.10+ interpreter for the virtualenv (default: python3.12, python3.11, python3)
  --no-system-deps   skip the dnf packages (Python, Qt's X11/OpenGL libraries); install them yourself
  --no-desktop       skip the ~/.local/bin launchers and the desktop menu entry
  -h, --help         show this help

Environment: WCL_VENV sets the virtualenv directory (default: .venv in the checkout).
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dev) EXTRAS="dev,gui" ;;
        --python) PYTHON="${2:?--python needs a path}"; shift ;;
        --no-system-deps) SYSTEM_DEPS=0 ;;
        --no-desktop) DESKTOP=0 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

step() { printf '\n==> %s\n' "$*"; }

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

# Python 3.10+ (EL 9's own python3 is 3.9), and the libraries the PySide6 wheel's X11 (xcb) platform plugin
# and QtCharts load at run time. The wheel bundles Qt itself.
DNF_PACKAGES=(
    python3.12 python3.12-pip git
    fontconfig freetype dbus-libs glib2 libX11 libXext libXrender libXi libxcb libxkbcommon libxkbcommon-x11
    mesa-libGL mesa-libEGL xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-wm
)

install_system_deps() {
    if ! command -v dnf >/dev/null 2>&1; then
        echo "dnf not found: skipping system packages. Install Python 3.10+ and Qt's X11 libraries yourself" \
            "(see guides/linux_install.md), or pass --no-system-deps to silence this." >&2
        return
    fi
    step "Installing system packages with dnf"
    as_root dnf install -y "${DNF_PACKAGES[@]}"
    # Qt 6.5+ needs libxcb-cursor; EL 9 ships it in EPEL.
    if ! as_root dnf install -y xcb-util-cursor; then
        as_root dnf install -y epel-release
        as_root dnf install -y xcb-util-cursor
    fi
}

pick_python() {
    if [ -n "$PYTHON" ]; then
        echo "$PYTHON"
        return
    fi
    for candidate in python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
            echo "$candidate"
            return
        fi
    done
    echo "No Python 3.10+ found. On AlmaLinux 9: sudo dnf install python3.12 python3.12-pip" >&2
    exit 1
}

install_app() {
    local python
    python="$(pick_python)"
    step "Creating the virtualenv at $VENV_DIR with $("$python" --version)"
    "$python" -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
    # Editable on purpose: the app keeps config.json, its database and reports next to the code
    # (wcl_core.paths), so they stay in this checkout and survive reinstalls.
    step "Installing WarcraftLogs Analyzer [$EXTRAS]"
    "$VENV_DIR/bin/python" -m pip install -e "$REPO_DIR[$EXTRAS]"
}

check_qt_libraries() {
    step "Checking the libraries Qt's X11 plugin needs"
    local plugin missing
    plugin="$("$VENV_DIR/bin/python" -c \
        'import pathlib, PySide6; print(pathlib.Path(PySide6.__file__).parent / "Qt/plugins/platforms/libqxcb.so")')"
    if [ ! -f "$plugin" ]; then
        echo "PySide6 has no X11 platform plugin at $plugin" >&2
        exit 1
    fi
    missing="$(ldd "$plugin" | awk '/not found/ {print $1}' | sort -u)"
    if [ -n "$missing" ]; then
        echo "Qt's X11 plugin cannot load these libraries:" >&2
        echo "$missing" >&2
        echo "Install them (dnf provides '<library>' names the package) and run this script again." >&2
        exit 1
    fi
    echo "All present."
}

install_launchers() {
    step "Adding launchers to $BIN_DIR and a menu entry to $APPS_DIR"
    mkdir -p "$BIN_DIR" "$APPS_DIR"
    ln -sf "$VENV_DIR/bin/warcraftlogs" "$BIN_DIR/warcraftlogs"
    ln -sf "$VENV_DIR/bin/warcraftlogs-gui" "$BIN_DIR/warcraftlogs-gui"
    cat >"$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=WarcraftLogs Analyzer
Comment=Analyze Warcraft Logs raid reports
Exec="$VENV_DIR/bin/warcraftlogs-gui"
Path=$REPO_DIR
Icon=$REPO_DIR/logo.png
Terminal=false
Categories=Game;Utility;
EOF
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
    fi
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) echo "Note: $BIN_DIR is not on your PATH; add it to run warcraftlogs and warcraftlogs-gui by name." ;;
    esac
}

if [ "$SYSTEM_DEPS" -eq 1 ]; then
    install_system_deps
fi
install_app
check_qt_libraries
if [ "$DESKTOP" -eq 1 ]; then
    install_launchers
fi

step "Done"
echo "Start the app from your applications menu, or run: $VENV_DIR/bin/warcraftlogs-gui"
