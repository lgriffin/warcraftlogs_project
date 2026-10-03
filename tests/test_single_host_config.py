"""Phase 5 of ``guides/identity_and_profiles.md``: the single-host keys are read in one place.

``wcl_api_url`` and ``guild_id`` in config.json are the defaults of the implicit "All" profile. A raid profile
names its own site and guild, and ``AppContext.api_url`` / ``guild_id`` choose between them, so a module that reads
the raw key ignores the active profile. Code reads them through ``wcl_core.config.configured_api_url`` /
``configured_guild_id`` (or the context); this test finds every other ``config["wcl_api_url"]`` or
``.get("guild_id")``. ``EDITORS`` are the views that edit the defaults themselves; the list only shrinks.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    "warcraftlogs_client": ROOT / "warcraftlogs_client",
    "wcl_core": ROOT / "packages" / "wcl-core" / "src" / "wcl_core",
    "wcl_store": ROOT / "packages" / "wcl-store" / "src" / "wcl_store",
    "wcl_app": ROOT / "packages" / "wcl-app" / "src" / "wcl_app",
}
KEYS = {"wcl_api_url", "guild_id"}

# Where the keys may be read raw: the accessors, the loader that builds the dict, and the profile file, whose
# entries carry their own ``guild_id`` and ``wcl_api_url``.
OWNERS = {"wcl_core.config", "wcl_app.profiles"}

# Views that show and save the defaults in config.json, so they read the raw key on purpose.
EDITORS = {
    "warcraftlogs_client.gui.character_view",
    "warcraftlogs_client.gui.settings_view",
}


def _module(package: str, path: Path, root: Path) -> str:
    parts = path.relative_to(root).with_suffix("").parts
    return ".".join((package, *parts)).removesuffix(".__init__")


def _reads_a_key(node: ast.AST) -> bool:
    if isinstance(node, ast.Subscript):
        key = node.slice
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
        key = node.args[0]
    else:
        return False
    return isinstance(key, ast.Constant) and key.value in KEYS


def readers() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for package, root in SOURCES.items():
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            lines = [node.lineno for node in ast.walk(tree) if _reads_a_key(node)]
            if lines:
                found[_module(package, path, root)] = sorted(lines)
    return found


def test_only_the_accessors_and_the_settings_editors_read_the_single_host_keys():
    stray = {module: lines for module, lines in readers().items() if module not in OWNERS | EDITORS}
    assert stray == {}, (
        "read these through wcl_core.config.configured_api_url / configured_guild_id, or AppContext.api_url / "
        f"guild_id, so the active profile applies: {stray}"
    )


def test_every_listed_editor_still_reads_a_key_so_the_list_only_shrinks():
    gone = EDITORS - set(readers())
    assert not gone, f"remove these from EDITORS: {sorted(gone)}"


def test_the_check_sees_both_ways_of_reading_a_key():
    tree = ast.parse('config["wcl_api_url"]\nconfig.get("guild_id", 0)\nconfig.get("other")\nprofile.guild_id')
    assert sum(_reads_a_key(node) for node in ast.walk(tree)) == 2


class TestTheAccessors:
    def test_the_api_url_is_the_configured_one_or_none(self):
        from wcl_core.config import configured_api_url

        assert configured_api_url({"wcl_api_url": " https://classic.warcraftlogs.com/api/v2/client "}) == (
            "https://classic.warcraftlogs.com/api/v2/client"
        )
        assert configured_api_url({"wcl_api_url": ""}) is None
        assert configured_api_url({"wcl_api_url": "   "}) is None
        assert configured_api_url({}) is None

    def test_the_guild_id_is_a_number_or_none(self):
        from wcl_core.config import configured_guild_id

        assert configured_guild_id({"guild_id": "774065"}) == 774065
        assert configured_guild_id({"guild_id": 12}) == 12
        assert configured_guild_id({"guild_id": ""}) is None
        assert configured_guild_id({"guild_id": "toads"}) is None
        assert configured_guild_id({"guild_id": True}) is None
        assert configured_guild_id({"guild_id": None}) is None
        assert configured_guild_id({}) is None

    def test_without_a_config_they_read_config_json(self, monkeypatch):
        from wcl_core import config

        monkeypatch.setattr(
            config, "load_config", lambda: {"wcl_api_url": "https://sod.warcraftlogs.com", "guild_id": 7}
        )
        assert config.configured_api_url() == "https://sod.warcraftlogs.com"
        assert config.configured_guild_id() == 7

    def test_an_unreadable_config_json_names_nothing(self, monkeypatch):
        from wcl_core import config
        from wcl_core.common.errors import ConfigurationError

        def missing():
            raise ConfigurationError("no config.json")

        monkeypatch.setattr(config, "load_config", missing)
        assert config.configured_api_url() is None
        assert config.configured_guild_id() is None


class TestReportLinks:
    def _raid(self, game_version=None):
        from wcl_core.models import RaidMetadata

        return RaidMetadata(report_id="abc123", title="Karazhan", owner="toad", start_time=0, game_version=game_version)

    def test_a_raid_links_to_the_site_it_was_fetched_from_whatever_the_config_says(self, monkeypatch):
        from wcl_core import config

        monkeypatch.setattr(
            config, "load_config", lambda: {"wcl_api_url": "https://fresh.warcraftlogs.com/api/v2/client"}
        )
        assert self._raid("classic").url == "https://classic.warcraftlogs.com/reports/abc123"
        assert self._raid("retail").url == "https://www.warcraftlogs.com/reports/abc123"

    def test_a_raid_from_before_eras_were_read_links_to_the_configured_site(self, monkeypatch):
        from wcl_core import config

        monkeypatch.setattr(
            config, "load_config", lambda: {"wcl_api_url": "https://sod.warcraftlogs.com/api/v2/client"}
        )
        assert self._raid().url == "https://sod.warcraftlogs.com/reports/abc123"

    def test_a_site_not_announced_yet_links_to_the_main_site(self, monkeypatch):
        from wcl_core import config

        monkeypatch.setattr(config, "load_config", lambda: {})
        assert self._raid("forever").url == "https://www.warcraftlogs.com/reports/abc123"
        assert self._raid().url == "https://www.warcraftlogs.com/reports/abc123"


class TestAClientForARaidsSite:
    CONFIG = {
        "client_id": "id",
        "client_secret": "secret",
        "wcl_api_url": "https://fresh.warcraftlogs.com/api/v2/client",
    }

    def test_the_same_site_reuses_the_contexts_client(self):
        from wcl_app import AppContext

        ctx = AppContext(config=dict(self.CONFIG))
        assert ctx.client_for("fresh") is ctx.wcl_client

    def test_another_site_gets_a_client_of_its_own_with_the_same_credentials(self):
        from wcl_app import AppContext

        ctx = AppContext(config=dict(self.CONFIG))
        client = ctx.client_for("classic")
        assert client.api_url == "https://classic.warcraftlogs.com/api/v2/client"
        assert client is not ctx.wcl_client
        assert client.token_manager.client_id == "id"

    def test_an_unknown_site_keeps_the_contexts_client(self):
        from wcl_app import AppContext

        ctx = AppContext(config=dict(self.CONFIG))
        assert ctx.client_for(None) is ctx.wcl_client
        assert ctx.client_for("forever") is ctx.wcl_client

    def test_a_headless_host_always_gets_its_own_client(self):
        from contextlib import nullcontext

        from wcl_app import AppContext
        from wcl_core.auth import TokenManager
        from wcl_core.client import WarcraftLogsClient

        client = WarcraftLogsClient(TokenManager("host", "secret"))
        ctx = AppContext.headless(client, storage=lambda: nullcontext())
        assert ctx.client_for("classic") is client

    def test_without_credentials_it_says_which_is_missing(self):
        from wcl_app import AppContext
        from wcl_core.common.errors import ConfigurationError

        with pytest.raises(ConfigurationError, match="client_id"):
            AppContext(config={"wcl_api_url": self.CONFIG["wcl_api_url"]}).client_for("classic")

    def test_the_guild_and_host_fall_back_to_config_json_through_the_accessors(self):
        from wcl_app import AppContext

        assert AppContext(config={"guild_id": "not a number"}).guild_id is None
        assert AppContext(config={"guild_id": "42", "wcl_api_url": " "}).guild_id == 42
        assert AppContext(config={"wcl_api_url": " "}).api_url is None
