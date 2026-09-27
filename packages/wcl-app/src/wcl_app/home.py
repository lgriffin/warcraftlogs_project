"""
Home page: a catalogue of widgets, the layout a user picks from it, and the data each widget shows.

Every frontend renders the same payloads. A widget is one of five kinds, and each kind fills its own fields:

    stats    ``tiles``    big numbers (raids stored, days since the last raid, ...)
    table    ``columns`` and ``rows``
    list     ``items``
    bars     ``bars``     one labelled value per bar, drawn as a bar chart
    actions  ``actions``  shortcuts to other parts of the app

``HomeWidget.to_dict()`` is the JSON shape the Toads Hub serves, documented in ``guides/home_widgets.md``.
Values arrive both raw (``value`` / ``values``) and formatted (``display`` / ``cells``), so a frontend never
formats numbers or dates itself. Links name what to open (a raid, a character, a player page or an action)
and each frontend maps them onto its own navigation.

The layout is an ordered list of widget ids. Where it is kept is up to the host: the desktop app keeps it
in a JSON file (``JsonLayoutStore``), the Toads Hub per member in its own database.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any, Protocol

from wcl_core.models import RaidAnalysis
from wcl_store import RaidRepository, StorageError

from wcl_app.context import AppContext, StorageFactory

HOME_SCHEMA_VERSION = 1

# Widget kinds
STATS = "stats"
TABLE = "table"
LIST = "list"
BARS = "bars"
ACTIONS = "actions"

# Widget sizes: a full-width row, or half a row next to another half widget.
FULL = "full"
HALF = "half"

# Link kinds and the params each carries.
RAID = "raid"  # report_id
CHARACTER = "character"  # name
PLAYER_PAGE = "player_page"  # name, server, region
ACTION = "action"  # id, one of the quick action ids below

ATTENDANCE_WINDOW = 10  # raids counted for attendance and active raiders
ACTIVITY_WEEKS = 8
RECENT_RAIDS = 8
TOP_N = 5

# Enough to list every stored raid; get_raid_list requires a limit.
_ALL_RAIDS = 100_000


# ── Payloads ──


@dataclass
class Link:
    kind: str
    params: dict[str, str]


@dataclass
class Tile:
    label: str
    value: int | float | str | None
    display: str
    hint: str = ""


@dataclass
class Column:
    key: str
    label: str
    align: str = "left"  # "left" or "right"


@dataclass
class Row:
    cells: dict[str, str]  # column key -> display text
    values: dict[str, int | float | str | None]  # column key -> raw value
    link: Link | None = None


@dataclass
class ListItem:
    label: str
    detail: str = ""
    link: Link | None = None


@dataclass
class Bar:
    label: str
    value: float
    display: str


@dataclass
class Action:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class WidgetSpec:
    """A widget a user can put on their home page."""

    id: str
    title: str
    description: str
    kind: str
    size: str = HALF
    default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_KIND_FIELDS = {
    STATS: ("tiles",),
    TABLE: ("columns", "rows"),
    LIST: ("items",),
    BARS: ("bars",),
    ACTIONS: ("actions",),
}


@dataclass
class HomeWidget:
    """One widget's data. ``empty`` says why there is nothing to show; ``error`` that loading it failed."""

    id: str
    title: str
    kind: str
    size: str
    subtitle: str = ""
    link: Link | None = None
    tiles: list[Tile] = field(default_factory=list)
    columns: list[Column] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    items: list[ListItem] = field(default_factory=list)
    bars: list[Bar] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    empty: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON shape: the common fields plus only the fields of this widget's kind."""
        data = asdict(self)
        keep = {"id", "title", "kind", "size", "subtitle", "link", "empty", "error", *_KIND_FIELDS[self.kind]}
        return {k: v for k, v in data.items() if k in keep}


@dataclass
class HomePage:
    widgets: list[HomeWidget]
    generated_at: str  # local time, "YYYY-MM-DD HH:MM:SS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": HOME_SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "widgets": [w.to_dict() for w in self.widgets],
        }


# ── Catalogue ──

QUICK_ACTIONS = (
    Action("raids.download", "Import a report", "Analyse a Warcraft Logs report and store it"),
    Action("raids.browse", "Browse raids", "Every stored raid, newest first"),
    Action("raids.diff", "Compare raids", "Put two raids side by side"),
    Action("characters", "Find a character", "Search, profile and compare characters"),
    Action("characters.player", "Player page", "Collect one character's logs from Warcraft Logs"),
    Action("insights", "Insights", "Performance trends and boss analytics"),
    Action("raid_groups", "Raid groups", "Manage raid groups and their members"),
)

CATALOGUE: tuple[WidgetSpec, ...] = (
    WidgetSpec("quick_actions", "Quick actions", "Shortcuts to the things you do most", ACTIONS, FULL, True),
    WidgetSpec(
        "guild_snapshot", "Guild at a glance", "Raids stored, active raiders and raid cadence", STATS, FULL, True
    ),
    WidgetSpec("last_raid", "Last raid", "Duration, bosses, damage and healing of the latest raid", STATS, FULL, True),
    WidgetSpec("recent_raids", "Recent raids", "The latest raids, one click to open", LIST, HALF, True),
    WidgetSpec(
        "raid_activity", "Raid activity", f"Raids per week over the last {ACTIVITY_WEEKS} weeks", BARS, HALF, True
    ),
    WidgetSpec("top_damage", "Top damage", "Highest damage dealers in the last raid", TABLE, HALF, True),
    WidgetSpec("top_healing", "Top healing", "Highest healers in the last raid", TABLE, HALF, True),
    WidgetSpec("attendance", "Attendance", f"Who came to the last {ATTENDANCE_WINDOW} raids", TABLE, HALF, True),
    WidgetSpec("boss_kills", "Boss kills", "Every boss killed in the last raid and how long it took", TABLE, HALF),
    WidgetSpec("class_mix", "Class mix", "Players of each class in the last raid", BARS, HALF),
    WidgetSpec("interrupts", "Interrupts", "Most interrupts in the last raid", TABLE, HALF),
    WidgetSpec("consumables", "Consumables", "Most consumables used in the last raid", TABLE, HALF),
    WidgetSpec("tracked_players", "Tracked players", "Characters you follow with a player page", TABLE, HALF),
)
_SPECS = {s.id: s for s in CATALOGUE}


# ── Layout ──


@dataclass(frozen=True)
class HomeLayout:
    """The widgets on a user's home page, in order."""

    widgets: tuple[str, ...]

    @classmethod
    def default(cls) -> HomeLayout:
        return cls(tuple(s.id for s in CATALOGUE if s.default))

    @classmethod
    def of(cls, widget_ids: Iterable[str]) -> HomeLayout:
        """Layout of the given ids in order, dropping unknown ids and repeats. An empty page is allowed."""
        return cls(tuple(dict.fromkeys(i for i in widget_ids if i in _SPECS)))

    @classmethod
    def from_dict(cls, data: Any) -> HomeLayout:
        """Read a stored layout, falling back to the default if it is missing or malformed."""
        if not isinstance(data, dict) or not isinstance(data.get("widgets"), list):
            return cls.default()
        return cls.of(i for i in data["widgets"] if isinstance(i, str))

    def to_dict(self) -> dict[str, Any]:
        return {"version": HOME_SCHEMA_VERSION, "widgets": list(self.widgets)}

    def hidden(self) -> list[str]:
        """Catalogue widgets not on the page, in catalogue order."""
        return [s.id for s in CATALOGUE if s.id not in self.widgets]


class LayoutStore(Protocol):
    """Where a host keeps one user's layout."""

    def load(self) -> HomeLayout | None:
        """The saved layout, or None if nothing is saved."""
        ...

    def save(self, layout: HomeLayout | None) -> None:
        """Save the layout; None forgets it, so the default applies again."""
        ...


class MemoryLayoutStore:
    """Keeps the layout in memory: for tests, and hosts that persist it themselves."""

    def __init__(self, layout: HomeLayout | None = None):
        self.layout = layout

    def load(self) -> HomeLayout | None:
        return self.layout

    def save(self, layout: HomeLayout | None) -> None:
        self.layout = layout


class JsonLayoutStore:
    """Keeps the layout in a JSON file. A missing or unreadable file means nothing is saved."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> HomeLayout | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return HomeLayout.from_dict(data)

    def save(self, layout: HomeLayout | None) -> None:
        if layout is None:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(layout.to_dict(), indent=2), encoding="utf-8")


# ── Formatting ──


def compact(n: float) -> str:
    """12345678 -> "12.3M", 4500 -> "4.5K", 950 -> "950"."""
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= size:
            return f"{n / size:.1f}{suffix}"
    return f"{n:,.0f}"


def _duration(ms: int) -> str:
    seconds = max(ms, 0) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m {secs:02d}s"


def _parse_date(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def _day(dt: datetime | None, raw: str | None) -> str:
    if dt is None:
        return (raw or "")[:10] or "-"
    return f"{dt:%a} {dt.day} {dt:%b %Y}"


# ── Service ──


class _Snapshot:
    """The storage reads a page needs, each done at most once however many widgets use it."""

    def __init__(self, repo: RaidRepository):
        self.repo = repo

    @cached_property
    def raids(self) -> list[dict[str, Any]]:
        return self.repo.get_raid_list(limit=_ALL_RAIDS)

    @cached_property
    def last_raid(self) -> dict[str, Any] | None:
        return self.raids[0] if self.raids else None

    @cached_property
    def last_analysis(self) -> RaidAnalysis | None:
        return self.repo.get_raid_analysis(self.last_raid["report_id"]) if self.last_raid else None

    @cached_property
    def rosters(self) -> list[list[dict[str, Any]]]:
        """Rosters of the last ``ATTENDANCE_WINDOW`` raids, newest first."""
        return [self.repo.get_raid_roster(r["report_id"]) for r in self.raids[:ATTENDANCE_WINDOW]]


def _raid_link(report_id: str) -> Link:
    return Link(RAID, {"report_id": report_id})


def _character_link(name: str) -> Link:
    return Link(CHARACTER, {"name": name})


class HomeService:
    """Builds home pages from storage and keeps the user's layout."""

    def __init__(
        self,
        storage: StorageFactory,
        layouts: LayoutStore | None = None,
        *,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.storage = storage
        self.layouts: LayoutStore = layouts if layouts is not None else MemoryLayoutStore()
        self.now = now
        self._builders: dict[str, Callable[[_Snapshot, HomeWidget], None]] = {
            "quick_actions": self._quick_actions,
            "guild_snapshot": self._guild_snapshot,
            "last_raid": self._last_raid,
            "recent_raids": self._recent_raids,
            "raid_activity": self._raid_activity,
            "top_damage": self._top_damage,
            "top_healing": self._top_healing,
            "attendance": self._attendance,
            "boss_kills": self._boss_kills,
            "class_mix": self._class_mix,
            "interrupts": self._interrupts,
            "consumables": self._consumables,
            "tracked_players": self._tracked_players,
        }

    @classmethod
    def from_context(cls, ctx: AppContext, layouts: LayoutStore | None = None) -> HomeService:
        """Home pages over the context's storage (the desktop database, or the host's own)."""
        return cls(ctx.repository, layouts)

    # ── Layout ──

    @staticmethod
    def catalogue() -> list[WidgetSpec]:
        return list(CATALOGUE)

    def layout(self) -> HomeLayout:
        """The saved layout, else the default."""
        saved = self.layouts.load()
        return saved if saved is not None else HomeLayout.default()

    def save_layout(self, widget_ids: Iterable[str]) -> HomeLayout:
        """Save the widgets to show, in order; unknown ids and repeats are dropped."""
        layout = HomeLayout.of(widget_ids)
        self.layouts.save(layout)
        return layout

    def reset_layout(self) -> HomeLayout:
        self.layouts.save(None)
        return HomeLayout.default()

    # ── Data ──

    def page(self, layout: HomeLayout | None = None) -> HomePage:
        """Every widget of ``layout`` (default: the saved one). A widget that fails carries ``error``."""
        ids = (self.layout() if layout is None else layout).widgets
        generated_at = self.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.storage() as repo:
                snapshot = _Snapshot(repo)
                return HomePage([self._build(i, snapshot) for i in ids], generated_at)
        except (StorageError, OSError) as e:
            widgets = [self._blank(i) for i in ids]
            for w in widgets:
                w.error = f"Storage unavailable: {e}"
            return HomePage(widgets, generated_at)

    def widget(self, widget_id: str) -> HomeWidget:
        """One widget on its own, for refreshing it alone. Raises KeyError for an unknown id."""
        return self.page(HomeLayout((_SPECS[widget_id].id,))).widgets[0]

    @staticmethod
    def _blank(widget_id: str) -> HomeWidget:
        spec = _SPECS[widget_id]
        return HomeWidget(id=spec.id, title=spec.title, kind=spec.kind, size=spec.size)

    def _build(self, widget_id: str, snapshot: _Snapshot) -> HomeWidget:
        widget = self._blank(widget_id)
        try:
            self._builders[widget_id](snapshot, widget)
        except StorageError as e:
            widget.error = str(e)
        return widget

    # ── Widgets ──

    def _quick_actions(self, _snapshot: _Snapshot, w: HomeWidget) -> None:
        w.actions = list(QUICK_ACTIONS)

    def _guild_snapshot(self, s: _Snapshot, w: HomeWidget) -> None:
        now = self.now()
        dates = [_parse_date(r.get("raid_date")) for r in s.raids]
        last = dates[0] if dates else None
        active = {p["name"].lower() for roster in s.rosters for p in roster}
        last_30 = sum(1 for d in dates if d is not None and now - d <= timedelta(days=30))
        days_since = (now.date() - last.date()).days if last else None
        w.tiles = [
            Tile("Raids stored", len(s.raids), f"{len(s.raids):,}"),
            Tile("Active raiders", len(active), str(len(active)), f"in the last {ATTENDANCE_WINDOW} raids"),
            Tile("Raids in 30 days", last_30, str(last_30)),
            Tile("Last raid", last.strftime("%Y-%m-%d") if last else None, f"{last:%b} {last.day}" if last else "-"),
            Tile("Days since last raid", days_since, "-" if days_since is None else str(days_since)),
        ]

    def _last_raid(self, s: _Snapshot, w: HomeWidget) -> None:
        a = s.last_analysis
        if s.last_raid is None or a is None:
            w.empty = "No raids stored yet. Import a report to get started."
            return
        raid = s.last_raid
        w.subtitle = raid.get("title") or a.metadata.title
        w.link = _raid_link(a.metadata.report_id)
        duration = (a.metadata.end_time - a.metadata.start_time) if a.metadata.end_time else 0
        damage = sum(d.total_damage for d in a.dps)
        healing = sum(h.total_healing for h in a.healers)
        size = len(a.composition.all_players)
        date = _parse_date(raid.get("raid_date"))
        w.tiles = [
            Tile("Date", raid.get("raid_date"), _day(date, raid.get("raid_date"))),
            Tile("Duration", duration, _duration(duration) if duration else "-"),
            Tile("Bosses killed", len(a.encounters), str(len(a.encounters))),
            Tile("Raid size", size, str(size)),
            Tile("Total damage", damage, compact(damage)),
            Tile("Total healing", healing, compact(healing)),
        ]

    def _recent_raids(self, s: _Snapshot, w: HomeWidget) -> None:
        if not s.raids:
            w.empty = "No raids stored yet."
            return
        for raid in s.raids[:RECENT_RAIDS]:
            date = _parse_date(raid.get("raid_date"))
            w.items.append(
                ListItem(
                    raid.get("title") or raid["report_id"],
                    _day(date, raid.get("raid_date")),
                    _raid_link(raid["report_id"]),
                )
            )

    def _raid_activity(self, s: _Snapshot, w: HomeWidget) -> None:
        today = self.now().date()
        this_week = today - timedelta(days=today.weekday())
        weeks = [this_week - timedelta(weeks=n) for n in range(ACTIVITY_WEEKS - 1, -1, -1)]
        counts: Counter = Counter()
        for raid in s.raids:
            d = _parse_date(raid.get("raid_date"))
            if d is not None:
                counts[d.date() - timedelta(days=d.weekday())] += 1
        w.bars = [Bar(f"{week.day} {week:%b}", counts[week], str(counts[week])) for week in weeks]
        if not any(counts[week] for week in weeks):
            w.empty = f"No raids in the last {ACTIVITY_WEEKS} weeks."

    def _top_damage(self, s: _Snapshot, w: HomeWidget) -> None:
        a = s.last_analysis
        players = sorted(a.dps, key=lambda d: d.total_damage, reverse=True)[:TOP_N] if a else []
        if not players:
            w.empty = "No damage recorded in the last raid."
            return
        total = sum(d.total_damage for d in a.dps) if a else 0
        w.subtitle = s.last_raid["title"] if s.last_raid else ""
        w.columns = [
            Column("rank", "#", "right"),
            Column("name", "Name"),
            Column("class", "Class"),
            Column("damage", "Damage", "right"),
            Column("share", "Share", "right"),
        ]
        for i, d in enumerate(players, 1):
            share = round(d.total_damage / total * 100, 1) if total else 0.0
            w.rows.append(
                Row(
                    {
                        "rank": str(i),
                        "name": d.name,
                        "class": d.player_class,
                        "damage": compact(d.total_damage),
                        "share": f"{share}%",
                    },
                    {"rank": i, "name": d.name, "class": d.player_class, "damage": d.total_damage, "share": share},
                    _character_link(d.name),
                )
            )

    def _top_healing(self, s: _Snapshot, w: HomeWidget) -> None:
        a = s.last_analysis
        players = sorted(a.healers, key=lambda h: h.total_healing, reverse=True)[:TOP_N] if a else []
        if not players:
            w.empty = "No healing recorded in the last raid."
            return
        w.subtitle = s.last_raid["title"] if s.last_raid else ""
        w.columns = [
            Column("rank", "#", "right"),
            Column("name", "Name"),
            Column("class", "Class"),
            Column("healing", "Healing", "right"),
            Column("overheal", "Overheal", "right"),
        ]
        for i, h in enumerate(players, 1):
            w.rows.append(
                Row(
                    {
                        "rank": str(i),
                        "name": h.name,
                        "class": h.player_class,
                        "healing": compact(h.total_healing),
                        "overheal": f"{h.overheal_percent}%",
                    },
                    {
                        "rank": i,
                        "name": h.name,
                        "class": h.player_class,
                        "healing": h.total_healing,
                        "overheal": h.overheal_percent,
                    },
                    _character_link(h.name),
                )
            )

    def _attendance(self, s: _Snapshot, w: HomeWidget) -> None:
        rosters = s.rosters
        if not rosters:
            w.empty = "No raids stored yet."
            return
        seen: Counter = Counter()
        names: dict[str, tuple[str, str]] = {}  # lower-case name -> (name, class) from the newest raid
        for roster in rosters:
            for key in {p["name"].lower() for p in roster}:
                seen[key] += 1
            for p in roster:
                names.setdefault(p["name"].lower(), (p["name"], p.get("player_class") or ""))
        total = len(rosters)
        w.subtitle = f"Last {total} raids"
        w.columns = [
            Column("name", "Name"),
            Column("class", "Class"),
            Column("raids", "Raids", "right"),
            Column("attendance", "Attendance", "right"),
        ]
        for key, count in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))[:10]:
            name, cls = names[key]
            pct = round(count / total * 100)
            w.rows.append(
                Row(
                    {"name": name, "class": cls, "raids": f"{count}/{total}", "attendance": f"{pct}%"},
                    {"name": name, "class": cls, "raids": count, "attendance": pct},
                    _character_link(name),
                )
            )

    def _boss_kills(self, s: _Snapshot, w: HomeWidget) -> None:
        a = s.last_analysis
        if not a or not a.encounters:
            w.empty = "No boss kills recorded in the last raid."
            return
        w.subtitle = s.last_raid["title"] if s.last_raid else ""
        w.link = _raid_link(a.metadata.report_id)
        w.columns = [
            Column("boss", "Boss"),
            Column("duration", "Kill time", "right"),
            Column("players", "Players", "right"),
        ]
        for e in sorted(a.encounters, key=lambda e: e.start_time):
            w.rows.append(
                Row(
                    {"boss": e.name, "duration": _duration(e.duration_ms), "players": str(len(e.players))},
                    {"boss": e.name, "duration": e.duration_ms, "players": len(e.players)},
                )
            )

    def _class_mix(self, s: _Snapshot, w: HomeWidget) -> None:
        a = s.last_analysis
        if not a or not a.composition.all_players:
            w.empty = "No raids stored yet."
            return
        w.subtitle = s.last_raid["title"] if s.last_raid else ""
        classes = Counter(p.player_class or "Unknown" for p in a.composition.all_players)
        w.bars = [Bar(cls, n, str(n)) for cls, n in sorted(classes.items(), key=lambda kv: (-kv[1], kv[0]))]

    def _interrupts(self, s: _Snapshot, w: HomeWidget) -> None:
        a = s.last_analysis
        counts: Counter = Counter()
        classes: dict[str, str] = {}
        for i in a.interrupts if a else []:
            counts[i.player_name] += i.count
            classes[i.player_name] = i.player_class
        if not counts:
            w.empty = "No interrupts recorded in the last raid."
            return
        w.subtitle = s.last_raid["title"] if s.last_raid else ""
        w.columns = [Column("name", "Name"), Column("class", "Class"), Column("interrupts", "Interrupts", "right")]
        for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_N]:
            w.rows.append(
                Row(
                    {"name": name, "class": classes[name], "interrupts": str(n)},
                    {"name": name, "class": classes[name], "interrupts": n},
                    _character_link(name),
                )
            )

    def _consumables(self, s: _Snapshot, w: HomeWidget) -> None:
        a = s.last_analysis
        counts: Counter = Counter()
        roles: dict[str, str] = {}
        for c in a.consumables if a else []:
            counts[c.player_name] += c.count
            roles[c.player_name] = c.player_role
        if not counts:
            w.empty = "No consumables recorded in the last raid."
            return
        w.subtitle = s.last_raid["title"] if s.last_raid else ""
        w.columns = [Column("name", "Name"), Column("role", "Role"), Column("used", "Used", "right")]
        for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_N]:
            role = roles[name].capitalize()
            w.rows.append(
                Row(
                    {"name": name, "role": role, "used": str(n)},
                    {"name": name, "role": roles[name], "used": n},
                    _character_link(name),
                )
            )

    def _tracked_players(self, s: _Snapshot, w: HomeWidget) -> None:
        pages = s.repo.find_player_pages()
        if not pages:
            w.empty = "No player pages yet. Open Player page to follow a character."
            return
        w.columns = [
            Column("name", "Name"),
            Column("server", "Server"),
            Column("region", "Region"),
            Column("logs", "Logs", "right"),
        ]
        for p in pages:
            region = (p.get("region") or "").upper()
            w.rows.append(
                Row(
                    {"name": p["name"], "server": p["server"], "region": region, "logs": str(p.get("log_count", 0))},
                    {"name": p["name"], "server": p["server"], "region": region, "logs": p.get("log_count", 0)},
                    Link(PLAYER_PAGE, {"name": p["name"], "server": p["server"], "region": p.get("region") or ""}),
                )
            )
