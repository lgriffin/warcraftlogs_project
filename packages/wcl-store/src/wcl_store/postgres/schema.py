"""SQLAlchemy Core tables for the Postgres backend.

These mirror the SQLite tables the ``RaidRepository`` methods touch, with Postgres types: ``BIGINT`` for
millisecond timestamps and totals, double precision for percentages, and unique indexes on ``lower(...)``
where SQLite uses ``COLLATE NOCASE``. Dates and the JSON-encoded lists stay text so both backends return
identical rows. Alembic migrations in ``migrations/versions`` create them; ``test_store_contract`` checks
the migrations and this module agree.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)

# UTC "YYYY-MM-DD HH:MM:SS", the format SQLite's datetime('now') writes.
NOW_TEXT = text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def _id() -> Column[Any]:
    return Column("id", Integer, Identity(), primary_key=True)


def _fk(name: str, target: str, *, cascade: bool = False) -> Column[Any]:
    return Column(name, Integer, ForeignKey(target, ondelete="CASCADE" if cascade else None), nullable=False)


characters = Table(
    "characters",
    metadata,
    _id(),
    Column("name", Text, nullable=False),
    Column("player_class", Text, nullable=False),
    Column("first_seen", Text, nullable=False),
    Column("last_seen", Text, nullable=False),
)
Index("uq_characters_lower_name", func.lower(characters.c.name), unique=True)

raids = Table(
    "raids",
    metadata,
    _id(),
    Column("report_id", Text, nullable=False, unique=True),
    Column("title", Text, nullable=False),
    Column("owner", Text),
    Column("raid_date", Text, nullable=False, index=True),
    Column("start_time", BigInteger, nullable=False),
    Column("end_time", BigInteger),
    Column("imported_at", Text, nullable=False, server_default=NOW_TEXT),
    Column("source", Text, nullable=False, server_default="guild", index=True),
    Column("label", Text),
    Column("raid_size", Integer),
    Column("zone", Text),
)

healer_performance = Table(
    "healer_performance",
    metadata,
    _id(),
    _fk("character_id", "characters.id"),
    _fk("raid_id", "raids.id"),
    Column("total_healing", BigInteger, nullable=False, server_default="0"),
    Column("total_overhealing", BigInteger, nullable=False, server_default="0"),
    Column("overheal_percent", Float, nullable=False, server_default="0"),
    Column("fear_ward_casts", Integer, nullable=False, server_default="0"),
    Column("total_dispels", Integer, nullable=False, server_default="0"),
    Column("active_time_percent", Float, server_default="0"),
    UniqueConstraint("character_id", "raid_id"),
    Index(None, "raid_id"),
)

healer_spells = Table(
    "healer_spells",
    metadata,
    _id(),
    _fk("healer_performance_id", "healer_performance.id", cascade=True),
    Column("spell_id", BigInteger, nullable=False),
    Column("spell_name", Text, nullable=False),
    Column("casts", Integer, nullable=False, server_default="0"),
    Column("total_healing", BigInteger, nullable=False, server_default="0"),
    Index(None, "healer_performance_id"),
)

tank_performance = Table(
    "tank_performance",
    metadata,
    _id(),
    _fk("character_id", "characters.id"),
    _fk("raid_id", "raids.id"),
    Column("total_damage_taken", BigInteger, nullable=False, server_default="0"),
    Column("total_mitigated", BigInteger, nullable=False, server_default="0"),
    Column("mitigation_percent", Float, nullable=False, server_default="0"),
    Column("active_time_percent", Float, server_default="0"),
    UniqueConstraint("character_id", "raid_id"),
    Index(None, "raid_id"),
)

tank_damage_taken = Table(
    "tank_damage_taken",
    metadata,
    _id(),
    _fk("tank_performance_id", "tank_performance.id", cascade=True),
    Column("spell_id", BigInteger, nullable=False),
    Column("spell_name", Text, nullable=False),
    Column("hits", Integer, nullable=False, server_default="0"),
    Index(None, "tank_performance_id"),
)

tank_abilities = Table(
    "tank_abilities",
    metadata,
    _id(),
    _fk("tank_performance_id", "tank_performance.id", cascade=True),
    Column("spell_id", BigInteger, nullable=False),
    Column("spell_name", Text, nullable=False),
    Column("casts", Integer, nullable=False, server_default="0"),
    Index(None, "tank_performance_id"),
)

dps_performance = Table(
    "dps_performance",
    metadata,
    _id(),
    _fk("character_id", "characters.id"),
    _fk("raid_id", "raids.id"),
    Column("role", Text, nullable=False),
    Column("total_damage", BigInteger, nullable=False, server_default="0"),
    Column("active_time_percent", Float, server_default="0"),
    UniqueConstraint("character_id", "raid_id"),
    CheckConstraint("role IN ('melee', 'ranged')", name="role"),
    Index(None, "raid_id"),
)

dps_abilities = Table(
    "dps_abilities",
    metadata,
    _id(),
    _fk("dps_performance_id", "dps_performance.id", cascade=True),
    Column("spell_id", BigInteger, nullable=False),
    Column("spell_name", Text, nullable=False),
    Column("casts", Integer, nullable=False, server_default="0"),
    Column("total_damage", BigInteger, nullable=False, server_default="0"),
    Index(None, "dps_performance_id"),
)

consumable_usage = Table(
    "consumable_usage",
    metadata,
    _id(),
    _fk("character_id", "characters.id"),
    _fk("raid_id", "raids.id"),
    Column("consumable_name", Text, nullable=False),
    Column("count", Integer, nullable=False, server_default="0"),
    Column("timestamps", Text),
    UniqueConstraint("character_id", "raid_id", "consumable_name"),
    Index(None, "raid_id"),
)

interrupt_usage = Table(
    "interrupt_usage",
    metadata,
    _id(),
    _fk("character_id", "characters.id"),
    _fk("raid_id", "raids.id"),
    Column("spell_id", BigInteger, nullable=False),
    Column("spell_name", Text, nullable=False),
    Column("count", Integer, nullable=False, server_default="0"),
    Column("timestamps", Text),
    UniqueConstraint("character_id", "raid_id", "spell_id"),
    Index(None, "raid_id"),
)

cancelled_casts = Table(
    "cancelled_casts",
    metadata,
    _id(),
    _fk("character_id", "characters.id"),
    _fk("raid_id", "raids.id"),
    Column("total_casts", Integer, nullable=False, server_default="0"),
    Column("cancelled_casts", Integer, nullable=False, server_default="0"),
    Column("cancel_rate", Float, nullable=False, server_default="0"),
    UniqueConstraint("character_id", "raid_id"),
    Index(None, "raid_id"),
)

cancelled_cast_spells = Table(
    "cancelled_cast_spells",
    metadata,
    _id(),
    _fk("character_id", "characters.id"),
    _fk("raid_id", "raids.id"),
    Column("spell_id", BigInteger, nullable=False),
    Column("spell_name", Text, nullable=False, server_default=""),
    Column("total_casts", Integer, nullable=False, server_default="0"),
    Column("cancelled_casts", Integer, nullable=False, server_default="0"),
    Column("cancel_rate", Float, nullable=False, server_default="0"),
    Column("timestamps", Text),
    Column("correlations", Text),
    Column("next_casts", Text),
    UniqueConstraint("character_id", "raid_id", "spell_id"),
    Index(None, "raid_id"),
)

encounters = Table(
    "encounters",
    metadata,
    _id(),
    _fk("raid_id", "raids.id", cascade=True),
    Column("encounter_id", Integer, nullable=False),
    Column("name", Text, nullable=False),
    Column("start_time", BigInteger, nullable=False),
    Column("end_time", BigInteger, nullable=False),
    Column("duration_ms", BigInteger, nullable=False),
    Column("boss_events", Text),
    UniqueConstraint("raid_id", "encounter_id", "start_time"),
)

encounter_performance = Table(
    "encounter_performance",
    metadata,
    _id(),
    _fk("encounter_row_id", "encounters.id", cascade=True),
    _fk("character_id", "characters.id"),
    Column("role", Text),
    Column("total_damage", BigInteger, server_default="0"),
    Column("total_healing", BigInteger, server_default="0"),
    Column("total_damage_taken", BigInteger, server_default="0"),
    Column("active_time_percent", Float, server_default="0"),
    UniqueConstraint("encounter_row_id", "character_id"),
    CheckConstraint("role IN ('healer', 'tank', 'melee', 'ranged', 'unknown')", name="role"),
)


def _uptime_table(name: str) -> Table:
    return Table(
        name,
        metadata,
        _id(),
        _fk("raid_id", "raids.id", cascade=True),
        _fk("encounter_row_id", "encounters.id", cascade=True),
        Column("spell_id", BigInteger, nullable=False),
        Column("spell_name", Text, nullable=False),
        Column("uptime_percent", Float, nullable=False, server_default="0"),
        Column("bands_json", Text),
        UniqueConstraint("raid_id", "encounter_row_id", "spell_id"),
    )


aura_uptime = _uptime_table("aura_uptime")
totem_uptime = _uptime_table("totem_uptime")

player_pages = Table(
    "player_pages",
    metadata,
    _id(),
    Column("name", Text, nullable=False),
    Column("server", Text, nullable=False),
    Column("region", Text, nullable=False),
    Column("created_at", Text, nullable=False, server_default=NOW_TEXT),
)
Index(
    "uq_player_pages_lower_name_server_region",
    func.lower(player_pages.c.name),
    func.lower(player_pages.c.server),
    func.lower(player_pages.c.region),
    unique=True,
)

player_page_logs = Table(
    "player_page_logs",
    metadata,
    _id(),
    _fk("player_page_id", "player_pages.id", cascade=True),
    Column("report_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("title", Text, nullable=False, server_default=""),
    Column("zone", Text),
    Column("owner", Text),
    Column("start_time", BigInteger, nullable=False, server_default="0"),
    Column("updated_at", Text, nullable=False, server_default=NOW_TEXT),
    UniqueConstraint("player_page_id", "report_id"),
    CheckConstraint("status IN ('added', 'dismissed')", name="status"),
)

role_overrides = Table(
    "role_overrides",
    metadata,
    _id(),
    Column("character_name", Text, nullable=False),
    Column("report_id", Text, nullable=False, server_default=""),
    Column("role", Text, nullable=False),
    Column("updated_at", Text, nullable=False, server_default=NOW_TEXT),
    CheckConstraint("role IN ('healer', 'tank', 'melee', 'ranged', 'dps')", name="role"),
)
Index(
    "uq_role_overrides_lower_character_name_report_id",
    func.lower(role_overrides.c.character_name),
    role_overrides.c.report_id,
    unique=True,
)

# Which players an override actually moved in a stored raid, so clearing it re-analyses only those raids.
role_override_raids = Table(
    "role_override_raids",
    metadata,
    Column("raid_id", Integer, ForeignKey("raids.id"), nullable=False),
    Column("character_name", Text, nullable=False),
    Column("detected_role", Text, nullable=False),
)
Index(
    "uq_role_override_raids_raid_id_lower_character_name",
    role_override_raids.c.raid_id,
    func.lower(role_override_raids.c.character_name),
    unique=True,
)

# Per-character lookups (history, lineage, rosters) go through these.
for _t in (healer_performance, tank_performance, dps_performance, consumable_usage, interrupt_usage):
    Index(None, _t.c.character_id)
