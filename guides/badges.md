# Toads badges

Small awards for turning up to raids and for coming prepared. Each badge counts one thing across every stored guild
raid (raids attended, raids with a flask or an elixir pair, or consumables used from one family) and has up to four
tiers named after WoW item quality.
The desktop app draws them as small round icons on the Player page and in the Home `badges` widget, so a player sees
their own and a raid leader sees the whole roster's. The Toads Hub serves the same payloads.

Badges are worked out from storage on demand (`wcl_app.badges`); nothing extra is stored. Tests:
`tests/test_badges.py` (SQLite and Postgres), `tests/test_home_service.py` and the GUI tests.

## Using the service

```python
from wcl_app import BadgeService

badges = BadgeService.from_context(ctx)        # storage and thresholds from the context
badges.catalogue()                             # list[BadgeRule]: every badge in play
badges.for_character("Hadur").to_dict()        # one player, every badge, earned or not
[p.to_dict() for p in badges.for_guild()]      # everyone, most tiers first
badges.rules.to_dict()                         # the catalogue as JSON
```

`PlayerPageService.get_page(...).badges` carries the player's badges, and `HomeService` builds the `badges` widget
(`guides/home_widgets.md`). Both read thresholds from the same config.

Storage reads: `get_raid_attendance(sources)`, `get_consumable_totals(sources)` and
`get_consumable_raids(names, sources)` (for Flask Bearer) for the guild, `get_character_raid_roles` and
`get_character_consumable_counts` for one player. Only `guild` raids count unless a
host passes other `sources`.

## Tiers

| tier | `quality`   | `tier_name` | suggested colour |
|------|-------------|-------------|------------------|
| 0    | `""`        | `""`        | dimmed: not earned yet |
| 1    | `uncommon`  | Uncommon    | `#1eff00`        |
| 2    | `rare`      | Rare        | `#0070dd`        |
| 3    | `epic`      | Epic        | `#a335ee`        |
| 4    | `legendary` | Legendary   | `#ff8000`        |

`stacks` is how many times the first tier has been reached: 200 mana potions against a first tier of 10 is 20, drawn
as "x20".

## Default badges

| id                    | name           | counts                                            | thresholds        |
|-----------------------|----------------|---------------------------------------------------|-------------------|
| `attendance`          | Loyal Toad     | raids attended                                    | 5, 15, 40, 100    |
| `well_stocked`        | Well Stocked   | every consumable except flasks and elixirs        | 50, 250, 750, 2000 |
| `mana_potions`        | Mana Guzzler   | mana potions, Bottled Nethergon Energy, Dreamless Sleep | 10, 50, 150, 400 |
| `healing_potions`     | Survivor       | healing and rejuvenation potions, healthstones, Nightmare Seed | 10, 40, 100, 250 |
| `combat_potions`      | Liquid Courage | Destruction, Haste, Heroic, Insane Strength, Ironshield, Mad Alchemist's, Mighty Rage | 10, 50, 150, 400 |
| `runes`               | Rune Eater     | Dark and Demonic Runes                            | 10, 40, 100, 250  |
| `drums`               | Drummer        | Drums of Battle                                   | 10, 50, 150, 400  |
| `explosives`          | Sapper         | sapper charges, grenades, bombs, flame turrets    | 10, 50, 150, 400  |
| `weapon_enhancements` | Sharpened      | weapon oils and stones                            | 5, 20, 50, 120    |
| `scrolls`             | Scholar        | Scrolls of Agility and Strength                   | 5, 20, 50, 120    |
| `flasked`             | Flask Bearer   | raids with a flask or an elixir pair (below)      | 5, 15, 40, 100    |

Consumable names are those `wcl_core/data/consumes_config.json` records, matched ignoring case. Flask Bearer's
catalogue entry is `{"id": "flasked", "name": "Flask Bearer", "icon": "flask", "glyph": "⚗️", "unit": "raids"}`
plus its tiers.

## Flasks and elixirs

`consumes_config.json` lists flasks, battle elixirs and guardian elixirs in their own sections (`flasks`,
`battle_elixirs`, `guardian_elixirs`) by the aura id WarcraftLogs reports. They are drunk before the pull, so they are
read from each player's buffs table (the same call the buff consumables use), not from casts, and stored as ordinary
consumable rows: `count` is how many times the aura was applied, `timestamps` when. They therefore show up in the
`flasks` Home widget, the reference comparison and the lineage consumables with no extra work. Well Stocked and the
`consumables` Home widget leave them out, since a flask aura can be applied several times a raid.

A player is **prepared** for a raid with a flask, or with a battle elixir and a guardian elixir together (in TBC a
flask counts as both). `wcl_core.flasks.preparation(names, catalog)` returns `"flask"`, `"elixirs"` or `""`, and
`FlaskCatalog.kind_of(name)` says whether a consumable name is a `flask`, `battle_elixir` or `guardian_elixir`.
Flask Bearer counts prepared raids; lineage adds a "Flask or elixir pair" metric (1 or 0 per raid, so `mean` is the
share of raids prepared) once a character has any flask or elixir on record.

At analysis time `RaidAnalysis.flask_coverage` also says, per player, which boss pulls (kills and wipes) began with a
flask or an elixir pair up (within 5 seconds of the pull). Each player is scored only on the pulls the fight's
`friendlyPlayers` list puts them in, so `boss_pulls` is their own pull count. It is not stored yet, so a raid read back from storage has an
empty list. `FlaskCoverage.to_dict()`:

```json
{
  "name": "Stabby",
  "role": "melee",
  "report_id": "aBcD1234eFgH5678",
  "boss_pulls": 12,
  "prepared_pulls": 11,
  "flask_pulls": 0,
  "elixir_pair_pulls": 11,
  "flasks": [],
  "battle_elixirs": ["Elixir of Major Agility"],
  "guardian_elixirs": ["Elixir of Major Defense"]
}
```

Raids imported before these sections existed have no flask or elixir rows; re-import a raid to fill them in.

## Configuring

A `badges` section in `config.json` (or the `config` a headless host passes to `AppContext`):

```json
"badges": {
    "thresholds": {"attendance": [5, 15, 40, 100], "mana_potions": [20, 100]},
    "disabled": ["explosives"]
}
```

`thresholds` gives 1 to 4 ascending positive whole numbers per badge id; fewer numbers mean fewer tiers. A malformed
entry keeps the default and is logged. `disabled` drops badges. Unknown ids are ignored.

## Badge

```json
{
  "id": "mana_potions",
  "name": "Mana Guzzler",
  "description": "Mana potions",
  "icon": "mana_potion",
  "glyph": "🧪",
  "tier": 3,
  "quality": "epic",
  "tier_name": "Epic",
  "value": 212,
  "display": "212 potions",
  "stacks": 21,
  "next_at": 400,
  "next_tier": "Legendary",
  "progress": 0.248
}
```

| field       | meaning                                                                        |
|-------------|--------------------------------------------------------------------------------|
| `icon`      | stable icon id for a frontend's own artwork                                    |
| `glyph`     | an emoji to draw when there is no artwork                                      |
| `value`     | the raw count; `display` is it formatted with its unit                         |
| `next_at`   | the count the next tier needs, or null at the top tier (`next_tier` is then "") |
| `progress`  | 0 to 1 from the current tier's threshold to the next; 1 at the top tier        |

## Player

`PlayerBadges.to_dict()`: `{name, player_class, score, badges}` with every badge in play, earned or not, in catalogue
order. `score` is the sum of tiers, used to rank a roster. The Home widget's `holders` list only earned badges.

## Catalogue

`BadgeRules.to_dict()`: `{version, badges: [{id, name, description, icon, glyph, unit, tiers: [{tier, quality, name,
at}]}]}`. `version` is `BADGES_SCHEMA_VERSION`; it changes only when a field changes meaning or goes away.
