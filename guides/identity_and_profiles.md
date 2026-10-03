# Discord identity and raid profiles

Status: **experimental** (branch `claude/experimental-discord-identity-fs3zou`). This guide is the plan; the
sections marked *built* describe what the branch already carries, the rest is the roadmap.

## Why

The analyzer takes any Warcraft Logs report and stores it. One guild anchored on top of it has lived through
Classic and then The Burning Crusade on the Anniversary ("fresh") realms, and may run Classic Era ("forever") or
Season of Discovery characters too. Everything lands in one database with no way to say "show me TBC" or
"show me the Classic days", and every frontend treats the whole database as the guild.

The second gap is identity. The desktop app has a Warcraft Logs sign-in but no notion of *whose* app it is. The
Toads Hub signs members in with Discord, and the Toads bot talks to the Hub over `/api/bots`. For the analyzer to
take part (a member's own app pushing to the bot, the bot asking a member's app for a report) the app needs to
know which Discord user it belongs to, and the shared services need to carry that identity without the frontends
each inventing their own.

Both are structural: they touch the storage contract, `AppContext` and every service, so they come first as a
model and a thin vertical slice, then each frontend adapts.

## Vocabulary

| Term | Meaning | Where it lives |
| --- | --- | --- |
| **Game version** | Which Warcraft Logs site a report is on: `fresh` (Anniversary realms, Classic through TBC), `classic` (Classic Era and Hardcore, "forever"), `sod`, `retail`. Derived from the API host the report was fetched through. | `wcl_core.game_version`, stored on `raids.game_version` |
| **Expansion** | The content era of the report's zone: `Classic`, `The Burning Crusade`, `Wrath of the Lich King`, ... Read from the API's `zone { expansion { name } }`, or from the zone name for raids stored before this change. | `wcl_core.game_version`, stored on `raids.expansion` |
| **Scope** | The filter the services hand the repository: sources, game versions, expansions, zones, a date window. Empty means everything, which is today's behaviour. | `wcl_store.RaidScope` |
| **Profile** | A named, user-facing view that produces a scope and picks the Warcraft Logs host and guild to import from: "TBC", "Classic days", "Era forever". No active profile means the plain, unfiltered app. | `wcl_app.profiles` |
| **Identity** | The Discord user this app instance belongs to: id, username, display name, avatar. Linked once with Discord OAuth (PKCE), then stamped on the profiles the user creates. | `wcl_core.discord_auth`, `wcl_app.identity` |

Game version and expansion are two axes on purpose. The Anniversary guild's Classic and TBC raids share a host
(`fresh`) and differ by expansion; Era and Anniversary Classic raids share an expansion and differ by host.

## Layering (per `tests/test_architecture.py`)

```
core         wcl_core.game_version   host -> game version, zone -> expansion, catalogue of known zones
             wcl_core.discord_auth   Discord OAuth 2 with PKCE for a public client, loopback redirect, /users/@me
             wcl_core.models         RaidMetadata.game_version, RaidMetadata.expansion
             wcl_core.client         reports carry zone { name expansion { name } }; the client knows its host
persistence  wcl_store.RaidScope     the filter type; both backends apply it
             raids.game_version, raids.expansion (SQLite migrate + Alembic 0002)
             RaidRepository: scope= on the list/count/attendance/healing reads, set_raid_era, get_raids_without_era
services     wcl_app.profiles        Profile, ProfileStore (JSON on the desktop, the host's own store elsewhere),
                                     ProfileService (list, create, activate, scope, backfill eras)
             wcl_app.identity        IdentityService (current, link, unlink)
             wcl_app.context         AppContext.profile and AppContext.scope; the WCL client follows the profile's host
frontends    CLI: `warcraftlogs profile ...`, `warcraftlogs discord ...`; desktop and Toads follow
```

Rules kept: no `discord` package anywhere (Discord is plain HTTPS with `requests`, exactly like the Warcraft Logs
sign-in); RBAC stays in the frontends (identity says *who*, never *what they may do*); services read storage only
through `AppContext.repository()`; no new `KNOWN_VIOLATIONS`.

## Data model

### Raids (*built*)

Two nullable text columns on `raids`: `game_version` and `expansion`. `import_raid` writes both from
`RaidMetadata`; a re-import never blanks a value that is already stored. Existing rows are backfilled by
`ProfileService.backfill_eras()` from the zone name through the catalogue in `wcl_core.game_version` (Molten Core
is Classic, Karazhan is The Burning Crusade, and so on); the game version of a backfilled raid is the host the app
is configured for, since that is where it was fetched from. Anything the catalogue does not know stays `NULL` and
is shown by every profile, so an unknown zone never disappears.

Postgres gets the same columns in Alembic revision `0002_raid_era`.

### Scope (*built*)

```python
@dataclass(frozen=True)
class RaidScope:
    sources: tuple[str, ...] = ("guild",)
    game_versions: tuple[str, ...] = ()   # () = any
    expansions: tuple[str, ...] = ()      # () = any
    zones: tuple[str, ...] = ()           # () = any, matched ignoring ASCII case
    since: str | None = None              # "YYYY-MM-DD HH:MM:SS" on raid_date, inclusive
    until: str | None = None              # exclusive
```

Raids whose `game_version` or `expansion` is `NULL` match every scope on that axis. Each repository read that
lists or aggregates raids takes `scope: RaidScope | None = None`; `None` keeps the method's old behaviour so
nothing that exists changes until it opts in.

### Profiles (*built*)

```python
@dataclass(frozen=True)
class Profile:
    slug: str                 # "tbc", "classic-days"; the stable id
    name: str                 # what the user sees
    game_version: str | None  # fresh | classic | sod | retail; None = the configured host
    expansions: tuple[str, ...] = ()
    zones: tuple[str, ...] = ()
    since: str | None = None
    until: str | None = None
    guild_id: int | None = None       # the guild to import from; None = config
    wcl_api_url: str | None = None    # the host to import from; None = config, or derived from game_version
    owner: str | None = None          # Discord user id that created it
```

`ProfileStore` is a protocol (`load() -> ProfileSet`, `save(ProfileSet)`); `JsonProfileStore` keeps it in
`profiles.json` next to the home layout on the desktop, and the Toads Hub keeps one per member in its own database,
the same split as `HomeLayout`. `ProfileSet` is the list plus the active slug.

A profile is a view, not a partition: the database stays one store and a raid can appear under several profiles.
That is what keeps "normal usage" intact: with no active profile every service behaves exactly as today.

### Identity (*built*)

`DiscordIdentity(id, username, global_name, avatar)` plus the OAuth tokens, kept in `discord_identity.json`
under the user data directory (same place and same `SecretStr` handling as the Warcraft Logs user token). The
Discord application id comes from `discord_client_id` in `config.json` or `DISCORD_CLIENT_ID`; the flow is
Authorization Code with PKCE for a public client, so the desktop never holds a client secret. The scope is only
`identify`. `DISCORD_OAUTH_URL` can point the flow at the Toads fake Discord (`FAKE_DISCORD_I_AM_DEV=1`) for
development, so the desktop and the Hub share one dev login.

Identity never grants anything. It answers "whose app is this" so the bot bridge can trust a later request, and
so profiles and (later) role overrides and layouts can be attributed. Permission checks belong to the host:
Toads' `require()` for the Hub, nothing for a single-user desktop.

## Services

- `AppContext.profile` is the active profile (or `None`); `AppContext.scope` is its `RaidScope`. `wcl_client`
  builds the Warcraft Logs client for the profile's host when it names one, so a "TBC on Anniversary" and an
  "Era" profile import from the right site. `AppContext.headless(...)` takes `profile=` for the Hub.
- `ProfileService`: `list()`, `active()`, `create(...)`, `delete(slug)`, `activate(slug | None)`, `scope()`,
  `backfill_eras()`. A profile created while an identity is linked gets `owner` stamped.
- `IdentityService`: `current()`, `link(open_browser=...)`, `unlink()`.
- `RaidService.list_raids()` and `count` honour the context scope (*built*); `HomeService`, `PlayerService`,
  `BadgeService`, `ReferenceService` follow in the next step, each by passing `ctx.scope` to the repository
  reads they already make.

## Beyond the desktop

`wcl_app` is the core API. There is no separate "API package" to build: a host wires `AppContext.headless(client,
storage, profile=...)` with the signed-in member's profile and calls the same services the CLI calls.

- **Toads Hub** already has Discord OAuth and sessions. It maps its session's Discord id to the profile owner and
  stores `ProfileSet` per member. Nothing in the analyzer needs the Hub's session code.
- **Toads bot**: `/api/bots` is the bridge. The desktop app, once linked, can register with the Hub as "Leigh's
  app" (a later phase: `POST /api/bots/apps` with the Discord identity, the Hub verifies the id against its own
  member list). Until then the identity is local only.
- **Headless CLI/bot use**: `warcraftlogs --profile tbc ...` picks a profile for one run; a bot command maps a
  Discord user to the profile they own.

## Roadmap

1. **Foundation (this branch)**: vocabulary, columns and migration, `RaidScope`, profiles with the JSON store,
   Discord identity, `AppContext` wiring, CLI commands, contract tests. Draft PR, marked experimental.
2. **Scoped services**: Home, players, badges, healing and reference reads pass the scope. Desktop gets a profile
   switcher in the toolbar and Discord sign-in in Settings; the Hub gets per-member profiles.
3. **Import by profile**: the download view and `import_missing` fetch the guild list from the profile's host and
   guild; the era is tagged at import so backfill becomes a one-off.
4. **Bridge**: register a linked app with the Toads Hub; bot commands resolve a Discord user to their profile.
5. **Retire the single-host config**: once every frontend goes through profiles, `wcl_api_url` and `guild_id` in
   `config.json` become the defaults of the implicit "All" profile.

## Open questions for Leigh

- Discord application: reuse the Toads Hub's Discord app (add a loopback redirect, enable the public client) or
  register a second one for the desktop? The code only needs an id either way.
- Should "forever" (Classic Era) be a game version or just a profile name? The code models it as the `classic`
  host, which also covers Hardcore.
- Does the desktop keep one database per profile, or one database with views? This design says one database, so
  a report never has to be imported twice.
