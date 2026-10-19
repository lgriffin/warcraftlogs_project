#!/usr/bin/env bash
# Start the installed desktop app on a headless X server and fail if it does not stay up, the way a missing Qt
# system library would make it (CI's `almalinux` job and the release's Linux bundle run this after
# scripts/install_linux.sh). Installs Xvfb with dnf when it is missing.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${WCL_VENV:-$REPO_DIR/.venv}"
SECONDS_UP="${WCL_SMOKE_SECONDS:-15}"

if ! command -v Xvfb >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then dnf install -y xorg-x11-server-Xvfb; else sudo dnf install -y xorg-x11-server-Xvfb; fi
fi

"$VENV_DIR/bin/warcraftlogs" --version

Xvfb :99 -screen 0 1920x1200x24 -nolisten tcp &
XVFB_PID=$!
trap 'kill "$XVFB_PID" 2>/dev/null || true' EXIT
sleep 2

# The real X11 (xcb) platform plugin, not offscreen: this is what loads the dnf packages the install script adds.
status=0
DISPLAY=:99 QT_QPA_PLATFORM=xcb timeout "$SECONDS_UP" "$VENV_DIR/bin/warcraftlogs-gui" || status=$?
if [ "$status" -ne 124 ]; then
    echo "warcraftlogs-gui exited with status $status before $SECONDS_UP seconds were up" >&2
    exit 1
fi
echo "warcraftlogs-gui stayed up for $SECONDS_UP seconds on X11."
