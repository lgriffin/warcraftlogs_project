# Discord identity and raid profiles

Plan revision 4, 2026-10-03. Phases 1, 2.1 to 2.3 and Q merged (PRs #144 to #158); phase 3 in review.
Status: **experimental**. Order of precedence, as in ESI.ts: running code and CI are the fact, the requirements
below are the intent, this guide is the how, the phase map is the order.

## Decisions

- Decided 2026-10-03: **Forever is its own game version** (`forever`). It launches in November 2026; Warcraft Logs
  has not announced its site, so `wcl_core.game_version.HOSTS` has no entry for it yet and a Forever profile keeps
  the configured host for imports until one is added. Classic Era and Hardcore stay `classic`.
- Decided 2026-10-03: **Reuse the Toads Hub's Discord application.** The desktop is a public client with PKCE on a
  loopback redirect; the Hub owner adds `http://127.0.0.1:8765/callback` as a redirect and enables the public client.
  The code needs only the application id (`discord_client_id` or `DISCORD_CLIENT_ID`).
- Decided 2026-10-03: **Python first, port to Toads later.** Every phase lands in this repo; the Hub takes the
  packages by pinning a commit, as it does today. Nothing here needs the Hub's session code.
- Decided 2026-10-03: **The ESI.ts standard is the bar**: world-class testing, architecture and scalability, in
  Python. The quality section below says what that means here and what is still missing.
- Decided 2026-10-03: one database with views, never one database per profile, so a report is imported once.

## Why

The analyzer takes any Warcraft Logs report and stores it. One guild anchored on top of it has lived through
Classic and then The Burning Crusade on the Anniversary ("fresh") realms, and may run Classic Era, Season of
Discovery or Forever characters too. Everything lands in one database with no way to say "show me TBC" or "show me
the Classic days", and every frontend treats the whole database as the guild.

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
| **Game version** | Which Warcraft Logs site a report is on: `fresh` (Anniversary realms, Classic through TBC), `classic` (Classic Era and Hardcore), `sod`, `forever` (November 2026, site not announced), `retail`. Derived from the API host the report was fetched through. | `wcl_core.game_version`, stored on `raids.game_version` |
| **Expansion** | The content era of the report's zone: `Classic`, `The Burning Crusade`, `Wrath of the Lich King`, ... Read from the API's `zone { expansion { name } }`, or from the zone name for raids stored before this change. | `wcl_core.game_version`, stored on `raids.expansion` |
| **Scope** | The filter the services hand the repository: sources, game versions, expansions, zones, a date window. Empty means everything, which is today's behaviour. | `wcl_store.RaidScope` |
| **Profile** | A named, user-facing view that produces a scope and picks the Warcraft Logs host and guild to import from: "TBC", "Classic days", "Forever". No active profile means the plain, unfiltered app. | `wcl_app.profiles` |
| **Identity** | The Discord user this app instance belongs to: id, username, display name, avatar. Linked once with Discord OAuth (PKCE), then stamped on the profiles the user creates. | `wcl_core.discord_auth`, `wcl_app.identity` |

Game version and expansion are two axes on purpose. The Anniversary guild's Classic and TBC raids share a host
(`fresh`) and differ by expansion; Era and Anniversary Classic raids share an expansion and differ by host.

## Requirements

EARS form, one `shall` each, in the style of the ESI.ts charter. Status is **Enforced** (a named check proves it),
**Practised** (done, not yet gated) or **Gap**.

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| PROF-01 | When a raid is imported, the store shall record its game version and expansion without blanking a stored value with an unknown one. | Enforced | `tests/test_store_contract.py::test_import_stores_the_era_and_keeps_it_when_stored_again` |
| PROF-02 | When a read takes a `RaidScope`, the store shall return only raids inside it, counting a raid whose era is unknown as inside every scope on that axis. | Enforced | `test_scope_filters_raids_by_era_and_unknown_eras_match_every_scope`, both backends |
| PROF-03 | When no profile is active, every service shall behave exactly as before profiles existed. | Enforced | `scope=None` keeps each method's historic path; `test_count_raids_counts_each_source` and the rest of the contract run unchanged |
| PROF-04 | When a profile names a game version whose site is known, the context shall import from that site; any other profile keeps the configured host. | Enforced | `tests/test_profiles.py::test_switching_profiles_rebuilds_the_client_for_the_host`, `test_api_url_follows_the_game_version_unless_given` |
| PROF-05 | When a profile is created while an identity is linked, the profile shall carry that Discord id as its owner. | Enforced | `test_create_activate_and_delete` |
| PROF-06 | When raids stored before this change are backfilled, the service shall tag each from its zone and the configured host, leaving an unknown zone's expansion unset. | Enforced | `test_backfill_tags_stored_raids_from_the_zone_and_the_configured_host` |
| PROF-07 | Each raid-reading service shall use the active scope at read time. | Enforced | see below |
| IDENT-01 | The desktop sign-in shall use Authorization Code with PKCE and the `identify` scope only, holding no client secret. | Enforced | `tests/test_discord_auth.py::TestPkce`, `test_complete_auth_exchanges_the_code_with_the_verifier_and_reads_who` |
| IDENT-02 | If the callback's state differs from the one issued, or carries an error, then the service shall link nothing. | Enforced | `test_link_refuses_a_bad_callback` |
| IDENT-03 | Identity shall never decide what a user may do; permission checks stay in the frontends. | Practised | `wcl_app.identity` exposes who only; `tests/test_architecture.py` keeps `discord` out of every layer |
| IDENT-04 | When `DISCORD_OAUTH_URL` is set, the flow shall use that site, so the Toads fake Discord serves development. | Enforced | `test_oauth_url_can_point_at_the_fake_discord` |
| IDENT-05 | When a member redeems a one-time code from the Toads bot, the app shall register with the Toads Hub as theirs and publish its profiles. | Enforced | `tests/test_hub_bridge.py::TestLink`, against `FakeHub` |
| IDENT-06 | When the bot sees a Discord user, the bridge shall resolve them to their named or active profile. | Enforced | `tests/test_hub_bridge.py::TestTheBotResolvesAMember` |
| IDENT-07 | If a code was issued to another Discord user than the one linked to the app, then the app shall link nothing. | Enforced | `test_a_code_issued_to_someone_else_links_nothing` |
| ARCH-P1 | The layering shall hold: core has no Qt, SQLite or Discord library; services read storage only through `AppContext.repository()`; frontends call services. | Enforced | `tests/test_architecture.py`, `lint-imports`; `KNOWN_VIOLATIONS` only shrinks |
| PROF-08 | The desktop and CLI shall start in the saved active profile. | Enforced | see below |
| PROF-09 | The desktop shall show and switch the active profile and its raid count. | Enforced | see below |
| PROF-10 | While a profile is active, the guild list shall show only its guild and era. | Enforced | see below |
| PROF-11 | When a profile imports a raid, the profile shall list it without a backfill. | Enforced | see below |
| PROF-12 | If a profile's site is not the client's, then the service shall import nothing. | Enforced | see below |
| ARCH-P2 | A new storage operation shall land in the protocol, both backends, a migration and the contract tests together. | Enforced | `test_contract_module_calls_every_protocol_method` (33 methods), `test_migrations_match_the_schema_and_downgrade_cleanly` |

PROF-07 evidence: `tests/test_profile_scoped_services.py`, each test failing without its change, and the scope
contract tests on both backends.
PROF-10 evidence: `tests/test_import_by_profile.py` and
`test_a_scope_admits_exactly_the_raids_the_store_returns_for_it` on both backends. PROF-11 evidence:
`test_a_raid_imported_under_a_profile_is_listed_by_it_without_a_backfill`. PROF-12 evidence:
`test_a_profile_whose_site_is_unknown_refuses_to_import`.
PROF-08 evidence: `test_the_desktop_context_starts_in_the_saved_profile`. PROF-09 evidence:
`tests/gui/test_profile_switcher.py`, `test_the_home_page_follows_a_later_profile_switch` and
`tests/gui/test_characters_hub.py`.

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

### Raids (built)

Two nullable text columns on `raids`: `game_version` and `expansion`. `import_raid` writes both from
`RaidMetadata`; a re-import never blanks a value that is already stored. Existing rows are backfilled by
`ProfileService.backfill_eras()` from the zone name through the catalogue in `wcl_core.game_version` (Molten Core
is Classic, Karazhan is The Burning Crusade, and so on); the game version of a backfilled raid is the host the app
is configured for, since that is where it was fetched from. Anything the catalogue does not know stays `NULL` and
is shown by every profile, so an unknown zone never disappears.

Postgres gets the same columns in Alembic revision `0002_raid_era`.

### Scope (built)

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

### Profiles (built)

```python
@dataclass(frozen=True)
class Profile:
    slug: str                 # "tbc", "classic-days"; the stable id
    name: str                 # what the user sees
    game_version: str | None  # fresh | classic | sod | forever | retail; None = the configured host
    expansions: tuple[str, ...] = ()
    zones: tuple[str, ...] = ()
    since: str | None = None
    until: str | None = None
    guild_id: int | None = None       # the guild to import from; None = config
    wcl_api_url: str | None = None    # the host to import from; None = config, or derived from game_version
    owner: str | None = None          # Discord user id that created it
```

`ProfileStore` is a protocol (`load() -> ProfileSet | None`, `save(ProfileSet)`); `JsonProfileStore` keeps it in
`profiles.json` next to the home layout on the desktop, and the Toads Hub keeps one per member in its own database,
the same split as `HomeLayout`. `ProfileSet` is the list plus the active slug.

A profile is a view, not a partition: the database stays one store and a raid can appear under several profiles.
That is what keeps "normal usage" intact: with no active profile every service behaves exactly as today.

### Identity (built)

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
  "Era" profile import from the right site. `AppContext.headless(...)` takes `profile=` for the Hub and keeps the
  host's own client whatever the profile names.
- `ProfileService`: `list()`, `active()`, `create(...)`, `update(slug, ...)`, `delete(slug)`,
  `activate(slug | None)`, `scope()`, `apply()`, `backfill_eras()`. A profile created while an identity is linked
  gets `owner` stamped.
- `IdentityService`: `current()`, `link(open_browser=...)`, `unlink()`.
- `RaidService.list_raids()` and `count_raids()` and `HomeService` honour the context scope (built);
  `PlayerService`, `BadgeService`, `HealingService`, `ReferenceService` follow in phase 2, each by passing
  `ctx.scope` to the repository reads they already make.

## Beyond the desktop

`wcl_app` is the core API. There is no separate "API package" to build: a host wires `AppContext.headless(client,
storage, profile=...)` with the signed-in member's profile and calls the same services the CLI calls. This mirrors
ESI.ts's one-runtime-many-identities model: one pipeline and one database, a per-identity view on top.

- **Toads Hub** already has Discord OAuth and sessions. It maps its session's Discord id to the profile owner and
  stores `ProfileSet` per member. Nothing in the analyzer needs the Hub's session code.
- **Toads bot**: a member gets a one-time code from the bot and pastes it into the desktop, which registers with the
  Hub as "Leigh's app" and publishes its profiles (phase 4, [hub_bridge.md](hub_bridge.md)). The bot resolves a
  Discord user to a profile with `member_profile` and runs the services under it.
- **Headless CLI/bot use**: `warcraftlogs --profile tbc ...` picks a profile for one run; a bot command maps a
  Discord user to the profile they own.

## Phase map

| Phase | Name | State | Evidence |
| --- | --- | --- | --- |
| 1 | Foundation: vocabulary, columns, scope, profiles, identity, CLI | Merged | PR #144 |
| 2 | Scoped services and frontends | 2.1 to 2.3 merged (#145 to #149); 2.4 planned | PROF-07 to PROF-09 |
| 3 | Import by profile | 3.1 and 3.2 in review; 3.3 waits on Warcraft Logs | PROF-10 to PROF-12 |
| 4 | Bridge to the Toads Hub and bot | 4.1 in review; 4.2 is the Toads port | IDENT-05 to IDENT-07 |
| 5 | Retire the single-host config | Planned | |
| Q | Quality bar: the ESI.ts gates in Python | Merged (#150 to #158) | section below, `guides/CHARTER.md` |

Each phase is a set of PRs that merge alone, one concern per PR, with a definition of done checkable from CI.

### Phase 1: foundation (PR #144)

Scope: everything marked *built* above, the `profile` and `discord` CLI commands, this guide.
Definition of done: CI green including the `storage-postgres` job; PROF-01 to PROF-06 and IDENT-01 to IDENT-04
Enforced.

### Phase 2: scoped services and frontends

Order, one PR each:
1. `BadgeService`, `HealingService`, `ReferenceService`, `PlayerPageService` and the lineage pass `ctx.scope`;
   `scope=` on `get_character_raid_roles`, `get_character_spell_casts`, `get_character_consumable_counts`,
   `get_consumable_totals` and `get_consumable_raids`, with contract tests on both backends. A read of other sources
   narrows the profile's scope to them (`wcl_store.narrowed`), so a TBC profile's reference list is its TBC
   references. Character history (`get_character_history`) is the one read left, in 2.2.
   Context-built services ask `ctx.scope` at each read, so a profile switch reaches services built before it; an
   explicit `scope=` stays fixed. The desktop and CLI build their context with `AppContext.desktop()`, which starts
   in the saved active profile (PROF-08).
2. `get_character_history` takes `scope=`; `PlayerService.history`, the player page and the CLI `history` command
   pass it. Closes PROF-07. With a scope, first and last seen come from the raids inside it, and a character with no
   raids inside it has no history. The desktop's character, compare and history widgets still read the database
   directly; 2.3b moves them onto a service.
3. Desktop: a profile switcher in the toolbar (reads `ProfileService`, calls `apply()`), a Settings section for
   Discord sign-in (`IdentityService.link()` on a worker thread, like the Warcraft Logs sign-in), and a "Tag stored
   raids" action that runs `backfill_eras()`. No view reads the profile file itself.
   2.3a (merged, #147): the top bar's profile switcher (`gui/profile_switcher.py`) over
   `ProfileService.desktop(ctx)`, sharing the window's context with the Home page so a switch refreshes it in place.
   2.3b (merged, #148): `wcl_app.characters.CharacterService` (roster, dossier, comparison) reads the desktop-only
   character queries, which now all take `scope=`, under the context's profile at read time. The Characters hub's list, its
   history panel, the pushed history view and the compare view use it and re-read on a switch, so three entries leave
   `KNOWN_VIOLATIONS`. `character_view` (My Character) still reads the database for peers and imports; it moves with
   the insight views.
   2.3c: Settings' `gui/identity_panel.py`. "Discord Account" links and unlinks through `IdentityService` (the
   browser wait runs on a daemon thread so closing the app never blocks on it); "Raid Eras" runs `backfill_eras()`
   on a worker with the window's context, then the switcher recounts and the scoped views refresh.
4. Headless host: `AppContext.headless(..., profile=)` documented for the Hub; `ProfileSet` round-trip stays the
   contract (`guides/home_widgets.md` style page for the profile payload).
Definition of done: every service read that lists or aggregates raids takes the scope; the desktop shows the active
profile's name and count; `KNOWN_VIOLATIONS` is no larger.

### Phase 3: import by profile

Decided 2026-10-03: an import under a profile pulls only that profile's era. A player may later opt into several
game versions; that is a profile with several game versions, not a change to this rule.

Order:
1. The download view, the CLI's `profile import` and `RaidService.guild_reports()` / `new_guild_reports()` /
   `import_new()` read the profile's guild and host and keep only the reports inside its scope.
   `RaidScope.admits` is the store's scope rule for a raid not stored yet (the contract checks they agree on both
   backends); the guild list asks Warcraft Logs for each report's `zone { expansion }`. A profile switch drops the
   download view's list.
2. Imports tag the era from the API (`get_report_metadata`), so `backfill_eras()` is a one-off for old databases.
   An import, a guild list or a guild analysis under a profile whose game version is not the client's site raises
   `ProfileSiteUnknown` before any request, rather than filing Forever raids under `fresh`. `profile create
   --api-url` gives a profile its own site.
3. `HOSTS` gains `forever` when Warcraft Logs announces its site; a Forever profile then imports from it with no
   other change. Until then a Forever profile can read but not import.
Definition of done: a profile with its own guild id imports only that guild's reports; a raid imported under a
profile is listed by it without a backfill.

### Phase 4: bridge

Decided 2026-10-03: the desktop links to the Hub with a **one-time code from the bot**, pasted into the desktop.
The wire contract is [hub_bridge.md](hub_bridge.md).

Order:
1. (built) `wcl_core.hub` is the Hub client: it redeems a code, publishes profiles and unlinks, through
   `wcl_core.http`, with the token as a `SecretStr`. `wcl_core.testing.FakeHub` issues codes as the bot would and
   keeps what apps publish. `wcl_app.bridge.BridgeService` links, publishes and unlinks. When a Discord identity is
   linked, it refuses a code issued to someone else. `member_profile(directory, discord_id, slug)` is what the bot
   resolves a member through. Frontends: `warcraftlogs hub link|status|publish|unlink` and Settings' "Toads Hub"
   section.
2. Hub side (in the Toads repo, pinned to this one): the three endpoints in `hub_bridge.md`, the bot command that
   issues a code, and bot commands that take a profile slug.
Definition of done: IDENT-05 to IDENT-07 Enforced by contract tests against a fake Hub, the way
`DISCORD_OAUTH_URL` points at the fake Discord.

### Phase 5: retire the single-host config

`wcl_api_url` and `guild_id` in `config.json` become the defaults of the implicit "All" profile; the settings view
edits profiles, not raw keys. Definition of done: no module reads `config["wcl_api_url"]` outside `AppContext`.

## Quality bar: the ESI.ts standard in Python

What ESI.ts enforces and what this repo has, so phase Q can close the gaps one PR at a time. Every gate is a
one-way ratchet: a floor never goes down, a baseline only shrinks, an exception expires.

| ESI.ts gate | Here today | Gap to close |
| --- | --- | --- |
| `lint:layers`, empty shrink-only baseline | `tests/test_architecture.py` + `lint-imports`; `KNOWN_VIOLATIONS` has 36 desktop edges | Move views onto services until the list is empty; then forbid the list growing by construction (it already does) |
| `ci-success` single required check, no job-level `if`, skipped = failed | Enforced, see below | None |
| `check:local` mirrors CI, with a test that parses `ci.yml` | Enforced, see below | None |
| Coverage floors below measured, only up | `fail_under = 70` in `pyproject.toml`, documented as only going up | Raise toward the measured value; add branch coverage |
| Mutation ratchet per directory (Stryker) | Enforced on 6 `wcl_core` modules, see below | More modules, `wcl_store` |
| Properties with known-bad implementations (fast-check) | `tests/fuzz/` with hypothesis | Model-based tests for `RaidScope` filtering and `expansion_for_zone`; each must fail against a registered bad implementation |
| EARS specification, one `shall` per Rule, `spec:audit` | Enforced, see below | None |
| Mock only at the HTTP seam (`lint:bdd-seam`) | A ratchet, see below | Empty `KNOWN_STEP_MOCKS` (4 step modules) |
| `./testing`: mock transport, data factory | `FakeWarcraftLogs`, `FakeDiscord`, `FakeClock` | A `RaidAnalysis` factory |
| API surface snapshot + semver diff | Enforced, see below | Nested payload dataclasses; a `!` commit check |
| Export coverage: every public export referenced by a test | Enforced, see below | None |
| Suite health: no skip/only, no assertion-free tests | Enforced, see below | None |
| Determinism: time only via a clock module | Enforced, see below | The desktop app (`updater.py`, GUI) |
| Error taxonomy with guards | `wcl_core.common.errors` (`WarcraftLogsError`, `AuthenticationError`, `ConfigurationError`), `wcl_store.StorageError` | Document the tree in a guide; add `retryable` on API errors; every service error is a subclass |
| Schemas tolerate additive change | `pydantic` only for `SecretStr`; GraphQL parsed by hand | pydantic models with `extra="allow"` for every API response the analyzer reads |
| Conventional commits, release-please, semver classification | `build_release.sh` bumps versions by hand | Conventional commit check on PR titles, then release automation |
| Dependency audit, expiring exceptions | `pip-audit` task (needs network) | Run it in CI nightly; exceptions with `expires` dates |
| Charter with IDs and statuses, each Enforced row names its check | [CHARTER.md](CHARTER.md), audited | Its Part 10 |

`ci-success` needs every job and fails when one failed, was cancelled or was skipped (`scripts/ci_gate.py`).
`tests/test_dev_tasks.py` reads `ci.yml`: the gate needs every job, only the gate has a job-level `if:`, and each job
runs exactly its `dev.py` tasks (`JOB_TASKS`) or is listed in `OUTSIDE_DEV` with a reason.

`tests/test_suite_health.py` lints `tests/`: every skip or xfail mark and every `pytest.skip`/`xfail`/`fail` call
says why, every test function asserts (or uses `pytest.raises`, a mock's `assert_*`, a pytest-qt signal wait, or a
module helper that asserts), and no `except Exception`/bare `except`/`suppress(Exception)` drops the exception. These
rules have no allow-list; each has its own test on a small source.

`tests/test_api_contract.py` guards the API the Toads Hub and bot build on: `wcl_app`, `wcl_store`,
`wcl_core.clock`, `wcl_core.http` and `wcl_core.testing`. Every name in their `__all__` is named by a test, and
every public method of an exported `*Service` and of `RaidRepository` is called by one. `tests/api_surface.txt` records one line per export,
dataclass field and signature, read from the source; any change fails until the file is regenerated with
`WCL_UPDATE_SURFACE=1 pytest tests/test_api_contract.py`, and the failure lists the lines that are gone as breaking.
`master` requires `ci-success` through a ruleset.

`scripts/mutate.py` plants one bug at a time in a `wcl_core` module (a flipped comparison or operator, `and`/`or`,
a dropped `not`, a negated `if`, a changed constant, `return None`) in a scratch copy, and runs that module's tests
against it. `[tool.wcl.mutation]` in `pyproject.toml` lists each module, its tests and its floor, the share of
mutants the tests must kill; the `mutation` CI job (`python scripts/dev.py mutation`, also part of `check`) fails a
module below its floor. Floors only go up. Starting scores: `http` 100%, `game_version` 94%, `dynamic_role_parser`
91%, `flasks` 88%, `auth` 71%, `cache` 30%; `-v` lists the survivors to aim at.

Every request wcl-core makes goes through `wcl_core.http` (`post`/`get`, each with a timeout); a test checks that no
module in `packages/` calls `requests` directly. `wcl_core.testing` ships fakes for that seam: `FakeWarcraftLogs`
answers the token endpoint and GraphQL queries (matched by a substring of the query), `FakeDiscord` the Discord token
and `/users/@me` endpoints, both record every request and fail on one they cannot answer. Step definitions use them
instead of `unittest.mock` or a patched `requests`/`wcl_app`; `test_step_definitions_mock_only_at_the_http_seam` in
the suite-health lint holds the step modules that still mock to `KNOWN_STEP_MOCKS`, which may only shrink.

The shared packages read the time only through `wcl_core.clock` (`time`, `monotonic`, `now`, `today`, `sleep`),
the system clock unless `clock.use(...)` swaps one in. `wcl_core.testing.FakeClock` moves only on `sleep` or
`advance` and records each wait, so token expiry, retry backoff and "this week" are tested without waiting or
depending on the day. `tests/test_clock.py` fails on any other `time.time`/`monotonic`/`sleep`/`perf_counter` or
`datetime.now`/`utcnow`/`today` in `packages/`, with no allow-list.

`tests/test_spec_audit.py` audits the specification. Each scenario in `tests/features/` holds one `shall`, carries
one `@ears_*` tag, and opens with that pattern's word (When, While, If, Where, or none for ubiquitous). Every feature
file is bound by a step module. Every row of the requirements table above holds one `shall` and a known status, and an
Enforced row names tests that exist. Every Enforced row also has a scenario titled with its ID and its exact words
(`tests/features/profiles.feature`), except the few in `NO_SCENARIO`, each with the reason another test proves it.

Order for phase Q, cheapest first: fan-in CI job and the `dev.py` parity test (done); suite-health lint (done); the
EARS audit over `tests/features/` with a scenario per requirement (done); `wcl_core.testing` with the fake
transport (done); export coverage and the surface snapshot (done); mutation on `wcl_core` with a floor (done); the clock
lint (done); the charter (done). What is left of the gap table is the charter's gap register.

## Open questions

- Which Warcraft Logs site Forever will use. Until known, `forever` profiles keep the configured host.
- Resolved 2026-10-03: the Hub registers apps per Discord account, through a code the bot issues to that account.
