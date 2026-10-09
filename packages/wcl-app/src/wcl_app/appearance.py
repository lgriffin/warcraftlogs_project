"""Appearance: each user's theme, light or dark and optionally styled after a vanilla WoW class.

Like mains and alts (``wcl_app.my_characters``), the choice is kept per Discord identity, or for this app (``LOCAL``)
while nobody is signed in. The class theme defaults to following the user's main: whatever class the main was seen
playing in stored raids. Picking a class, or "none" for the plain theme, overrides that.

The desktop keeps the choices in ``appearance.json``; the Toads Hub can keep them per member in its own database.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from wcl_store import StorageError

from wcl_app.my_characters import LOCAL, MyCharactersService
from wcl_app.themes import MODES, Mode, Palette, build_palette, class_for

if TYPE_CHECKING:
    from wcl_app.context import AppContext

APPEARANCE_SCHEMA_VERSION = 1
FOLLOW_MAIN = "main"  # class theme: whatever class the user's main plays
NO_CLASS = "none"  # class theme: the plain palette

__all__ = [
    "FOLLOW_MAIN",
    "NO_CLASS",
    "Appearance",
    "AppearanceService",
    "JsonAppearanceStore",
    "MemoryAppearanceStore",
    "Theme",
]


@dataclass(frozen=True)
class Appearance:
    """What the user picked: ``mode`` is dark or light; ``class_theme`` a vanilla class, FOLLOW_MAIN or NO_CLASS."""

    mode: Mode = "dark"
    class_theme: str = FOLLOW_MAIN

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"Unknown theme mode '{self.mode}'")
        if self.class_theme not in (FOLLOW_MAIN, NO_CLASS) and class_for(self.class_theme) != self.class_theme:
            raise ValueError(f"'{self.class_theme}' is not a vanilla class")

    def to_dict(self) -> dict[str, str]:
        return {"mode": self.mode, "class_theme": self.class_theme}

    @classmethod
    def from_dict(cls, data: Any) -> Appearance:
        """The saved choice; anything unreadable falls back to the default for that field."""
        data = data if isinstance(data, dict) else {}
        mode: Mode = data["mode"] if data.get("mode") in MODES else "dark"
        raw = data.get("class_theme")
        class_theme = raw if raw in (FOLLOW_MAIN, NO_CLASS) else (class_for(raw) or FOLLOW_MAIN)
        return cls(mode=mode, class_theme=class_theme)


@dataclass(frozen=True)
class Theme:
    """The theme to draw: the user's choice, the class it resolved to, and its palette."""

    appearance: Appearance
    wow_class: str | None
    main_class: str | None  # the main's class when known, whether or not the theme follows it
    palette: Palette

    @property
    def follows_main(self) -> bool:
        return self.appearance.class_theme == FOLLOW_MAIN

    @property
    def label(self) -> str:
        mode = self.appearance.mode.capitalize()
        if self.wow_class is None:
            return f"Classic {mode.lower()}"
        return f"{self.wow_class} {mode.lower()}" + (" (your main)" if self.follows_main else "")


class AppearanceStore(Protocol):
    def load(self, owner: str) -> Appearance | None:
        """The owner's saved appearance, or None when they have saved nothing."""
        ...

    def save(self, owner: str, appearance: Appearance) -> None: ...


class MemoryAppearanceStore:
    def __init__(self, saved: dict[str, Appearance] | None = None):
        self.saved = dict(saved or {})

    def load(self, owner: str) -> Appearance | None:
        return self.saved.get(owner)

    def save(self, owner: str, appearance: Appearance) -> None:
        self.saved[owner] = appearance


class JsonAppearanceStore:
    """Keeps every owner's appearance in one JSON file. A missing or unreadable file means nothing is saved."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        owners = data.get("owners") if isinstance(data, dict) else None
        return owners if isinstance(owners, dict) else {}

    def load(self, owner: str) -> Appearance | None:
        data = self._read().get(owner)
        return Appearance.from_dict(data) if isinstance(data, dict) else None

    def save(self, owner: str, appearance: Appearance) -> None:
        owners = self._read()
        owners[owner] = appearance.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": APPEARANCE_SCHEMA_VERSION, "owners": owners}
        partial = self.path.with_name(self.path.name + ".tmp")
        partial.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        partial.replace(self.path)


def main_class_from(ctx: AppContext, my_characters: MyCharactersService) -> str | None:
    """The vanilla class the user's main was seen playing in stored raids, or None when unknown."""
    main = my_characters.current().main
    if main is None:
        return None
    try:
        with ctx.repository() as db:
            history = db.get_character_history(main.name)
    except (StorageError, OSError):
        return None
    return class_for(history.player_class) if history else None


class AppearanceService:
    """Read and change one user's theme; ``owner`` is their Discord id, None when signed out."""

    def __init__(
        self,
        store: AppearanceStore,
        owner: str | None = None,
        *,
        main_class: Callable[[], str | None] | None = None,
    ):
        self.store = store
        self.owner = owner or LOCAL
        self._main_class = main_class

    @classmethod
    def desktop(cls, ctx: AppContext) -> AppearanceService:
        """The desktop's saved appearance for whoever is signed in with Discord, following their main's class."""
        from wcl_core import paths
        from wcl_core.discord_auth import DiscordIdentityStore

        identity = DiscordIdentityStore().identity
        my_characters = MyCharactersService.desktop(ctx.config)
        return cls(
            JsonAppearanceStore(paths.get_appearance_path()),
            identity.id if identity else None,
            main_class=lambda: main_class_from(ctx, my_characters),
        )

    def current(self) -> Appearance:
        saved = self.store.load(self.owner)
        return saved if saved is not None else Appearance()

    def save(self, appearance: Appearance) -> Theme:
        self.store.save(self.owner, appearance)
        return self.theme(appearance)

    def main_class(self) -> str | None:
        return class_for(self._main_class()) if self._main_class else None

    def theme(self, appearance: Appearance | None = None) -> Theme:
        """The theme for ``appearance`` (the saved one by default), with a followed main's class resolved."""
        appearance = appearance or self.current()
        main_class = self.main_class()
        if appearance.class_theme == FOLLOW_MAIN:
            wow_class = main_class
        elif appearance.class_theme == NO_CLASS:
            wow_class = None
        else:
            wow_class = appearance.class_theme
        return Theme(appearance, wow_class, main_class, build_palette(appearance.mode, wow_class))
