"""My characters: the main character and the alts a user has claimed, so a profile page can jump between them.

Each Discord identity (``wcl_app.identity``) keeps its own main and alts; with nobody signed in they belong to this
app (``LOCAL``). The first time someone signs in, they take over what was set up before signing in, and before
anything was claimed at all the main is the one "My Character" saved in config.json, so nothing set up earlier
disappears when you log in.

Where the claims are kept is up to the host, like profiles: the desktop uses ``JsonMyCharactersStore`` on
``my_characters.json``; the Toads Hub can keep them per member in its own database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from wcl_app.player_page import PlayerRef

MY_CHARACTERS_SCHEMA_VERSION = 1
LOCAL = "local"  # the owner key while nobody is signed in

__all__ = ["LOCAL", "JsonMyCharactersStore", "MemoryMyCharactersStore", "MyCharacters", "MyCharactersService"]


def _ref_to_dict(ref: PlayerRef) -> dict[str, str]:
    return {"name": ref.name, "server": ref.server, "region": ref.region}


def _ref_from_dict(data: Any) -> PlayerRef | None:
    if not isinstance(data, dict):
        return None
    try:
        return PlayerRef.create(
            str(data.get("name") or ""), str(data.get("server") or ""), str(data.get("region") or "")
        )
    except ValueError:
        return None


@dataclass(frozen=True)
class MyCharacters:
    """One user's main and claimed alts; ``favourites`` lists the main first."""

    main: PlayerRef | None = None
    alts: tuple[PlayerRef, ...] = ()

    @property
    def favourites(self) -> tuple[PlayerRef, ...]:
        return ((self.main,) if self.main else ()) + self.alts

    def __contains__(self, ref: object) -> bool:
        return ref in self.favourites

    def to_dict(self) -> dict[str, Any]:
        return {"main": _ref_to_dict(self.main) if self.main else None, "alts": [_ref_to_dict(a) for a in self.alts]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MyCharacters:
        main = _ref_from_dict(data.get("main"))
        alts: list[PlayerRef] = []
        for raw in data.get("alts") or ():
            ref = _ref_from_dict(raw)
            if ref is not None and ref != main and ref not in alts:
                alts.append(ref)
        return cls(main=main, alts=tuple(alts))


class MyCharactersStore(Protocol):
    def load(self, owner: str) -> MyCharacters | None:
        """The owner's saved characters, or None when they have saved nothing."""
        ...

    def save(self, owner: str, characters: MyCharacters) -> None: ...


class MemoryMyCharactersStore:
    def __init__(self, saved: dict[str, MyCharacters] | None = None):
        self.saved = dict(saved or {})

    def load(self, owner: str) -> MyCharacters | None:
        return self.saved.get(owner)

    def save(self, owner: str, characters: MyCharacters) -> None:
        self.saved[owner] = characters


class JsonMyCharactersStore:
    """Keeps every owner's characters in one JSON file. A missing or unreadable file means nothing is saved."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        owners = data.get("owners") if isinstance(data, dict) else None
        return owners if isinstance(owners, dict) else {}

    def load(self, owner: str) -> MyCharacters | None:
        data = self._read().get(owner)
        return MyCharacters.from_dict(data) if isinstance(data, dict) else None

    def save(self, owner: str, characters: MyCharacters) -> None:
        owners = self._read()
        owners[owner] = characters.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": MY_CHARACTERS_SCHEMA_VERSION, "owners": owners}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def legacy_main(config: dict[str, Any] | None) -> PlayerRef | None:
    """The character "My Character" saved in config.json before mains and alts existed, if it is complete."""
    config = config or {}
    return _ref_from_dict(
        {
            "name": config.get("character_name"),
            "server": config.get("character_server"),
            "region": config.get("character_region") or "eu",
        }
    )


class MyCharactersService:
    """Read and change the signed-in user's main and alts; ``owner`` is their Discord id, None when signed out."""

    def __init__(
        self,
        store: MyCharactersStore,
        owner: str | None = None,
        config: dict[str, Any] | None = None,
        *,
        owner_name: str | None = None,
    ):
        self.store = store
        self.owner = owner or LOCAL
        self.owner_name = owner_name if owner else None  # who to say is signed in; None while signed out
        self.config = config or {}

    @classmethod
    def desktop(cls, config: dict[str, Any] | None = None) -> MyCharactersService:
        """The desktop's saved characters, for whoever is signed in with Discord right now."""
        from wcl_core import paths
        from wcl_core.discord_auth import DiscordIdentityStore

        identity = DiscordIdentityStore().identity
        store = JsonMyCharactersStore(paths.get_my_characters_path())
        if identity is None:
            return cls(store, None, config)
        return cls(store, identity.id, config, owner_name=identity.display_name)

    def current(self) -> MyCharacters:
        """The owner's characters; one who saved nothing takes over the signed-out ones, then config.json's."""
        saved = self.store.load(self.owner)
        if saved is None and self.owner != LOCAL:
            saved = self.store.load(LOCAL)
        if saved is None:
            main = legacy_main(self.config)
            saved = MyCharacters(main=main)
        return saved

    def _save(self, characters: MyCharacters) -> MyCharacters:
        self.store.save(self.owner, characters)
        return characters

    def set_main(self, ref: PlayerRef) -> MyCharacters:
        """Make ``ref`` the main; the old main stays claimed as an alt."""
        mine = self.current()
        if mine.main == ref:
            return mine
        alts = [a for a in mine.alts if a != ref]
        if mine.main is not None:
            alts.insert(0, mine.main)
        return self._save(MyCharacters(main=ref, alts=tuple(alts)))

    def claim(self, ref: PlayerRef) -> MyCharacters:
        """Claim ``ref`` as an alt, or as the main when there is none yet. Claiming one already claimed is a no-op."""
        mine = self.current()
        if ref in mine:
            return mine
        if mine.main is None:
            return self._save(MyCharacters(main=ref, alts=mine.alts))
        return self._save(MyCharacters(main=mine.main, alts=(*mine.alts, ref)))

    def release(self, ref: PlayerRef) -> MyCharacters:
        """Stop claiming ``ref``; releasing the main promotes the first alt."""
        mine = self.current()
        if ref not in mine:
            return mine
        alts = [a for a in mine.alts if a != ref]
        main = mine.main
        if main == ref:
            main = alts.pop(0) if alts else None
        return self._save(MyCharacters(main=main, alts=tuple(alts)))
