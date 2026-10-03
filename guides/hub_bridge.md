# Toads Hub bridge: the app link contract

Status: **experimental**, phase 4 of [identity_and_profiles.md](identity_and_profiles.md). This page is the wire
contract between an analyzer (desktop or CLI) and the Toads Hub. The Python side is built and tested here against
`wcl_core.testing.FakeHub`; the Hub and bot side gets ported to the Toads repo against this page.

## The flow

1. In Discord, a member asks the Toads bot to link an app. The bot already knows their Discord id, so it asks the
   Hub for a one-time code bound to that member and sends it to them privately.
2. The member pastes the code into the analyzer: Settings, "Toads Hub", or `warcraftlogs hub link CODE`.
3. The analyzer redeems the code. The Hub answers with an app id, an app token and the member the code was issued
   to. The analyzer keeps them in `hub_link.json` next to `discord_identity.json`, readable by its owner only. Linking
   again replaces the old registration and asks the Hub to drop it.
4. The analyzer publishes its raid profiles (`ProfileSet`). It does so again on `hub publish` or "Publish profiles".
   If that first publish fails the app is still linked (the code is spent): `HubLinkedNotPublished` says so, and
   publishing again is all that is left.
5. When a member runs a bot command, the bot resolves their Discord id to a profile with
   `wcl_app.member_profile(directory, discord_id, slug)`. It then runs the shared services under that profile with
   `AppContext.headless(client, storage, profile=...)`. No slug means the member's active profile, or none. A slug
   the member never published raises `ProfileNotPublished`, so a typo never widens a command to every raid.

The code is the proof of identity: only the member the bot gave it to can have it. The analyzer needs no Discord
sign-in to link. If it has one (`discord login`) and the code was issued to someone else, it links nothing and asks
the Hub to drop the app (IDENT-07).

## Settings

| Setting | Where | Meaning |
| --- | --- | --- |
| Hub URL | `TOADS_HUB_URL`, else `toads_hub_url` in `config.json` | The Hub's base URL. `https` only, except `localhost`, `127.0.0.1` and `::1` |

## Codes

Eight characters in two groups of four, `7KQ2-M9XD`, from Crockford's base 32 (`0-9`, `A-Z` without `I`, `L`, `O`,
`U`). The analyzer accepts lower case, spaces and a missing hyphen, and always sends the canonical upper-case,
hyphenated form. A malformed code is refused before any request. The Hub should make codes single use and short-lived
(ten minutes is the suggestion) and bind each to the Discord id that asked for it.

## Endpoints

Every request is a `POST` with a JSON body and a 30 second timeout. Every request after the link carries
`Authorization: Bearer <app token>`. The analyzer never logs the code, the token or a reply body.

### `POST /api/apps/link`

Request:

```json
{"code": "7KQ2-M9XD", "app": {"name": "WarcraftLogs Analyzer", "version": "1.4.0"}}
```

| Status | Meaning | Analyzer |
| --- | --- | --- |
| 200 or 201 | Linked; body below | Keeps the link, then publishes profiles |
| 400 | Malformed code | `AuthenticationError`: ask the bot again |
| 404 | Unknown or already used code | Same |
| 410 | Expired code | Same |
| anything else | Hub trouble | `HubError` with the status |

Reply body:

```json
{
  "app_id": "app-1",
  "token": "<opaque app token>",
  "member": {"discord_id": "123456789", "username": "toadlord", "display_name": "Leigh"}
}
```

`display_name` may be null. A body missing `app_id`, `token`, `member.discord_id` or `member.username` is a `HubError`.

### `POST /api/apps/profiles`

The body is the analyzer's `ProfileSet.to_dict()` (`{"version": 1, "active": "tbc", "profiles": [...]}`, each
profile as `Profile.to_dict()`). It replaces whatever the member published before. 200 or 204 is success. 401 means
the Hub no longer knows the token, and the analyzer says to link again. Anything else is a `HubError`.

### `POST /api/apps/unlink`

No body. 200 or 204 is success. 401 also counts as success, because the Hub had already forgotten the app. The
analyzer forgets the link locally whatever the Hub answers, and reports whether the Hub confirmed. If the link file
cannot be deleted, the unlink fails and the app stays linked, rather than finding the link again on the next start.

## The Hub's side, for the port

- Store per app: the app id, a hash of the token, the member's Discord id, the app name and version, and when it
  linked. Store per member: the latest `ProfileSet` an app published.
- The Hub's profile table is the `ProfileDirectory` the bot passes to `member_profile`: `load(discord_id)` returns
  the stored set or its dict.
- Permissions stay in the Hub and the bot: who may ask for a code, and which commands may run under a profile.
  `wcl_app` only says who and which profile.

## Tests

- `tests/test_hub_bridge.py`: the client, the service, the resolver and the CLI against `FakeHub`, including every
  status in the tables above.
- `tests/gui/test_hub_panel.py`: the Settings section.
- `tests/features/profiles.feature`: IDENT-05 to IDENT-07.
- The mutation floor on `wcl_core.hub` is 100%.
