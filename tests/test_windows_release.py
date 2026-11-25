"""Charter REL-04: one Windows installer per release, and installed copies upgrade in place from it.

The updater runs each new Setup.exe silently over the last one, so the installer must keep the same AppId, take its
version from the app, and the release must always ship it with a SHA256SUMS entry.
"""

import re
from pathlib import Path

import yaml

from warcraftlogs_client.version import __version__

ROOT = Path(__file__).resolve().parent.parent
ISS = (ROOT / "installer.iss").read_text(encoding="utf-8")
WORKFLOW = ROOT / ".github" / "workflows" / "build-installer.yml"


def _setup_value(key: str) -> str:
    match = re.search(rf"^{key}=(.*)$", ISS, re.MULTILINE)
    assert match, f"installer.iss has no {key}="
    return match.group(1).strip()


def _windows_steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["build"]["steps"]


def test_installer_default_version_is_the_app_version():
    match = re.search(r'^\s*#define AppVersion "([^"]+)"', ISS, re.MULTILINE)
    assert match, "installer.iss has no default AppVersion"
    assert match.group(1) == __version__


def test_installer_names_itself_after_the_version_the_updater_looks_for():
    assert _setup_value("AppVersion") == "{#AppVersion}"
    assert _setup_value("OutputBaseFilename") == "WarcraftLogsAnalyzer-{#AppVersion}-Setup"


def test_installer_keeps_the_app_id_every_earlier_release_used():
    """Inno Setup's default AppId is AppName; changing it would install a second copy beside the first."""
    assert _setup_value("AppId") == "WarcraftLogs Analyzer" == _setup_value("AppName")


def test_installer_is_per_user_so_silent_updates_need_no_admin_prompt():
    assert _setup_value("PrivilegesRequired") == "lowest"
    assert _setup_value("DefaultDirName").startswith("{autopf}")


def test_release_passes_the_app_version_to_the_installer():
    steps = _windows_steps()
    inno = next(s for s in steps if "Inno-Setup-Action" in s.get("uses", ""))
    assert "/DAppVersion=${{ steps.version.outputs.version }}" in inno["with"]["options"]
    assert not inno.get("continue-on-error"), "a release without the installer leaves installed copies stranded"
    version = next(s for s in steps if s.get("id") == "version")
    assert "GITHUB_REF_NAME" in version["run"]


def test_release_checksums_and_publishes_the_installer():
    steps = _windows_steps()
    sums = next(s for s in steps if s.get("name") == "Generate SHA256SUMS")
    assert 'installer_output\\*.exe"' in sums["run"]
    assert "if (" not in sums["run"].split("installer_output")[0].splitlines()[-1]
    release = next(s for s in steps if "action-gh-release" in s.get("uses", ""))
    assert "installer_output/*.exe" in release["with"]["files"]
