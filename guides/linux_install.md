# Installing on Linux (AlmaLinux 9)

Implements: REL-03 in [CHARTER.md](CHARTER.md).

The app runs from a source checkout on Linux. `scripts/install_linux.sh` sets it up on AlmaLinux 9 (RHEL 9 and
Rocky 9 work the same way), and CI's `almalinux` job runs that script in an `almalinux:9` container on every pull
request, then starts the app on a real X server (`scripts/smoke_linux.sh`) and runs the GUI tests.

## Install

```bash
git clone https://github.com/lgriffin/warcraftlogs_project.git
cd warcraftlogs_project
scripts/install_linux.sh
```

Each release also publishes `WarcraftLogsAnalyzer-<tag>-linux.tar.gz`, the tag's source, listed in the release's
signed `SHA256SUMS` (check it as the README shows), and released only after it installed and started on AlmaLinux 9.
Unpack it and run the same script inside it. To update a bundle install, unpack the newer bundle over the same
folder (`tar -xzf WarcraftLogsAnalyzer-<tag>-linux.tar.gz --strip-components=1 -C <folder>`), so your data stays, and
run the script again.

The script:

1. Installs the system packages with `dnf` (using `sudo` unless run as root): Python 3.12 (EL 9's own `python3` is
   3.9, and the app needs 3.10+), git, and the libraries the PySide6 wheel's X11 plugin loads (Mesa GL/EGL,
   `libxkbcommon-x11`, the `xcb-util-*` libraries, fontconfig). `xcb-util-cursor`, which Qt 6.5+ needs, comes from
   EPEL; the script enables `epel-release` when the base repositories lack it.
2. Creates a virtualenv at `.venv` in the checkout and installs the app into it with `pip install -e ".[gui]"`.
3. Checks with `ldd` that Qt's X11 plugin finds every library it links, and stops naming any that are missing.
4. Links `warcraftlogs` and `warcraftlogs-gui` into `~/.local/bin` and adds a "WarcraftLogs Analyzer" entry to the
   applications menu (`~/.local/share/applications/warcraftlogs-analyzer.desktop`).

| Option | Effect |
|--------|--------|
| `--dev` | also install the dev tools (the `[dev]` extra) |
| `--python PATH` | the Python 3.10+ interpreter for the virtualenv |
| `--no-system-deps` | skip `dnf`; for other distributions, install the equivalent packages yourself |
| `--no-desktop` | skip the launchers and the menu entry |

`WCL_VENV` moves the virtualenv elsewhere.

## Where data lives

A source install keeps `config.json`, `warcraftlogs_history.db`, `reports/` and `.cache/` in the checkout, as it does
on Windows (`wcl_core.paths`). That is why the script installs in editable mode: a plain `pip install .` would put them
inside `site-packages`. All of them are in `.gitignore`.

## Updating

The in-app updater downloads the Windows build, so on Linux it stays off and Settings says how to update instead. From a
git checkout:

```bash
git pull
scripts/install_linux.sh
```

## Uninstalling

Delete `~/.local/bin/warcraftlogs`, `~/.local/bin/warcraftlogs-gui`,
`~/.local/share/applications/warcraftlogs-analyzer.desktop` and the checkout (which holds your data).

## Troubleshooting

- **`qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`**: a system library is missing. Run the script again;
  its `ldd` check names the library, and `dnf provides '*/<library>'` names the package.
- **Wayland sessions**: the app runs through XWayland by default. `QT_QPA_PLATFORM=wayland` uses the wheel's native
  Wayland plugin instead.
- **No display (SSH, servers)**: use the CLI (`warcraftlogs`), or `QT_QPA_PLATFORM=offscreen` for headless tests.
