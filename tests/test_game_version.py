"""Game versions and expansions (``wcl_core.game_version``): the two era axes behind raid profiles."""

import pytest
from wcl_core import game_version as gv


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://fresh.warcraftlogs.com/api/v2/client", "fresh"),
        ("https://classic.warcraftlogs.com/api/v2/user", "classic"),
        ("https://sod.warcraftlogs.com/", "sod"),
        ("https://forever.warcraftlogs.com/api/v2/client", "forever"),
        ("https://www.warcraftlogs.com/api/v2/client", "retail"),
        ("https://FRESH.warcraftlogs.com", "fresh"),
        ("", "retail"),
        (None, "retail"),
        ("not a url", "retail"),
    ],
)
def test_game_version_comes_from_the_host(url, expected):
    assert gv.game_version_for_url(url) == expected


def test_every_hosted_game_version_round_trips_through_its_api_url():
    for version in gv.HOSTS:
        url = gv.api_url_for(version)
        assert url is not None and url.endswith("/api/v2/client")
        assert gv.game_version_for_url(url) == version


def test_forever_is_a_game_version_without_a_host_yet():
    assert gv.FOREVER in gv.GAME_VERSIONS
    assert gv.host_for(gv.FOREVER) is None and gv.api_url_for(gv.FOREVER) is None
    assert gv.host_for("nope") is None


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
