"""Raid profiles: the named, high-level views over one database ("TBC", "Classic days", "Era forever").

A profile picks which stored raids a frontend sees (as a ``wcl_store.RaidScope``) and which Warcraft Logs site
and guild new imports come from. It is a view, not a partition: the database stays one store, a raid can
appear under several profiles, and with no active profile every service behaves exactly as it always has.

Where profiles are kept is up to the host, like the home layout: the desktop uses ``JsonProfileStore`` on
``profiles.json``, the Toads Hub keeps a ``ProfileSet`` per member in its own database. See
``guides/identity_and_profiles.md``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from wcl_core.config import configured_api_url
from wcl_core.game_version import GAME_VERSIONS, api_url_for, expansion_for_zone, game_version_for_url
from wcl_store import RaidScope, StorageError

from wcl_app.context import AppContext

PROFILES_SCHEMA_VERSION = 1

__all__ = ["GAME_VERSIONS", "JsonProfileStore", "Profile", "ProfileService", "ProfileSet", "ProfileStore", "slugify"]

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError("A profile needs a name")
    return slug


@dataclass(frozen=True)
class Profile:
    slug: str
    name: str
    game_version: str | None = None  # fresh | classic | sod | retail; None = the configured host
    expansions: tuple[str, ...] = ()
    zones: tuple[str, ...] = ()
    since: str | None = None  # "YYYY-MM-DD HH:MM:SS" on raid_date, inclusive
    until: str | None = None  # exclusive
    guild_id: int | None = None  # the guild to import from; None = config
    wcl_api_url: str | None = None  # the host to import from; None = config, or derived from game_version
    owner: str | None = None  # Discord user id that created it (``wcl_app.identity``)

    def __post_init__(self) -> None:
        if self.game_version is not None and self.game_version not in GAME_VERSIONS:
            raise ValueError(f"Unknown game version {self.game_version!r}; one of {', '.join(GAME_VERSIONS)}")

    @property
    def scope(self) -> RaidScope:
        return RaidScope(
            game_versions=(self.game_version,) if self.game_version else (),
            expansions=self.expansions,
            zones=self.zones,
            since=self.since,
            until=self.until,
        )

    @property
    def api_url(self) -> str | None:
        """The client API URL imports should use, or None to keep the configured one (also when the game
        version's site is not announced yet, as for ``forever``)."""
        if self.wcl_api_url:
            return self.wcl_api_url
        return api_url_for(self.game_version) if self.game_version else None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["expansions"] = list(self.expansions)
        data["zones"] = list(self.zones)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        name = str(data.get("name") or data.get("slug") or "")
        guild_id = data.get("guild_id")
        return cls(
            slug=str(data.get("slug") or slugify(name)),
            name=name or str(data.get("slug")),
            game_version=data.get("game_version") or None,
            expansions=tuple(str(e) for e in data.get("expansions") or ()),
            zones=tuple(str(z) for z in data.get("zones") or ()),
            since=data.get("since") or None,
            until=data.get("until") or None,
            guild_id=int(guild_id) if guild_id is not None and guild_id != "" else None,
            wcl_api_url=data.get("wcl_api_url") or None,
            owner=str(data["owner"]) if data.get("owner") else None,
        )


@dataclass
class ProfileSet:
    """Every profile a user has, and which one is active (None = the plain, unfiltered app)."""

    profiles: list[Profile] = field(default_factory=list)
    active: str | None = None

    def get(self, slug: str) -> Profile | None:
        return next((p for p in self.profiles if p.slug == slug), None)

    @property
    def active_profile(self) -> Profile | None:
        return self.get(self.active) if self.active else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": PROFILES_SCHEMA_VERSION,
            "active": self.active,
            "profiles": [p.to_dict() for p in self.profiles],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileSet:
        profiles = [Profile.from_dict(p) for p in data.get("profiles") or () if isinstance(p, dict)]
        active = data.get("active") or None
        if active and not any(p.slug == active for p in profiles):
            active = None
        return cls(profiles=profiles, active=active)


class ProfileStore(Protocol):
    def load(self) -> ProfileSet | None:
        """The saved profiles, or None when nothing is saved."""
        ...

    def save(self, profiles: ProfileSet) -> None: ...


class MemoryProfileStore:
    def __init__(self, profiles: ProfileSet | None = None):
        self.profiles = profiles

    def load(self) -> ProfileSet | None:
        return self.profiles

    def save(self, profiles: ProfileSet) -> None:
        self.profiles = profiles


class JsonProfileStore:
    """Keeps the profiles in a JSON file. A missing or unreadable file means nothing is saved."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> ProfileSet | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        try:
            return ProfileSet.from_dict(data) if isinstance(data, dict) else None
        except ValueError:
            return None

    def save(self, profiles: ProfileSet) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(profiles.to_dict(), indent=2), encoding="utf-8")


def saved_active_profile(path: str | Path | None = None) -> Profile | None:
    """The desktop's saved active profile (from ``get_profiles_path()`` unless ``path`` is given), or None."""
    from wcl_core import paths

    profiles = JsonProfileStore(path if path is not None else paths.get_profiles_path()).load()
    return profiles.active_profile if profiles is not None else None


class ProfileService:
    """List, create, pick and apply profiles; ``owner`` is the linked Discord id the host passes in."""

    def __init__(self, store: ProfileStore, ctx: AppContext | None = None, owner: str | None = None):
        self.store = store
        self.ctx = ctx
        self.owner = owner

    @classmethod
    def from_context(cls, ctx: AppContext, store: ProfileStore, owner: str | None = None) -> ProfileService:
        return cls(store, ctx, owner=owner)

    @classmethod
    def desktop(cls, ctx: AppContext | None = None, owner: str | None = None) -> ProfileService:
        """The desktop's saved profiles, applied to ``ctx`` (a database-only desktop context when None)."""
        from wcl_core import paths

        context = ctx if ctx is not None else AppContext.desktop(with_config=False)
        return cls(JsonProfileStore(paths.get_profiles_path()), context, owner=owner)

    def raid_count(self) -> int | None:
        """Guild raids inside the active profile, or every guild raid with none; None if storage fails.

        Needs a context.
        """
        if self.ctx is None:
            raise ValueError("raid_count needs a context")
        try:
            with self.ctx.repository() as db:
                return db.count_raids("guild", scope=self.ctx.scope)
        except StorageError:
            return None

    def profiles(self) -> ProfileSet:
        return self.store.load() or ProfileSet()

    def list(self) -> list[Profile]:
        return list(self.profiles().profiles)

    def get(self, slug: str) -> Profile | None:
        return self.profiles().get(slug)

    def active(self) -> Profile | None:
        return self.profiles().active_profile

    def create(
        self,
        name: str,
        *,
        game_version: str | None = None,
        expansions: tuple[str, ...] = (),
        zones: tuple[str, ...] = (),
        since: str | None = None,
        until: str | None = None,
        guild_id: int | None = None,
        wcl_api_url: str | None = None,
        activate: bool = False,
    ) -> Profile:
        """Save a new profile; its slug comes from the name and must be unused."""
        profiles = self.profiles()
        slug = slugify(name)
        if profiles.get(slug) is not None:
            raise ValueError(f"A profile named {name!r} already exists")
        profile = Profile(
            slug=slug,
            name=name.strip(),
            game_version=game_version,
            expansions=tuple(expansions),
            zones=tuple(zones),
            since=since,
            until=until,
            guild_id=guild_id,
            wcl_api_url=wcl_api_url,
            owner=self.owner,
        )
        profiles.profiles.append(profile)
        if activate:
            profiles.active = slug
        self.store.save(profiles)
        self._apply(profiles)
        return profile

    def update(self, slug: str, **changes: Any) -> Profile:
        profiles = self.profiles()
        current = profiles.get(slug)
        if current is None:
            raise KeyError(slug)
        updated = replace(current, **changes)
        profiles.profiles = [updated if p.slug == slug else p for p in profiles.profiles]
        self.store.save(profiles)
        self._apply(profiles)
        return updated

    def delete(self, slug: str) -> bool:
        profiles = self.profiles()
        before = len(profiles.profiles)
        profiles.profiles = [p for p in profiles.profiles if p.slug != slug]
        if profiles.active == slug:
            profiles.active = None
        if len(profiles.profiles) == before:
            return False
        self.store.save(profiles)
        self._apply(profiles)
        return True

    def activate(self, slug: str | None) -> Profile | None:
        """Make ``slug`` the active profile, or None for the plain, unfiltered app."""
        profiles = self.profiles()
        if slug is not None and profiles.get(slug) is None:
            raise KeyError(slug)
        profiles.active = slug
        self.store.save(profiles)
        self._apply(profiles)
        return profiles.active_profile

    def scope(self) -> RaidScope | None:
        """The active profile's scope, or None for everything."""
        active = self.active()
        return active.scope if active else None

    def apply(self) -> Profile | None:
        """Put the saved active profile on the context; the desktop calls this at start-up."""
        profiles = self.profiles()
        self._apply(profiles)
        return profiles.active_profile

    def _apply(self, profiles: ProfileSet) -> None:
        if self.ctx is not None:
            self.ctx.use_profile(profiles.active_profile)

    def backfill_eras(self) -> int:
        """Fill ``game_version`` and ``expansion`` on raids stored before they were read; returns how many changed.

        The game version is the configured host's, since that is where those raids were fetched from. An
        expansion the zone catalogue does not know stays unknown, and the raid stays visible in every profile.
        """
        if self.ctx is None:
            raise RuntimeError("backfill_eras needs a context")
        default_version = game_version_for_url(configured_api_url(self.ctx.config))
        changed = 0
        with self.ctx.repository() as repo:
            for row in repo.get_raids_without_era():
                version = row.get("game_version") or default_version
                expansion = row.get("expansion") or expansion_for_zone(row.get("zone"))
                if version != row.get("game_version") or expansion != row.get("expansion"):
                    repo.set_raid_era(row["report_id"], version, expansion)
                    changed += 1
        return changed
