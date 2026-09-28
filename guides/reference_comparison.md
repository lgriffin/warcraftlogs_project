# Reference comparison

Officers compare one of our raids against another guild's raid of the same zone: a *reference*. The desktop
Reference view, the `reference` CLI command and the Toads Hub all use `wcl_app.reference.ReferenceService`
(`warcraftlogs_client.services.reference` in the desktop app). Tests: `tests/test_reference_service.py` (SQLite
and Postgres), `tests/test_reference_cli.py` and `tests/test_reference_reports.py`.

## The dedicated login

Another guild's report needs a user-scoped Warcraft Logs token (`/api/v2/user`); the client-credentials key
only sees public data. `ReferenceService.import_reference` analyses through `AppContext.user_client()` and raises
`ReferenceAuthRequired` when there is none.

- Desktop: Reference > Authenticate runs the OAuth flow and keeps the token in the user data dir
  (`wcl_core.user_auth.UserTokenManager`). The CLI uses the same token.
- Headless hosts keep the token themselves and pass it in:

```python
from wcl_core.client import WarcraftLogsClient
from wcl_core.user_auth import HostedUserToken, UserToken, token_url_for, user_api_url

tokens = HostedUserToken(stored_token, client_id, client_secret, token_url_for(api_url), on_refresh=save_token)
user = WarcraftLogsClient(tokens, cache_enabled=False, api_url=user_api_url(api_url))
ctx = AppContext.headless(guild_client, storage, user_client=lambda: user)
```

`on_refresh` gets each refreshed `UserToken` (Warcraft Logs may rotate the refresh token). A refused refresh
raises `AuthenticationError`: the host should ask for a new sign-in.

## Using the service

```python
refs = ReferenceService(ctx)
refs.import_reference("https://fresh.warcraftlogs.com/reports/abcd…", label="World first Gruul")
refs.references()              # list[StoredRaid], newest first (report_id, title, raid_date, zone, raid_size, label)
refs.guild_raids()             # our raids a reference can be compared against
refs.set_label(code, "")       # "" or None clears the label
refs.delete_reference(code)    # refuses guild raids
refs.compare(ours, theirs).to_dict()
```

Codes may be bare 16-character codes or report URLs. Bad codes, a report already stored (as either kind), a guild
raid where a reference is expected (or the reverse) and labels over 80 characters raise `ReferenceRequestError`
(a `ValueError`) with a message fit to show the user.

## Comparison payload (`version` 1)

```jsonc
{
  "version": 1,
  "guild":     {"report_id", "title", "raid_date", "zone", "raid_size", "duration_ms"},
  "reference": {…same…},
  "scope": {"scoped": true, "shared_encounters": 2, "guild_extra_encounters": ["Magtheridon"]},
  "overview":    [Metric],   // duration, total_damage, total_healing, damage_taken, damage_per_dps,
                             // healing_per_healer, overheal
  "composition": [Metric],   // raid_size, tanks, healers, melee, ranged
  "classes":     [{"player_class", "role", "metric", "guild_count", "guild_average",
                   "reference_count", "reference_average", "delta_percent"}],
  "consumables": [{"name", "guild_uses", "guild_users", "reference_uses", "reference_users"}],
  "encounters":  [{"name", "guild_duration_ms", "reference_duration_ms", "guild_damage", "reference_damage",
                   "guild_healing", "reference_healing", "duration_delta_percent"}]
}
```

A `Metric` is `{"key", "label", "guild", "reference", "guild_display", "reference_display", "delta_percent",
"higher_is_better", "better"}`. `delta_percent` is ours against the reference and `better` says whether that is
good; both are null when a side is missing or the reference is zero. Displays are already formatted (`"1.23M"`,
`"48:10"`, `"21.4%"`, `"—"` for missing), so a frontend never formats numbers.

`classes` holds each role's own number: healing for healers, mitigation % for tanks, damage for DPS. When our raid
killed bosses the reference did not, `scope.scoped` is true and `consumables` and `encounters` cover only the window
of the shared bosses; totals, composition and classes always cover each whole raid.
