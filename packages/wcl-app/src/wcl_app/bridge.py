"""The bridge to the Toads Hub and bot (phase 4 of ``guides/identity_and_profiles.md``).

A member asks the Toads bot for a one-time code in Discord and pastes it into the desktop or the CLI. ``BridgeService``
redeems it with the Hub (``wcl_core.hub``), keeps the app's registration and publishes the app's raid profiles, so
the Hub holds each member's ``ProfileSet``. The bot then resolves a Discord user to a profile with ``member_profile``
over the Hub's store of those sets, and runs the shared services under it with ``AppContext.headless(..., profile=)``.

The code is what proves who the member is: the bot issued it to them. When this app also has a Discord identity
linked, a code issued to someone else links nothing. The wire contract is ``guides/hub_bridge.md``.
"""

from __future__ import annotations

import contextlib
from typing import Any, Protocol

from wcl_core import hub
from wcl_core.common.errors import AuthenticationError
from wcl_core.hub import HubError, HubLink, HubLinkStore

from wcl_app.identity import IdentityService
from wcl_app.profiles import Profile, ProfileService, ProfileSet

__all__ = ["BridgeService", "HubMemberMismatch", "HubNotLinked", "ProfileDirectory", "member_profile"]

APP_NAME = "WarcraftLogs Analyzer"


class HubNotLinked(LookupError):
    """This app has no Toads Hub link yet: redeem a code from the bot first."""


class HubMemberMismatch(AuthenticationError):
    """The code belongs to another Discord user than the one linked to this app."""


class BridgeService:
    def __init__(
        self,
        store: HubLinkStore | None = None,
        config: dict[str, Any] | None = None,
        *,
        identity: IdentityService | None = None,
        profiles: ProfileService | None = None,
        app_version: str = "",
    ):
        self.store = store if store is not None else HubLinkStore()
        self.config = config or {}
        self.identity = identity
        self.profiles = profiles
        self.app_version = app_version

    def current(self) -> HubLink | None:
        return self.store.link

    def is_linked(self) -> bool:
        return self.store.link is not None

    def link(self, code: str) -> HubLink:
        """Redeem the bot's one-time code, keep the registration and publish this app's profiles."""
        link = hub.redeem(hub.hub_url(self.config), code, APP_NAME, self.app_version)
        who = self.identity.current() if self.identity is not None else None
        if who is not None and who.id != link.member.discord_id:
            with contextlib.suppress(HubError, AuthenticationError):
                hub.revoke(link)  # the Hub registered an app nobody will use; drop it if it answers
            raise HubMemberMismatch(
                f"That code was issued to {link.member.name}, but this app is linked to {who.display_name}; "
                "ask the bot for a code from your own Discord account"
            )
        self.store.save(link)
        if self.profiles is not None:
            self.publish()
        return link

    def publish(self, profiles: ProfileSet | None = None) -> None:
        """Replace the member's profiles on the Hub with *profiles*, or with this app's saved ones."""
        link = self.store.link
        if link is None:
            raise HubNotLinked("Link this app with a code from the Toads bot first")
        if profiles is None:
            profiles = self.profiles.profiles() if self.profiles is not None else ProfileSet()
        hub.publish_profiles(link, profiles.to_dict())

    def unlink(self) -> bool:
        """Forget the link here; return whether the Hub confirmed it forgot this app too."""
        link = self.store.link
        if link is None:
            return False
        try:
            hub.revoke(link)
            confirmed = True
        except HubError:
            confirmed = False  # unreachable: forget it here anyway, and the Hub's token goes unused
        self.store.forget()
        return confirmed


class ProfileDirectory(Protocol):
    """Where a host keeps each member's published profiles: the Hub's table, or ``FakeHub`` in tests."""

    def load(self, discord_id: str) -> ProfileSet | dict[str, Any] | None:
        """The member's ``ProfileSet`` (or its ``to_dict()``), or None when they never published one."""
        ...


def member_profile(directory: ProfileDirectory, discord_id: str, slug: str | None = None) -> Profile | None:
    """The profile the bot runs a member's command under: *slug* when given, else their active one.

    None when the member has no published profiles, no such slug or no active profile; the bot then uses the
    plain, unfiltered services.
    """
    data = directory.load(discord_id)
    if data is None:
        return None
    profiles = data if isinstance(data, ProfileSet) else ProfileSet.from_dict(data)
    return profiles.get(slug) if slug else profiles.active_profile
