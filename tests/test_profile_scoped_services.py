"""Every service that reads raids follows the active profile (PROF-07); no profile reads everything (PROF-03)."""

from __future__ import annotations

from datetime import datetime

import pytest
from wcl_app import AppContext, BadgeService, HealingService, PlayerPageService, ReferenceService
from wcl_app.home import _Snapshot
from wcl_app.lineage import character_lineage
from wcl_app.profiles import JsonProfileStore, Profile, ProfileService, ProfileSet
from wcl_core import paths

from warcraftlogs_client.models import ConsumableUsage

TBC = "The Burning Crusade"
DAY = 86_400_000
# Three guild raids a week apart ending "now", so the healing window sees them all.
NOW = datetime(2026, 10, 3, 20, 0)
T0 = int(datetime(2026, 9, 19, 20, 0).timestamp() * 1000)
MC, KARA, GRUUL, REF = "MoltenCoreMolten", "KaraKaraKaraKara", "GruulGruulGruulG", "ReferenceRaid000"
CLASSIC_DAYS = Profile("classic", "Classic days", expansions=("Classic",))
TBC_ONLY = Profile("tbc", "TBC", expansions=(TBC,))


@pytest.fixture
def ctx(tmp_path, build_analysis):
    """MC (Classic) and Kara (TBC) tagged, Gruul untagged; a TBC reference raid. HolyPriest heals and drinks in each."""
    context = AppContext(config={}, db_path=str(tmp_path / "scoped.db"))
    with context.repository() as repo:
        for n, code in enumerate((MC, KARA, GRUUL)):
            repo.import_raid(
                build_analysis(
                    report_id=code,
                    start_time=T0 + n * 7 * DAY,
                    consumables=[ConsumableUsage("HolyPriest", "healer", code, "Super Mana Potion", n + 1)],
                )
            )
        repo.import_raid(
            build_analysis(
                report_id=REF,
                start_time=T0 + 8 * DAY,
                consumables=[ConsumableUsage("HolyPriest", "healer", REF, "Super Mana Potion", 50)],
            ),
            source="reference",
        )
        repo.set_raid_era(MC, "fresh", "Classic")
        repo.set_raid_era(KARA, "fresh", TBC)
        repo.set_raid_era(REF, "classic", TBC)
    return context


def _holy(service: BadgeService):
    badges = {b.id: b for b in service.for_character("HolyPriest").badges}
    return badges["attendance"].value, badges["mana_potions"].value


def test_badges_follow_the_profile(ctx):
    assert _holy(BadgeService.from_context(ctx)) == (3, 6)
    ctx.use_profile(CLASSIC_DAYS)
    assert _holy(BadgeService.from_context(ctx)) == (2, 4)  # MC and the untagged Gruul
    ctx.use_profile(TBC_ONLY)
    assert _holy(BadgeService.from_context(ctx)) == (2, 5)
    guild = {p.name: p for p in BadgeService.from_context(ctx).for_guild()}
    assert {b.id: b.value for b in guild["HolyPriest"].badges}["attendance"] == 2


def test_badges_counting_references_narrow_the_profile_to_those_sources(ctx):
    ctx.use_profile(TBC_ONLY)
    service = BadgeService(ctx.repository, sources=("guild", "reference"), scope=ctx.scope)
    assert _holy(service) == (3, 55)  # Kara, Gruul and the TBC reference raid


def test_home_badge_counts_follow_the_profile(ctx):
    ctx.use_profile(CLASSIC_DAYS)
    with ctx.repository() as repo:
        stats = _Snapshot(repo, NOW.date(), ctx.scope).badge_stats
        assert stats["holypriest"].raids == 2
        assert _Snapshot(repo, NOW.date()).badge_stats["holypriest"].raids == 3


def test_weekly_healing_follows_the_profile(ctx):
    def raids() -> int:
        return HealingService(ctx.repository, now=lambda: NOW, scope=ctx.scope).weekly().raids

    assert raids() == 3
    ctx.use_profile(TBC_ONLY)
    assert raids() == 2
    ctx.use_profile(Profile("era", "Era", game_version="classic"))
    assert raids() == 1  # only the untagged Gruul; the Classic-host reference is not a guild raid
    assert HealingService.from_context(ctx).scope == ctx.scope


def test_reference_lists_follow_the_profile(ctx):
    service = ReferenceService(ctx)
    assert [r.report_id for r in service.references()] == [REF]
    assert [r.report_id for r in service.guild_raids()] == [GRUUL, KARA, MC]
    ctx.use_profile(CLASSIC_DAYS)
    assert [r.report_id for r in service.references()] == []
    assert [r.report_id for r in service.guild_raids()] == [GRUUL, MC]


def test_player_page_lineage_and_badges_follow_the_profile(ctx):
    from wcl_app import PlayerRef

    holy = PlayerRef.create("HolyPriest", "spineshatter", "eu")
    with ctx.repository() as repo:
        page = PlayerPageService.from_context(ctx, repo, with_api=False).get_page(holy)
        assert page.lineage is not None and page.lineage.raids == 3
        ctx.use_profile(TBC_ONLY)
        page = PlayerPageService.from_context(ctx, repo, with_api=False).get_page(holy)
        assert page.lineage is not None and page.lineage.raids == 2
        assert {b.id: b.value for b in page.badges.badges}["attendance"] == 2

        assert character_lineage(repo, "HolyPriest", ("reference",), scope=ctx.scope).raids == 1
        assert character_lineage(repo, "HolyPriest", scope=CLASSIC_DAYS.scope).raids == 2
        assert character_lineage(repo, "HolyPriest", scope=Profile("z", "Z", zones=("Nowhere",)).scope) is None


def test_services_built_once_follow_a_later_profile_switch(ctx, tmp_path):
    """A frontend builds a service at start-up; switching profile afterwards still reaches it (PROF-07)."""
    from wcl_app import PlayerRef

    holy = PlayerRef.create("HolyPriest", "spineshatter", "eu")
    badges = BadgeService.from_context(ctx)
    healing = HealingService.from_context(ctx)
    healing.now = lambda: NOW
    profiles = ProfileService(JsonProfileStore(tmp_path / "switch.json"), ctx)
    profiles.create("TBC", expansions=(TBC,))
    with ctx.repository() as repo:
        page = PlayerPageService.from_context(ctx, repo, with_api=False)
        assert (_holy(badges), healing.weekly().raids, page.get_page(holy).lineage.raids) == ((3, 6), 3, 3)
        profiles.activate("tbc")
        assert (_holy(badges), healing.weekly().raids, page.get_page(holy).lineage.raids) == ((2, 5), 2, 2)
        profiles.activate(None)
        assert (_holy(badges), healing.weekly().raids) == ((3, 6), 3)


def test_a_fixed_scope_stays_fixed_when_the_profile_switches(ctx):
    service = BadgeService(ctx.repository, scope=CLASSIC_DAYS.scope)
    ctx.use_profile(TBC_ONLY)
    assert _holy(service) == (2, 4)


def test_the_desktop_context_starts_in_the_saved_profile(ctx):
    assert AppContext.desktop(with_config=False).profile is None  # nothing saved: the plain app
    JsonProfileStore(paths.get_profiles_path()).save(ProfileSet(profiles=[TBC_ONLY], active="tbc"))
    desktop = AppContext.desktop(with_config=False, db_path=ctx.db_path)
    assert desktop.profile == TBC_ONLY
    assert [r.report_id for r in ReferenceService(desktop).guild_raids()] == [GRUUL, KARA]


def test_character_history_follows_the_profile(ctx):
    """Closes PROF-07: the player page's history and PlayerService.history read under the profile."""
    from wcl_app import PlayerRef, PlayerService

    holy = PlayerRef.create("HolyPriest", "spineshatter", "eu")
    players = PlayerService(ctx)
    assert players.history("HolyPriest").total_raids == 3
    ctx.use_profile(CLASSIC_DAYS)
    assert players.history("HolyPriest").total_raids == 2
    with ctx.repository() as repo:
        page = PlayerPageService.from_context(ctx, repo, with_api=False)
        assert page.get_page(holy).history["total_raids"] == 2
    ctx.use_profile(Profile("z", "Z", zones=("Nowhere",)))
    assert players.history("HolyPriest") is None


def test_the_home_page_follows_a_later_profile_switch(ctx):
    from wcl_app import HomeService

    home = HomeService.from_context(ctx)
    assert home.scope is None
    ctx.use_profile(TBC_ONLY)
    assert home.scope == TBC_ONLY.scope


def test_the_desktop_profile_service_switches_and_counts_on_the_shared_context(ctx):
    profiles = ProfileService.desktop(ctx)
    assert profiles.store.path == paths.get_profiles_path()
    assert profiles.raid_count() == 3
    profiles.create("TBC", expansions=(TBC,), activate=True)
    assert ctx.profile is not None and profiles.raid_count() == 2  # Kara and the untagged Gruul
    profiles.activate(None)
    assert profiles.raid_count() == 3
    assert ProfileService.desktop().ctx is not None
    with pytest.raises(ValueError, match="needs a context"):
        ProfileService(profiles.store).raid_count()


def test_a_storage_failure_gives_no_raid_count(ctx):
    from wcl_store import StorageError

    def broken():
        raise StorageError("database is locked")

    ctx.storage = broken
    assert ProfileService.desktop(ctx).raid_count() is None
