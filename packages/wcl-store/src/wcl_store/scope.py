"""``RaidScope``: the filter the services hand a ``RaidRepository`` read.

A scope narrows which stored raids a query sees: by source, by game version and expansion (the two era axes
``wcl_core.game_version`` defines), by zone and by a ``raid_date`` window. An empty tuple on an axis means
"any". A raid whose ``game_version`` or ``expansion`` is unknown (``NULL``, i.e. stored before they were read
and not backfilled) matches every scope on that axis, so a report never disappears from every view.

``None`` in place of a scope keeps each method's historic behaviour; ``RaidScope()`` is the same thing spelled
out: guild raids, any era.
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


def narrowed(scope: RaidScope | None, sources: tuple[str, ...]) -> RaidScope | None:
    """``scope`` limited to ``sources``, or None when there is no scope.

    A scope's ``sources`` replaces a read's ``sources`` argument, so a service that reads reference raids (or
    guild and reference together) under the active profile narrows the profile's scope to those sources first.
    """
    return scope.with_sources(sources) if scope is not None else None
