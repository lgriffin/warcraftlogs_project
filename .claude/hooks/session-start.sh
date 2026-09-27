#!/usr/bin/env bash
# Claude Code on the web: install the pinned dev toolchain so `python scripts/dev.py check` works in a fresh session.
# Local sessions already have their own environment, so this does nothing there.
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
if python3 -m pip install --quiet -e ".[dev]" >/tmp/wcl-dev-install.log 2>&1; then
  echo "Installed the dev toolchain; run: python scripts/dev.py check"
else
  # Never block the session: some environments cannot reach PyPI, and CI still runs every check.
  echo "Could not install the dev toolchain (see /tmp/wcl-dev-install.log); CI remains the check."
fi
exit 0
