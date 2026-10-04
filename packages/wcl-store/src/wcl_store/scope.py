"""``RaidScope``: the filter the services hand a ``RaidRepository`` read.

A scope narrows which stored raids a query sees: by source, by game version and expansion (the two era axes
``wcl_core.game_version`` defines), by zone and by a ``raid_date`` window. An empty tuple on an axis means
"any". A raid whose ``game_version`` or ``expansion`` is unknown (``NULL``, i.e. stored before they were read
and not backfilled) matches every scope on that axis, so a report never disappears from every view.

``None`` in place of a scope keeps each method's historic behaviour; ``RaidScope()`` is the same thing spelled
out: guild raids, any era.

``RaidScope.admits`` is the same rule for a raid that is not stored yet, such as a report in a guild's list on
Warcraft Logs, so an import under a profile fetches only the raids the profile will show. The contract tests check
it agrees with both backends.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RaidScope:
    sources: tuple[str, ...] = ("guild",)
    game_versions: tuple[str, ...] = ()
    expansions: tuple[str, ...] = ()
    zones: tuple[str, ...] = ()  # matched ignoring ASCII case, like character names
    since: str | None = None  # "YYYY-MM-DD HH:MM:SS" on raid_date, inclusive
    until: str | None = None  # exclusive

    @property
    def unfiltered(self) -> bool:
        """True when the scope only picks sources, which every read already did."""
        return not (self.game_versions or self.expansions or self.zones or self.since or self.until)

    def admits(
        self,
        *,
        source: str = "guild",
        game_version: str | None = None,
        expansion: str | None = None,
        zone: str | None = None,
        raid_date: str | None = None,
    ) -> bool:
        """Whether a raid with these values is inside the scope, by the rule the repository reads apply.

        ``raid_date`` is ``"YYYY-MM-DD HH:MM:SS"`` like the stored column; an unknown era matches every era.
        """
        if source not in self.sources:
            return False
        if self.game_versions and game_version and game_version not in self.game_versions:
            return False
        if self.expansions and expansion and expansion not in self.expansions:
            return False
        if self.zones and _ascii_fold(zone or "") not in {_ascii_fold(z) for z in self.zones}:
            return False
        if self.since and (raid_date or "") < self.since:
            return False
        return not (self.until and (raid_date or "") >= self.until)

    def with_sources(self, sources: tuple[str, ...]) -> RaidScope:
        return RaidScope(
            sources=sources,
            game_versions=self.game_versions,
            expansions=self.expansions,
            zones=self.zones,
            since=self.since,
            until=self.until,
        )


GUILD = RaidScope()

_ASCII_UPPER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _ascii_fold(text: str) -> str:
    """Lower-case ASCII letters only, as SQLite's ``NOCASE`` and the Postgres backend compare zones."""
    return text.translate(_ASCII_UPPER)


def narrowed(scope: RaidScope | None, sources: tuple[str, ...]) -> RaidScope | None:
    """``scope`` limited to ``sources``, or None when there is no scope.

    A scope's ``sources`` replaces a read's ``sources`` argument, so a service that reads reference raids (or
    guild and reference together) under the active profile narrows the profile's scope to those sources first.
    """
    return scope.with_sources(sources) if scope is not None else None
