"""Game versions and expansions (``wcl_core.game_version``): the two era axes behind raid profiles."""

import pytest
from wcl_core import game_version as gv


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://fresh.warcraftlogs.com/api/v2/client", "fresh"),
        ("https://classic.warcraftlogs.com/api/v2/user", "classic"),
        ("https://sod.warcraftlogs.com/", "sod"),
        ("https://www.warcraftlogs.com/api/v2/client", "retail"),
        ("https://FRESH.warcraftlogs.com", "fresh"),
        ("", "retail"),
        (None, "retail"),
        ("not a url", "retail"),
    ],
)
def test_game_version_comes_from_the_host(url, expected):
    assert gv.game_version_for_url(url) == expected


def test_every_game_version_round_trips_through_its_api_url():
    for version in gv.GAME_VERSIONS:
        assert gv.game_version_for_url(gv.api_url_for(version)) == version
        assert gv.api_url_for(version).endswith("/api/v2/client")
    assert gv.host_for("nope") == gv.HOSTS[gv.RETAIL]


@pytest.mark.parametrize(
    ("zone", "expected"),
    [
        ("Molten Core", "Classic"),
        ("Naxxramas", "Classic"),
        ("Karazhan", "The Burning Crusade"),
        ("karazhan", "The Burning Crusade"),
        ("  Sunwell Plateau ", "The Burning Crusade"),
        ("Icecrown Citadel", "Wrath of the Lich King"),
        ("Somewhere New", None),
        ("", None),
        (None, None),
    ],
)
def test_expansion_comes_from_the_zone_catalogue(zone, expected):
    assert gv.expansion_for_zone(zone) == expected


def test_catalogue_only_names_known_expansions():
    assert set(gv.ZONE_EXPANSIONS.values()) <= set(gv.EXPANSIONS)
