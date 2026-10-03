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


class TestProfileAndDiscordParsers:
    def test_profile_create_with_axes(self, parser):
        args = parser.parse_args(
            [
                "profile",
                "create",
                "TBC",
                "--expansion",
                "The Burning Crusade",
                "--zone",
                "Karazhan",
                "--since",
                "2026-01-01",
                "--use",
            ]
        )
        assert args.command == "profile" and args.profile_command == "create"
        assert args.name == "TBC" and args.expansion == ["The Burning Crusade"] and args.zone == ["Karazhan"]
        assert args.since == "2026-01-01" and args.use

    def test_profile_game_version_is_checked(self, parser):
        assert parser.parse_args(["profile", "create", "Era", "--game-version", "classic"]).game_version == "classic"
        with pytest.raises(SystemExit):
            parser.parse_args(["profile", "create", "Era", "--game-version", "wrath"])

    def test_profile_use_without_a_slug_clears(self, parser):
        assert parser.parse_args(["profile", "use"]).slug is None
        assert parser.parse_args(["profile", "use", "tbc"]).slug == "tbc"

    def test_discord_actions(self, parser):
        assert parser.parse_args(["discord", "login", "--no-browser"]).no_browser
        assert parser.parse_args(["discord", "whoami", "--json"]).json
        assert parser.parse_args(["discord", "logout"]).discord_command == "logout"


class TestProfileCommand:
    def test_list_create_use_show(self, monkeypatch, tmp_path, capsys):
        from wcl_core import paths

        from warcraftlogs_client import cli

        monkeypatch.setattr(paths, "get_profiles_path", lambda: tmp_path / "profiles.json")
        monkeypatch.setattr(cli, "_profile_service", lambda need_config: _service(tmp_path))
        parser = cli.create_parser()

        assert cli.run_profile_command(parser.parse_args(["profile", "list"])) == 0
        assert "No profiles yet" in capsys.readouterr().out
        assert (
            cli.run_profile_command(
                parser.parse_args(["profile", "create", "TBC", "--expansion", "The Burning Crusade", "--use"])
            )
            == 0
        )
        assert "Created profile 'TBC' (tbc) and made it active" in capsys.readouterr().out
        assert cli.run_profile_command(parser.parse_args(["profile", "list"])) == 0
        assert "* tbc" in capsys.readouterr().out
        assert cli.run_profile_command(parser.parse_args(["profile", "use"])) == 0
        assert "every raid is shown" in capsys.readouterr().out
        assert cli.run_profile_command(parser.parse_args(["profile", "use", "nope"])) == 1
        assert cli.run_profile_command(parser.parse_args(["profile", "show"])) == 0
        assert "No active profile" in capsys.readouterr().out
        assert cli.run_profile_command(parser.parse_args(["profile", "delete", "tbc"])) == 0
        assert cli.run_profile_command(parser.parse_args(["profile"])) == 1


def _service(tmp_path):
    from warcraftlogs_client.services import AppContext, JsonProfileStore, ProfileService

    ctx = AppContext(config={}, db_path=str(tmp_path / "t.db"))
    service = ProfileService.from_context(ctx, JsonProfileStore(tmp_path / "profiles.json"))
    service.apply()
    return service


class TestRoleDispatch:
    @pytest.mark.parametrize("role", ["healer", "tank", "melee", "ranged"])
    def test_role_commands_run_unified_analysis_filtered(self, monkeypatch, role):
        from warcraftlogs_client import cli

        calls = []
        monkeypatch.setattr(cli, "run_unified_analysis", lambda args, role=None: calls.append(role) or 0)
        monkeypatch.setattr("sys.argv", ["warcraftlogs", role])
        assert cli.main() == 0
        assert calls == [role]
