"""
Search stored raids and the tabs of a raid page, so a frontend can jump straight to "Karazhan, healing".

``SearchService(ctx).index()`` reads the active profile's raids once; ``ReportIndex.search(query)`` then answers each
keystroke without touching storage. A query is any mix of raid words (title, zone, owner, date, weekday, report
code) and tab words ("healing", "kicks", "pots"). A pasted report code or Warcraft Logs URL finds that raid, and the
URL's ``type=`` view picks the tab.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from wcl_core.common.log import get_logger
from wcl_store import StorageError

from wcl_app.context import AppContext
from wcl_app.player_page import parse_report_code


@dataclass(frozen=True)
class ReportTab:
    """A tab of the raid page: ``label`` is its title there, ``terms`` the words that find it."""

    key: str
    label: str
    terms: tuple[str, ...]


REPORT_TABS: tuple[ReportTab, ...] = (
    ReportTab("healers", "Healers", ("healers", "healing", "heals", "overhealing", "hps")),
    ReportTab("tanks", "Tanks", ("tanks", "tanking", "mitigation", "damage taken")),
    ReportTab("melee", "Melee DPS", ("melee", "dps", "damage done")),
    ReportTab("ranged", "Ranged DPS", ("ranged", "dps", "casters", "damage done")),
    ReportTab("consumables", "Consumables", ("consumables", "consumes", "potions", "pots", "flasks", "elixirs")),
    ReportTab("interrupts", "Interrupts", ("interrupts", "kicks")),
    ReportTab("cast_efficiency", "Cast Efficiency", ("cast efficiency", "casts", "cooldowns")),
    ReportTab("debuff_uptime", "Debuff Uptime", ("debuff uptime", "debuffs")),
    ReportTab("totem_uptime", "Totem Uptime", ("totem uptime", "totems")),
    ReportTab("boss_vs_trash", "Boss vs Trash", ("boss vs trash", "trash")),
    ReportTab("engineering", "Engineering", ("engineering", "sappers", "bombs")),
    ReportTab("timeline", "Timeline", ("timeline",)),
    ReportTab("encounters", "Encounters", ("encounters", "bosses", "fights", "kills", "wipes")),
    ReportTab("composition", "Composition", ("composition", "comp", "roster")),
)

# The view names Warcraft Logs puts in a report URL's ``type=``, mapped to the tab that shows the same thing.
# Damage done is one view there and two tabs here, so it offers both.
_WCL_VIEW_TABS = {
    "healing": ("healers",),
    "damage-taken": ("tanks",),
    "damage-done": ("melee", "ranged"),
    "casts": ("cast_efficiency",),
    "interrupts": ("interrupts",),
    "debuffs": ("debuff_uptime",),
    "summary": ("composition",),
}

_TABS_BY_KEY = {tab.key: tab for tab in REPORT_TABS}
_MIN_PREFIX = 3  # "he" would find half the tabs; "hea" is the shortest prefix that means something
_TAB_ONLY_RAIDS = 5  # a bare "healing" lists that tab of the newest raids
_WORD_RE = re.compile(r"[a-z0-9]+")

logger = get_logger(__name__)


@dataclass(frozen=True)
class SearchHit:
    """One result: a stored raid, opened at ``tab`` (None for its default tab).

    ``stored`` is False for a pasted report code or URL the database does not have yet, so the frontend can offer to
    analyse it instead of opening it.
    """

    report_id: str
    title: str
    raid_date: str = ""
    zone: str = ""
    tab: ReportTab | None = None
    stored: bool = True

    @property
    def label(self) -> str:
        """What a results list shows: date, title and zone, then the tab."""
        parts = [p for p in (self.raid_date[:10], self.title, self.zone if self.zone not in self.title else "") if p]
        text = "  ".join(parts) if self.stored else f"Analyze report {self.report_id}"
        return f"{text}  >  {self.tab.label}" if self.tab else text


def tab_by_key(key: str) -> ReportTab | None:
    return _TABS_BY_KEY.get(key)


def _tabs_for_word(word: str) -> set[str]:
    """Keys of the tabs one query word finds: a whole term word, or a prefix of one at least three letters long."""
    found = set()
    for tab in REPORT_TABS:
        for term in tab.terms:
            for term_word in term.split():
                if word == term_word or (len(word) >= _MIN_PREFIX and term_word.startswith(word)):
                    found.add(tab.key)
    return found


def _haystack(raid: dict[str, Any]) -> str:
    date = str(raid.get("raid_date") or "")
    try:
        weekday = datetime.fromisoformat(date).strftime("%A")
    except ValueError:
        weekday = ""
    fields = (raid.get("title"), raid.get("zone"), raid.get("owner"), raid.get("report_id"), date, weekday)
    return " ".join(str(f) for f in fields if f).lower()


def _hit(raid: dict[str, Any], tab: ReportTab | None = None) -> SearchHit:
    return SearchHit(
        report_id=str(raid["report_id"]),
        title=str(raid.get("title") or raid["report_id"]),
        raid_date=str(raid.get("raid_date") or ""),
        zone=str(raid.get("zone") or ""),
        tab=tab,
    )


class ReportIndex:
    """Stored raids, newest first, searchable without storage. ``error`` says why there are none if storage failed;
    a pasted report code still finds something to analyse."""

    def __init__(self, raids: list[dict[str, Any]], error: str | None = None):
        self.error = error
        self._raids = [(raid, _haystack(raid)) for raid in raids if raid.get("report_id")]
        self._by_code = {str(raid["report_id"]): raid for raid, _ in self._raids}

    def __len__(self) -> int:
        return len(self._raids)

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        query = (query or "").strip()
        if not query:
            return []
        linked = self._linked_report(query)
        if linked:
            return linked

        raid_words, tab_keys = self._split(query)
        tabs = [tab for tab in REPORT_TABS if tab.key in tab_keys]
        if not raid_words and not tabs:
            return []
        raids = [raid for raid, text in self._raids if all(word in text for word in raid_words)]
        if not raid_words:
            raids = raids[:_TAB_ONLY_RAIDS]
        if not tabs:
            return [_hit(raid) for raid in raids[:limit]]
        hits = [_hit(raid, tab) for raid in raids for tab in tabs]
        # A tab word can also be a raid's own word ("Tim", "trash run"): those raids follow, at their default tab.
        words = _WORD_RE.findall(query.lower())
        hits += [_hit(raid) for raid, text in self._raids if all(word in text for word in words)]
        return hits[:limit]

    def _linked_report(self, query: str) -> list[SearchHit]:
        """A pasted report code or Warcraft Logs URL, opened at the tabs its ``type=`` names."""
        if " " in query:
            return []
        code = parse_report_code(query)
        if code is None:
            return []
        tabs = _url_tabs(query) or (None,)
        raid = self._by_code.get(code)
        if raid is None and "/" not in query and code.isalpha() and code.islower():
            return []  # a sixteen-letter word, not a code: codes mix cases or carry digits
        if raid is None:
            return [SearchHit(report_id=code, title=code, tab=tab, stored=False) for tab in tabs]
        return [_hit(raid, tab) for tab in tabs]

    @staticmethod
    def _split(query: str) -> tuple[list[str], set[str]]:
        """The words that must match a raid, and the tabs the other words name.

        A word that names a tab is a tab word. Several tab words narrow to the tabs every one of them names ("debuff
        uptime" is one tab, not every uptime), unless they share none ("healing tanks" shows both).
        """
        raid_words: list[str] = []
        named: list[set[str]] = []
        for word in _WORD_RE.findall(query.lower()):
            keys = _tabs_for_word(word)
            if keys:
                named.append(keys)
            else:
                raid_words.append(word)
        if not named:
            return raid_words, set()
        common = set.intersection(*named)
        return raid_words, common or set.union(*named)


def _url_tabs(text: str) -> tuple[ReportTab, ...]:
    if "://" not in text and "type=" not in text:
        return ()
    parsed = urlparse(text)
    params = parse_qs(parsed.query) | parse_qs(parsed.fragment)
    view = (params.get("type") or [""])[0]
    return tuple(_TABS_BY_KEY[key] for key in _WCL_VIEW_TABS.get(view, ()))


class SearchService:
    """Builds a ``ReportIndex`` of the active profile's guild raids."""

    def __init__(self, ctx: AppContext, max_raids: int = 1000):
        self.ctx = ctx
        self.max_raids = max_raids

    def index(self) -> ReportIndex:
        try:
            with self.ctx.repository() as db:
                return ReportIndex(db.get_raid_list(limit=self.max_raids, scope=self.ctx.scope))
        except (StorageError, OSError) as e:
            logger.warning("Raid search could not read stored raids: %s", e)
            return ReportIndex([], error=str(e))
