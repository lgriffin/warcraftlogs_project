#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:?Usage: ./build_release.sh <version>  (e.g. 3.1.0)}"
ISCC="/c/Program Files (x86)/Inno Setup 6/ISCC.exe"
INSTALLER="installer_output/WarcraftLogsAnalyzer-${VERSION}-Setup.exe"

echo "=== Building WarcraftLogs Analyzer v${VERSION} ==="

# Update version in installer.iss and spec
sed -i "s/^AppVersion=.*/AppVersion=${VERSION}/" installer.iss
sed -i "s/^OutputBaseFilename=.*/OutputBaseFilename=WarcraftLogsAnalyzer-${VERSION}-Setup/" installer.iss

echo "[1/3] Running PyInstaller..."
rm -rf build dist
python -m PyInstaller warcraftlogs_analyzer.spec

echo "[2/3] Building installer with Inno Setup..."
"$ISCC" installer.iss

if [ ! -f "$INSTALLER" ]; then
    echo "ERROR: Installer not found at ${INSTALLER}"
    exit 1
fi

echo "[3/3] Creating GitHub release..."
gh release create "v${VERSION}" "$INSTALLER" \
    --title "WarcraftLogs Analyzer v${VERSION}" \
    --notes "## WarcraftLogs Analyzer v${VERSION}

Download **WarcraftLogsAnalyzer-${VERSION}-Setup.exe** below and run the installer.

Enter your WarcraftLogs API credentials in **Settings** on first launch.

User data is stored in \`%APPDATA%\\WarcraftLogsAnalyzer\\\` and is preserved across upgrades."

echo "=== Done! Release: https://github.com/lgriffin/warcraftlogs_project/releases/tag/v${VERSION} ==="
