"""Which Warcraft Logs site a report lives on, and which expansion its zone belongs to.

Two axes, kept apart on purpose (see ``guides/identity_and_profiles.md``):

- a **game version** is a Warcraft Logs site: ``fresh`` (Anniversary realms, which went from Classic into The
  Burning Crusade), ``classic`` (Classic Era and Hardcore), ``sod`` (Season of Discovery) and ``retail``. It
  is derived from the API host a report was fetched through.
- an **expansion** is the content era of a report's zone: ``Classic``, ``The Burning Crusade`` and so on. The
  API reports it as ``zone { expansion { name } }``; raids stored before that was read are backfilled from the
  zone name through ``ZONE_EXPANSIONS``.

Both are plain strings in storage so a value this module does not know is kept, not dropped.
"""

from __future__ import annotations

from urllib.parse import urlparse

FRESH = "fresh"
CLASSIC = "classic"
SOD = "sod"
RETAIL = "retail"

GAME_VERSIONS: tuple[str, ...] = (FRESH, CLASSIC, SOD, RETAIL)

# Warcraft Logs site per game version, for building API URLs and report links.
HOSTS: dict[str, str] = {
    FRESH: "https://fresh.warcraftlogs.com",
    CLASSIC: "https://classic.warcraftlogs.com",
    SOD: "https://sod.warcraftlogs.com",
    RETAIL: "https://www.warcraftlogs.com",
}

CLASSIC_ERA = "Classic"
BURNING_CRUSADE = "The Burning Crusade"
WRATH = "Wrath of the Lich King"

EXPANSIONS: tuple[str, ...] = (CLASSIC_ERA, BURNING_CRUSADE, WRATH)

# Raid zones by the name Warcraft Logs reports, for backfilling raids stored without an expansion.
ZONE_EXPANSIONS: dict[str, str] = {
    "Molten Core": CLASSIC_ERA,
    "Onyxia's Lair": CLASSIC_ERA,
    "Blackwing Lair": CLASSIC_ERA,
    "Zul'Gurub": CLASSIC_ERA,
    "Ruins of Ahn'Qiraj": CLASSIC_ERA,
    "Temple of Ahn'Qiraj": CLASSIC_ERA,
    "Naxxramas": CLASSIC_ERA,
    "Karazhan": BURNING_CRUSADE,
    "Gruul's Lair": BURNING_CRUSADE,
    "Magtheridon's Lair": BURNING_CRUSADE,
    "Serpentshrine Cavern": BURNING_CRUSADE,
    "Tempest Keep": BURNING_CRUSADE,
    "The Eye": BURNING_CRUSADE,
    "Hyjal Summit": BURNING_CRUSADE,
    "Battle for Mount Hyjal": BURNING_CRUSADE,
    "Black Temple": BURNING_CRUSADE,
    "Zul'Aman": BURNING_CRUSADE,
    "Sunwell Plateau": BURNING_CRUSADE,
    "Ulduar": WRATH,
    "Trial of the Crusader": WRATH,
    "Icecrown Citadel": WRATH,
    "The Ruby Sanctum": WRATH,
    "Vault of Archavon": WRATH,
    "The Obsidian Sanctum": WRATH,
    "The Eye of Eternity": WRATH,
}


def game_version_for_url(api_url: str | None) -> str:
    """The game version of a Warcraft Logs API or site URL; an unknown or empty host is ``retail``."""
    host = (urlparse(api_url or "").hostname or "").lower()
    first = host.split(".", 1)[0] if host else ""
    if first in (FRESH, CLASSIC, SOD):
        return first
    return RETAIL


def api_url_for(game_version: str) -> str:
    """The client-credentials API URL of a game version's site."""
    return f"{host_for(game_version)}/api/v2/client"


def host_for(game_version: str) -> str:
    """The site of a game version; an unknown version falls back to retail."""
    return HOSTS.get(game_version, HOSTS[RETAIL])


def expansion_for_zone(zone: str | None) -> str | None:
    """The expansion a zone name belongs to, or None when the zone is unknown or empty."""
    if not zone:
        return None
    name = zone.strip()
    if name in ZONE_EXPANSIONS:
        return ZONE_EXPANSIONS[name]
    folded = name.casefold()
    for known, expansion in ZONE_EXPANSIONS.items():
        if known.casefold() == folded:
            return expansion
    return None
