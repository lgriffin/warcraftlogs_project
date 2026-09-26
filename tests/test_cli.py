"""Tests for CLI argument parsing."""

import pytest

from warcraftlogs_client.cli import create_parser


@pytest.fixture
def parser():
    return create_parser()


class TestCreateParser:
    def test_unified_subcommand(self, parser):
        args = parser.parse_args(["unified"])
        assert args.command == "unified"

    def test_unified_with_md(self, parser):
        args = parser.parse_args(["unified", "--md"])
        assert args.md is True

    def test_unified_with_save(self, parser):
        args = parser.parse_args(["unified", "--save"])
        assert args.save is True

    def test_unified_with_report_id(self, parser):
        args = parser.parse_args(["unified", "--report-id", "abc123"])
        assert args.report_id == "abc123"

    def test_consumes_with_raid_ids(self, parser):
        args = parser.parse_args(["consumes", "id1", "id2", "id3"])
        assert args.command == "consumes"
        assert args.raid_ids == ["id1", "id2", "id3"]

    def test_consumes_with_csv(self, parser):
        args = parser.parse_args(["consumes", "id1", "--csv", "out.csv"])
        assert args.csv == "out.csv"

    def test_history_with_name(self, parser):
        args = parser.parse_args(["history", "Hadur"])
        assert args.command == "history"
        assert args.character_name == "Hadur"

    def test_history_all_flag(self, parser):
        args = parser.parse_args(["history", "--all"])
        assert args.all is True

    def test_history_raids_flag(self, parser):
        args = parser.parse_args(["history", "--raids"])
        assert args.raids is True

    def test_version_flag(self, parser):
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_healer_subcommand(self, parser):
        args = parser.parse_args(["healer"])
        assert args.command == "healer"

    def test_tank_subcommand(self, parser):
        args = parser.parse_args(["tank"])
        assert args.command == "tank"

    @pytest.mark.parametrize("role", ["healer", "tank", "melee", "ranged"])
    def test_role_subcommands_share_unified_options(self, parser, role):
        args = parser.parse_args([role, "--md", "--save", "--report-id", "abc123"])
        assert args.command == role
        assert args.md is True
        assert args.save is True
        assert args.report_id == "abc123"

    def test_healer_accepts_legacy_dynamic_roles_flag(self, parser):
        args = parser.parse_args(["healer", "--use-dynamic-roles"])
        assert args.use_dynamic_roles is True


class TestRoleDispatch:
    @pytest.mark.parametrize("role", ["healer", "tank", "melee", "ranged"])
    def test_role_commands_run_unified_analysis_filtered(self, monkeypatch, role):
        from warcraftlogs_client import cli

        calls = []
        monkeypatch.setattr(cli, "run_unified_analysis", lambda args, role=None: calls.append(role) or 0)
        monkeypatch.setattr("sys.argv", ["warcraftlogs", role])
        assert cli.main() == 0
        assert calls == [role]
