"""Raid profiles (``wcl_app.profiles``): named views over one database, and how the context follows them."""

import json
from unittest.mock import MagicMock

import pytest
from warcraftlogs_client.services.profiles import MemoryProfileStore, slugify
from wcl_core.models import RaidMetadata
from wcl_store import RaidScope, narrowed
from wcl_store.sqlite import PerformanceDB

from warcraftlogs_client.services import AppContext, JsonProfileStore, Profile, ProfileService, ProfileSet, RaidService

TBC = "The Burning Crusade"
KARA = "KaraKaraKaraKara"
MC = "MoltenCoreMolten"


def _profile_service(tmp_path, ctx=None, owner=None):
    return ProfileService.from_context(
        ctx or AppContext(config={}), JsonProfileStore(tmp_path / "profiles.json"), owner
    )


class TestProfile:
    def test_scope_carries_every_axis(self):
        p = Profile(
            "tbc", "TBC", game_version="fresh", expansions=(TBC,), zones=("Karazhan",), since="2026-01-01 00:00:00"
        )
        assert p.scope == RaidScope(
            game_versions=("fresh",), expansions=(TBC,), zones=("Karazhan",), since="2026-01-01 00:00:00"
        )
        assert Profile("all", "All").scope == RaidScope()
        assert Profile("all", "All").scope.unfiltered

    def test_narrowed_limits_a_scope_to_sources_and_keeps_no_scope(self):
        tbc = Profile("tbc", "TBC", expansions=(TBC,)).scope
        assert narrowed(tbc, ("reference",)) == RaidScope(expansions=(TBC,), sources=("reference",))
        assert narrowed(None, ("reference",)) is None

    def test_api_url_follows_the_game_version_unless_given(self):
        assert Profile("era", "Era", game_version="classic").api_url == "https://classic.warcraftlogs.com/api/v2/client"
        assert Profile("x", "X", game_version="classic", wcl_api_url="https://example.test/api").api_url.startswith(
            "https://example"
        )
        assert Profile("all", "All").api_url is None
        assert Profile("forever", "Forever", game_version="forever").api_url is None  # no site announced yet

    def test_unknown_game_version_is_refused(self):
        with pytest.raises(ValueError, match="Unknown game version"):
            Profile("x", "X", game_version="wrath")

    def test_round_trips_through_dicts(self):
        p = Profile("tbc", "TBC", game_version="fresh", expansions=(TBC,), guild_id=774065, owner="1234")
        assert Profile.from_dict(json.loads(json.dumps(p.to_dict()))) == p
        assert Profile.from_dict({"name": "Classic days"}) == Profile("classic-days", "Classic days")
        assert Profile.from_dict({"slug": "era", "guild_id": "", "owner": None}) == Profile("era", "era")

    def test_profile_set_drops_an_active_slug_it_does_not_have(self):
        loaded = ProfileSet.from_dict({"active": "gone", "profiles": [{"name": "TBC"}, "junk"]})
        assert [p.slug for p in loaded.profiles] == ["tbc"] and loaded.active is None
        assert loaded.active_profile is None

    def test_slugify(self):
        assert slugify("  TBC: Phase 1 ") == "tbc-phase-1"
        with pytest.raises(ValueError):
            slugify("!!!")


class TestJsonProfileStore:
    def test_missing_or_broken_file_means_nothing_saved(self, tmp_path):
        store = JsonProfileStore(tmp_path / "missing" / "profiles.json")
        assert store.load() is None
        store.path.parent.mkdir()
        store.path.write_text("{not json", encoding="utf-8")
        assert store.load() is None
        store.path.write_text('{"profiles": [{"name": "X", "game_version": "wrath"}]}', encoding="utf-8")
        assert store.load() is None

    def test_saves_and_loads(self, tmp_path):
        store = JsonProfileStore(tmp_path / "nested" / "profiles.json")
        store.save(ProfileSet([Profile("tbc", "TBC", expansions=(TBC,))], active="tbc"))
        loaded = store.load()
        assert loaded is not None and loaded.active == "tbc" and loaded.profiles[0].expansions == (TBC,)
        assert json.loads(store.path.read_text(encoding="utf-8"))["version"] == 1


class TestProfileService:
    def test_create_activate_and_delete(self, tmp_path):
        ctx = AppContext(config={"guild_id": 1, "wcl_api_url": "https://fresh.warcraftlogs.com/api/v2/client"})
        service = _profile_service(tmp_path, ctx, owner="42")
        assert service.list() == [] and service.active() is None and service.scope() is None

        tbc = service.create("TBC", expansions=(TBC,), activate=True)
        assert tbc.owner == "42" and tbc.slug == "tbc"
        assert service.active() == tbc and ctx.profile == tbc and ctx.scope == RaidScope(expansions=(TBC,))
        with pytest.raises(ValueError, match="already exists"):
            service.create("tbc")

        era = service.create("Era", game_version="classic", guild_id=99)
        assert service.active() == tbc  # creating does not switch
        assert service.activate("era") == era
        assert ctx.guild_id == 99 and ctx.api_url == "https://classic.warcraftlogs.com/api/v2/client"
        assert service.activate(None) is None and ctx.profile is None
        assert ctx.guild_id == 1 and ctx.api_url == "https://fresh.warcraftlogs.com/api/v2/client"
        with pytest.raises(KeyError):
            service.activate("nope")

        service.activate("tbc")
        assert service.delete("tbc") and not service.delete("tbc")
        assert service.active() is None and ctx.profile is None
        assert [p.slug for p in service.list()] == ["era"]

    def test_update_changes_one_profile(self, tmp_path):
        service = _profile_service(tmp_path)
        service.create("TBC", activate=True)
        updated = service.update("tbc", zones=("Karazhan",))
        assert updated.zones == ("Karazhan",) and service.active() == updated
        with pytest.raises(KeyError):
            service.update("nope", zones=())

    def test_apply_puts_the_saved_profile_on_the_context(self, tmp_path):
        ctx = AppContext(config={})
        store = MemoryProfileStore(ProfileSet([Profile("tbc", "TBC", expansions=(TBC,))], active="tbc"))
        service = ProfileService(store, ctx)
        assert service.apply() == store.profiles.profiles[0]
        assert ctx.scope == RaidScope(expansions=(TBC,))

    def test_switching_profiles_rebuilds_the_client_for_the_host(self, tmp_path):
        ctx = AppContext(
            config={
                "client_id": "id",
                "client_secret": "secret",
                "wcl_api_url": "https://fresh.warcraftlogs.com/api/v2/client",
            }
        )
        service = _profile_service(tmp_path, ctx)
        assert ctx.wcl_client.game_version == "fresh"
        service.create("Era", game_version="classic", activate=True)
        assert ctx.wcl_client.game_version == "classic"
        service.activate(None)
        assert ctx.wcl_client.game_version == "fresh"

    def test_headless_context_keeps_the_host_client_and_takes_the_profile(self):
        client = MagicMock()
        profile = Profile("era", "Era", game_version="classic")
        ctx = AppContext.headless(client, storage=MagicMock(), profile=profile)
        assert ctx.wcl_client is client and ctx.scope == RaidScope(game_versions=("classic",))
        ctx.use_profile(None)
        assert ctx.wcl_client is client and ctx.scope is None

    def test_backfill_tags_stored_raids_from_the_zone_and_the_configured_host(self, tmp_path, sample_raid_analysis):
        db_path = str(tmp_path / "t.db")
        ctx = AppContext(config={"wcl_api_url": "https://fresh.warcraftlogs.com/api/v2/client"}, db_path=db_path)
        sample_raid_analysis.metadata = RaidMetadata(KARA, "Kara", "Us", 1_700_000_000_000, zone="Karazhan")
        with PerformanceDB(db_path) as db:
            db.import_raid(sample_raid_analysis)
            sample_raid_analysis.metadata = RaidMetadata(MC, "MC", "Us", 1_700_000_000_000, zone="Molten Core")
            db.import_raid(sample_raid_analysis)
            sample_raid_analysis.metadata = RaidMetadata(
                "NewZoneNewZoneNe", "?", "Us", 1_700_000_000_000, zone="Unknown"
            )
            db.import_raid(sample_raid_analysis)

        service = _profile_service(tmp_path, ctx)
        assert service.backfill_eras() == 3
        assert service.backfill_eras() == 0  # the unknown zone keeps its host but stays unknown, once
        with PerformanceDB(db_path) as db:
            eras = {r["report_id"]: (r["game_version"], r["expansion"]) for r in db.get_raids_by_source("guild")}
        assert eras == {
            KARA: ("fresh", TBC),
            MC: ("fresh", "Classic"),
            "NewZoneNewZoneNe": ("fresh", None),
        }

        service.create("Classic days", expansions=("Classic",), activate=True)
        assert {r["report_id"] for r in RaidService(ctx).list_raids()} == {MC, "NewZoneNewZoneNe"}
        assert RaidService(ctx).count_raids() == 2
        service.activate(None)
        assert RaidService(ctx).count_raids() == 3


def test_raid_service_guild_comes_from_the_profile_then_config():
    client = MagicMock(api_url="https://www.warcraftlogs.com/api/v2/client")
    ctx = AppContext(config={"guild_id": "7"}, _client=client)
    RaidService(ctx).guild_reports()
    client.get_guild_reports.assert_called_with(7)
    ctx.use_profile(Profile("era", "Era", guild_id=9))
    RaidService(ctx).guild_info()
    client.get_guild_info.assert_called_with(9)
    RaidService(ctx).guild_info(3)
    client.get_guild_info.assert_called_with(3)
    with pytest.raises(ValueError, match="No guild"):
        RaidService(AppContext(config={}, _client=client)).guild_reports()
