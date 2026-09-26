"""Tests for the shared application services layer used by every frontend."""

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from warcraftlogs_client.models import CharacterProfile, CharacterReportEntry
from warcraftlogs_client.services import (
    AnalysisThresholds,
    AppContext,
    PlayerService,
    RaidService,
    ReferenceAuthRequired,
    validate_report_code,
)

SERVICES_DIR = Path(__file__).resolve().parent.parent / "warcraftlogs_client" / "services"
FORBIDDEN_IMPORT_PREFIXES = ("PySide6", "argparse", "fastapi", "flask", "starlette")

CODE_A = "aBcDeFgHiJkLmN12"
CODE_B = "zzzzzzzzzzzzzzz9"


@pytest.fixture
def ctx(tmp_path):
    context = AppContext(config={"client_id": "id", "client_secret": "secret"}, db_path=str(tmp_path / "t.db"))
    context._client = MagicMock()
    return context


class TestArchitecture:
    def test_services_import_no_frontend_framework(self):
        for path in SERVICES_DIR.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    assert not name.startswith(FORBIDDEN_IMPORT_PREFIXES), f"{path.name} imports {name}"

    def test_services_do_not_import_gui_or_cli(self):
        for path in SERVICES_DIR.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level >= 2 and node.module:
                    top = node.module.split(".")[0]
                    assert top not in ("gui", "cli", "renderers"), f"{path.name} imports {node.module}"


class TestReportCode:
    def test_valid_code_is_returned_stripped(self):
        assert validate_report_code(f"  {CODE_A} ") == CODE_A

    @pytest.mark.parametrize("bad", ["", "short", CODE_A + "x", 'abc"){ x }', "aBcDeFgHiJkLmN1!"])
    def test_invalid_code_is_rejected(self, bad):
        with pytest.raises(ValueError):
            validate_report_code(bad)


class TestThresholds:
    def test_defaults_when_config_has_none(self):
        assert AnalysisThresholds.from_config({}) == AnalysisThresholds()

    def test_config_overrides_and_kwargs_shape(self):
        t = AnalysisThresholds.from_config({"role_thresholds": {"healer_min_healing": 1, "tank_min_taken_10": 2}})
        kwargs = t.as_kwargs()
        assert kwargs["healer_threshold"] == 1
        assert kwargs["tank_min_taken_10"] == 2
        assert kwargs["tank_min_mitigation"] == 40


class TestRaidService:
    def test_analyze_passes_thresholds_and_progress(self, ctx):
        progress = MagicMock()
        with patch("warcraftlogs_client.services.raids.analyze_raid") as analyze:
            RaidService(ctx).analyze(CODE_A, progress=progress)
        args, kwargs = analyze.call_args
        assert args == (ctx.wcl_client, CODE_A)
        assert kwargs["progress_callback"] is progress
        assert kwargs["healer_threshold"] == 900000

    def test_analyze_rejects_bad_code_before_any_request(self, ctx):
        with patch("warcraftlogs_client.services.raids.analyze_raid") as analyze, pytest.raises(ValueError):
            RaidService(ctx).analyze("not-a-code")
        analyze.assert_not_called()

    def test_reference_without_sign_in_raises(self, ctx):
        with patch.object(AppContext, "user_client", return_value=None), pytest.raises(ReferenceAuthRequired):
            RaidService(ctx).analyze(CODE_A, reference=True)

    def test_analyze_and_save_round_trips(self, ctx, sample_raid_analysis):
        sample_raid_analysis.metadata.report_id = CODE_A
        with patch("warcraftlogs_client.services.raids.analyze_raid", return_value=sample_raid_analysis):
            RaidService(ctx).analyze_and_save(CODE_A)
        raids = RaidService(ctx)
        assert CODE_A in raids.imported_codes()
        assert raids.get_raid(CODE_A) is not None
        raids.delete_raid(CODE_A)
        assert CODE_A not in raids.imported_codes()

    def test_import_missing_skips_stored_reports(self, ctx):
        raids = RaidService(ctx)
        with (
            patch.object(RaidService, "imported_codes", return_value={CODE_A}),
            patch.object(RaidService, "analyze_and_save") as save,
        ):
            imported = raids.import_missing([CODE_A, CODE_B])
        assert imported == [CODE_B]
        save.assert_called_once()

    def test_import_missing_normalizes_and_dedupes(self, ctx):
        raids = RaidService(ctx)
        with (
            patch.object(RaidService, "imported_codes", return_value={CODE_A}),
            patch.object(RaidService, "analyze_and_save") as save,
        ):
            imported = raids.import_missing([f" {CODE_A} ", CODE_B, f"{CODE_B}\n", CODE_B])
        assert imported == [CODE_B]
        save.assert_called_once_with(CODE_B, progress=None)


class TestPlayerService:
    def test_discover_reports_flags_imported(self, ctx):
        ctx.wcl_client.get_character_profile.return_value = CharacterProfile(
            name="Hadur",
            server="spineshatter",
            region="EU",
            recent_reports=[
                CharacterReportEntry(code=CODE_A, title="Kara", start_time=1, zone_name="Karazhan"),
                CharacterReportEntry(code=CODE_B, title="Gruul", start_time=2, zone_name="Gruul's Lair"),
            ],
        )
        players = PlayerService(ctx)
        with patch.object(RaidService, "imported_codes", return_value={CODE_A}):
            refs = players.discover_reports("Hadur", "spineshatter", "EU")
        assert [(r.code, r.imported) for r in refs] == [(CODE_A, True), (CODE_B, False)]

    def test_add_reports_delegates_to_raid_service(self, ctx):
        raids = MagicMock()
        raids.import_missing.return_value = [CODE_B]
        assert PlayerService(ctx, raids=raids).add_reports([CODE_A, CODE_B]) == [CODE_B]
