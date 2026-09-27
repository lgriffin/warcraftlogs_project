# Home page widgets

The desktop Home view and the Toads Hub both draw their home page from `wcl_app.home.HomeService`
(`warcraftlogs_client.services.home` in the desktop app). The service owns the widget catalogue, the data in
each widget and the user's layout; a frontend only draws the payloads below and maps links onto its own
navigation. Tests: `tests/test_home_service.py` (SQLite and Postgres) and `tests/gui/test_home_view.py`.

## Using the service

```python
from wcl_app import AppContext, HomeService, JsonLayoutStore

home = HomeService.from_context(ctx, layouts)   # layouts: any LayoutStore; omitted means in memory
home.catalogue()                                # list[WidgetSpec]: every widget a user can pick
home.layout()                                   # HomeLayout: the saved one, else the default
home.save_layout(["last_raid", "attendance"])   # order is kept; unknown ids and repeats are dropped
home.reset_layout()                             # forget the saved layout
home.page().to_dict()                           # every widget of the saved layout, as JSON
home.widget("attendance").to_dict()             # one widget, to refresh it alone
```

Storage comes from `ctx.repository()`, so a headless host (`AppContext.headless(client, storage)`) gets the
same payloads from Postgres. Only `RaidRepository` methods are used: no new storage operations.

A `LayoutStore` has `load() -> HomeLayout | None` and `save(layout | None)`. The desktop uses
`JsonLayoutStore(<user data dir>/home_layout.json)`. The Hub should keep one layout per member, storing
`HomeLayout.to_dict()` and reading it back with `HomeLayout.from_dict()`, which falls back to the default for
anything missing or malformed.

## Page

```json
{
  "version": 1,
  "generated_at": "2026-09-27 12:00:00",
  "widgets": [ <widget>, ... ]
}
```

`version` is `HOME_SCHEMA_VERSION`; it changes only when a field below changes meaning or goes away.
`generated_at` is the host's local time.

## Widget

Every widget has these fields, plus the fields of its kind:

| field      | type                | meaning                                                                 |
|------------|---------------------|-------------------------------------------------------------------------|
| `id`       | string              | catalogue id, below                                                     |
| `title`    | string              | heading                                                                 |
| `kind`     | string              | `stats`, `table`, `list`, `bars` or `actions`                           |
| `size`     | string              | `full` (a whole row) or `half` (half a row, paired with the next half)  |
| `subtitle` | string              | context such as the raid it describes; may be empty                     |
| `link`     | link or null        | what the whole widget opens (an "Open" button)                          |
| `empty`    | string              | set when there is nothing to show: draw this message instead of a body |
| `error`    | string              | set when loading this widget failed; the rest of the page still loads  |

| kind      | fields                | item shape                                                                      |
|-----------|-----------------------|---------------------------------------------------------------------------------|
| `stats`   | `tiles`               | `{label, value, display, hint}`                                                 |
| `table`   | `columns`, `rows`     | column `{key, label, align}`; row `{cells, values, link}`                       |
| `list`    | `items`               | `{label, detail, link}`                                                         |
| `bars`    | `bars`                | `{label, value, display}`; scale each bar against the largest `value`           |
| `actions` | `actions`             | `{id, label, description}`                                                      |

Numbers come twice: `value` / `values` are raw (for sorting and charts) and `display` / `cells` are already
formatted ("1.2M", "75.0%", "Mon 21 Sep 2026"), so no frontend formats numbers itself. `align` is `left` or
`right`. A row's `cells` and `values` are keyed by column `key`.

## Links

`{"kind": ..., "params": {...}}`

| kind          | params                     | desktop                       | Hub (suggested)                   |
|---------------|----------------------------|-------------------------------|-----------------------------------|
| `raid`        | `report_id`                | opens the raid analysis       | the raid page                     |
| `character`   | `name`                     | opens the character history   | the character page                |
| `player_page` | `name`, `server`, `region` | Player page, prefilled        | the player page                   |
| `action`      | `id` (a quick action id)   | the command palette key       | the matching route, or hide it    |

Quick action ids: `raids.download`, `raids.browse`, `raids.diff`, `characters`, `characters.player`,
`insights`, `raid_groups`. A frontend that has no page for one can drop that button.

## Catalogue

| id                | kind    | size | default | shows                                                               |
|-------------------|---------|------|---------|---------------------------------------------------------------------|
| `quick_actions`   | actions | full | yes     | shortcuts to the main parts of the app                              |
| `guild_snapshot`  | stats   | full | yes     | raids stored, active raiders (last 10 raids), raids in 30 days, last raid, days since |
| `last_raid`       | stats   | full | yes     | date, duration, bosses killed, raid size, total damage and healing; links the raid |
| `recent_raids`    | list    | half | yes     | the 8 newest raids                                                   |
| `raid_activity`   | bars    | half | yes     | raids per week for the last 8 weeks, labelled by the week's Monday   |
| `top_damage`      | table   | half | yes     | top 5 damage in the last raid: rank, name, class, damage, share      |
| `top_healing`     | table   | half | yes     | top 5 healing in the last raid: rank, name, class, healing, overheal |
| `attendance`      | table   | half | yes     | top 10 attendance over the last 10 raids: name, class, raids, attendance |
| `boss_kills`      | table   | half | no      | bosses killed in the last raid, in kill order: boss, kill time, players |
| `class_mix`       | bars    | half | no      | players per class in the last raid                                  |
| `interrupts`      | table   | half | no      | top 5 interrupters in the last raid                                 |
| `consumables`     | table   | half | no      | top 5 consumable users in the last raid: name, role, used           |
| `tracked_players` | table   | half | no      | player pages: name, server, region, logs added                      |

"Raids" means guild raids; reference reports are left out. Adding a widget means a `WidgetSpec` in
`CATALOGUE`, a builder in `HomeService`, a test in `tests/test_home_service.py` and a row in this table.
