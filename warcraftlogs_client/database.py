"""
SQLite database for historical character performance tracking.

Stores per-character, per-raid performance metrics so users can
track trends over time: healing output, damage dealt, mitigation,
consumable habits, etc.
"""

import contextlib
import json
import os
import sqlite3
from datetime import datetime

from .cache import _cache_file, clear_response_cache
from .models import (
    AuraBand,
    AuraUptime,
    CancelledCastSummary,
    CharacterHistory,
    ConsumableUsage,
    DPSPerformance,
    EncounterPerformance,
    EncounterSummary,
    HealerPerformance,
    InterruptUsage,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidGroup,
    RaidMetadata,
    SpellUsage,
    TankPerformance,
)
from .spell_manager import get_spell_manager

SCHEMA_VERSION = 2


def _resolve_name(spell_id: int, stored_name: str) -> str:
    if stored_name.startswith("(ID "):
        resolved = get_spell_manager().get_spell_name(spell_id)
        if not resolved.startswith("(ID "):
            return resolved
    return stored_name


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    player_class TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    owner TEXT,
    raid_date TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    end_time INTEGER,
    imported_at TEXT NOT NULL DEFAULT (datetime('now')),
    source TEXT NOT NULL DEFAULT 'guild',
    label TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS healer_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    raid_id INTEGER NOT NULL REFERENCES raids(id),
    total_healing INTEGER NOT NULL DEFAULT 0,
    total_overhealing INTEGER NOT NULL DEFAULT 0,
    overheal_percent REAL NOT NULL DEFAULT 0.0,
    fear_ward_casts INTEGER NOT NULL DEFAULT 0,
    total_dispels INTEGER NOT NULL DEFAULT 0,
    UNIQUE(character_id, raid_id)
);

CREATE TABLE IF NOT EXISTS healer_spells (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    healer_performance_id INTEGER NOT NULL REFERENCES healer_performance(id) ON DELETE CASCADE,
    spell_id INTEGER NOT NULL,
    spell_name TEXT NOT NULL,
    casts INTEGER NOT NULL DEFAULT 0,
    total_healing INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tank_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    raid_id INTEGER NOT NULL REFERENCES raids(id),
    total_damage_taken INTEGER NOT NULL DEFAULT 0,
    total_mitigated INTEGER NOT NULL DEFAULT 0,
    mitigation_percent REAL NOT NULL DEFAULT 0.0,
    UNIQUE(character_id, raid_id)
);

CREATE TABLE IF NOT EXISTS tank_damage_taken (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tank_performance_id INTEGER NOT NULL REFERENCES tank_performance(id) ON DELETE CASCADE,
    spell_id INTEGER NOT NULL,
    spell_name TEXT NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tank_abilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tank_performance_id INTEGER NOT NULL REFERENCES tank_performance(id) ON DELETE CASCADE,
    spell_id INTEGER NOT NULL,
    spell_name TEXT NOT NULL,
    casts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dps_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    raid_id INTEGER NOT NULL REFERENCES raids(id),
    role TEXT NOT NULL CHECK(role IN ('melee', 'ranged')),
    total_damage INTEGER NOT NULL DEFAULT 0,
    UNIQUE(character_id, raid_id)
);

CREATE TABLE IF NOT EXISTS dps_abilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dps_performance_id INTEGER NOT NULL REFERENCES dps_performance(id) ON DELETE CASCADE,
    spell_id INTEGER NOT NULL,
    spell_name TEXT NOT NULL,
    casts INTEGER NOT NULL DEFAULT 0,
    total_damage INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS consumable_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    raid_id INTEGER NOT NULL REFERENCES raids(id),
    consumable_name TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    timestamps TEXT DEFAULT NULL,
    UNIQUE(character_id, raid_id, consumable_name)
);

CREATE INDEX IF NOT EXISTS idx_healer_perf_char ON healer_performance(character_id);
CREATE INDEX IF NOT EXISTS idx_healer_perf_raid ON healer_performance(raid_id);
CREATE INDEX IF NOT EXISTS idx_tank_perf_char ON tank_performance(character_id);
CREATE INDEX IF NOT EXISTS idx_tank_perf_raid ON tank_performance(raid_id);
CREATE INDEX IF NOT EXISTS idx_dps_perf_char ON dps_performance(character_id);
CREATE INDEX IF NOT EXISTS idx_dps_perf_raid ON dps_performance(raid_id);
CREATE INDEX IF NOT EXISTS idx_consumable_char ON consumable_usage(character_id);
CREATE INDEX IF NOT EXISTS idx_consumable_raid ON consumable_usage(raid_id);
CREATE INDEX IF NOT EXISTS idx_raids_date ON raids(raid_date);

CREATE INDEX IF NOT EXISTS idx_healer_spells_perf ON healer_spells(healer_performance_id);
CREATE INDEX IF NOT EXISTS idx_tank_dt_perf ON tank_damage_taken(tank_performance_id);
CREATE INDEX IF NOT EXISTS idx_tank_ab_perf ON tank_abilities(tank_performance_id);
CREATE INDEX IF NOT EXISTS idx_dps_ab_perf ON dps_abilities(dps_performance_id);

CREATE TABLE IF NOT EXISTS raid_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    raid_days TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS raid_group_members (
    group_id INTEGER NOT NULL REFERENCES raid_groups(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    UNIQUE(group_id, character_id)
);

CREATE INDEX IF NOT EXISTS idx_rgm_group ON raid_group_members(group_id);
CREATE INDEX IF NOT EXISTS idx_rgm_char ON raid_group_members(character_id);

CREATE TABLE IF NOT EXISTS encounters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raid_id INTEGER NOT NULL REFERENCES raids(id) ON DELETE CASCADE,
    encounter_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    UNIQUE(raid_id, encounter_id, start_time)
);

CREATE TABLE IF NOT EXISTS encounter_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_row_id INTEGER NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    role TEXT CHECK(role IN ('healer', 'tank', 'melee', 'ranged', 'unknown')),
    total_damage INTEGER DEFAULT 0,
    total_healing INTEGER DEFAULT 0,
    total_damage_taken INTEGER DEFAULT 0,
    UNIQUE(encounter_row_id, character_id)
);

CREATE INDEX IF NOT EXISTS idx_encounter_raid ON encounters(raid_id);
CREATE INDEX IF NOT EXISTS idx_encounter_perf_enc ON encounter_performance(encounter_row_id);
CREATE INDEX IF NOT EXISTS idx_encounter_perf_char ON encounter_performance(character_id);
"""


class PerformanceDB:
    """SQLite database for storing and querying historical character performance."""

    def __init__(self, db_path: str | None = None):
        from . import paths

        self.db_path = db_path or str(paths.get_db_path())
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def initialize(self) -> None:
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        cursor = conn.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        self._migrate(conn)
        conn.commit()

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(consumable_usage)").fetchall()}
        if "timestamps" not in cols:
            conn.execute("ALTER TABLE consumable_usage ADD COLUMN timestamps TEXT DEFAULT NULL")

        raid_cols = {row[1] for row in conn.execute("PRAGMA table_info(raids)").fetchall()}
        if "raid_size" not in raid_cols:
            conn.execute("ALTER TABLE raids ADD COLUMN raid_size INTEGER DEFAULT NULL")
        if "zone" not in raid_cols:
            conn.execute("ALTER TABLE raids ADD COLUMN zone TEXT DEFAULT NULL")
        if "source" not in raid_cols:
            conn.execute("ALTER TABLE raids ADD COLUMN source TEXT DEFAULT 'guild'")
        if "label" not in raid_cols:
            conn.execute("ALTER TABLE raids ADD COLUMN label TEXT DEFAULT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_raids_source ON raids(source)")

        conn.execute("""
            UPDATE raids SET raid_size = (
                SELECT COUNT(DISTINCT character_id) FROM (
                    SELECT character_id FROM healer_performance WHERE raid_id = raids.id
                    UNION
                    SELECT character_id FROM tank_performance WHERE raid_id = raids.id
                    UNION
                    SELECT character_id FROM dps_performance WHERE raid_id = raids.id
                )
            ) WHERE raid_size IS NULL
        """)

        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "raid_groups" not in tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS raid_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    raid_days TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS raid_group_members (
                    group_id INTEGER NOT NULL REFERENCES raid_groups(id) ON DELETE CASCADE,
                    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                    UNIQUE(group_id, character_id)
                );
                CREATE INDEX IF NOT EXISTS idx_rgm_group ON raid_group_members(group_id);
                CREATE INDEX IF NOT EXISTS idx_rgm_char ON raid_group_members(character_id);
            """)

        if "encounters" not in tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS encounters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    raid_id INTEGER NOT NULL REFERENCES raids(id) ON DELETE CASCADE,
                    encounter_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    start_time INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    UNIQUE(raid_id, encounter_id, start_time)
                );
                CREATE TABLE IF NOT EXISTS encounter_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    encounter_row_id INTEGER NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
                    character_id INTEGER NOT NULL REFERENCES characters(id),
                    role TEXT CHECK(role IN ('healer', 'tank', 'melee', 'ranged', 'unknown')),
                    total_damage INTEGER DEFAULT 0,
                    total_healing INTEGER DEFAULT 0,
                    total_damage_taken INTEGER DEFAULT 0,
                    UNIQUE(encounter_row_id, character_id)
                );
                CREATE INDEX IF NOT EXISTS idx_encounter_raid ON encounters(raid_id);
                CREATE INDEX IF NOT EXISTS idx_encounter_perf_enc ON encounter_performance(encounter_row_id);
                CREATE INDEX IF NOT EXISTS idx_encounter_perf_char ON encounter_performance(character_id);
            """)

        for table in ("healer_performance", "tank_performance", "dps_performance", "encounter_performance"):
            t_cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "active_time_percent" not in t_cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN active_time_percent REAL DEFAULT 0.0")

        if "interrupt_usage" not in tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS interrupt_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    character_id INTEGER NOT NULL REFERENCES characters(id),
                    raid_id INTEGER NOT NULL REFERENCES raids(id),
                    spell_id INTEGER NOT NULL,
                    spell_name TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    timestamps TEXT DEFAULT NULL,
                    UNIQUE(character_id, raid_id, spell_id)
                );
                CREATE INDEX IF NOT EXISTS idx_interrupt_char ON interrupt_usage(character_id);
                CREATE INDEX IF NOT EXISTS idx_interrupt_raid ON interrupt_usage(raid_id);
            """)

        if "aura_uptime" not in tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS aura_uptime (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    raid_id INTEGER NOT NULL REFERENCES raids(id) ON DELETE CASCADE,
                    encounter_row_id INTEGER NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
                    spell_id INTEGER NOT NULL,
                    spell_name TEXT NOT NULL,
                    uptime_percent REAL NOT NULL DEFAULT 0.0,
                    bands_json TEXT DEFAULT NULL,
                    UNIQUE(raid_id, encounter_row_id, spell_id)
                );
                CREATE INDEX IF NOT EXISTS idx_aura_raid ON aura_uptime(raid_id);
                CREATE INDEX IF NOT EXISTS idx_aura_enc ON aura_uptime(encounter_row_id);
            """)

        if "totem_uptime" not in tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS totem_uptime (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    raid_id INTEGER NOT NULL REFERENCES raids(id) ON DELETE CASCADE,
                    encounter_row_id INTEGER NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
                    spell_id INTEGER NOT NULL,
                    spell_name TEXT NOT NULL,
                    uptime_percent REAL NOT NULL DEFAULT 0.0,
                    bands_json TEXT DEFAULT NULL,
                    UNIQUE(raid_id, encounter_row_id, spell_id)
                );
                CREATE INDEX IF NOT EXISTS idx_totem_raid ON totem_uptime(raid_id);
                CREATE INDEX IF NOT EXISTS idx_totem_enc ON totem_uptime(encounter_row_id);
            """)

        if "cancelled_casts" not in tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS cancelled_casts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    character_id INTEGER NOT NULL REFERENCES characters(id),
                    raid_id INTEGER NOT NULL REFERENCES raids(id),
                    total_casts INTEGER NOT NULL DEFAULT 0,
                    cancelled_casts INTEGER NOT NULL DEFAULT 0,
                    cancel_rate REAL NOT NULL DEFAULT 0.0,
                    UNIQUE(character_id, raid_id)
                );
                CREATE INDEX IF NOT EXISTS idx_cc_char ON cancelled_casts(character_id);
                CREATE INDEX IF NOT EXISTS idx_cc_raid ON cancelled_casts(raid_id);
            """)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        self.close()
        return False

    # ── Character operations ──

    def _upsert_character(self, name: str, player_class: str, raid_date: str) -> int:
        conn = self._get_conn()
        # Check for existing character with case-insensitive match
        existing = conn.execute(
            "SELECT id, name FROM characters WHERE name = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE characters SET
                       player_class = ?,
                       last_seen = MAX(last_seen, ?)
                   WHERE id = ?""",
                (player_class, raid_date, existing["id"]),
            )
            return existing["id"]
        conn.execute(
            """INSERT INTO characters (name, player_class, first_seen, last_seen)
               VALUES (?, ?, ?, ?)""",
            (name, player_class, raid_date, raid_date),
        )
        cursor = conn.execute("SELECT id FROM characters WHERE name = ? COLLATE NOCASE", (name,))
        return cursor.fetchone()["id"]

    def _upsert_raid(self, metadata: RaidMetadata, source: str = "guild") -> int:
        conn = self._get_conn()
        raid_date = metadata.date.strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO raids (report_id, title, owner, raid_date, start_time, end_time, zone, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(report_id) DO UPDATE SET
                   title = excluded.title,
                   zone = COALESCE(excluded.zone, raids.zone),
                   imported_at = datetime('now')""",
            (
                metadata.report_id,
                metadata.title,
                metadata.owner,
                raid_date,
                metadata.start_time,
                metadata.end_time,
                metadata.zone,
                source,
            ),
        )
        cursor = conn.execute("SELECT id FROM raids WHERE report_id = ?", (metadata.report_id,))
        return cursor.fetchone()["id"]

    # ── Import a full raid analysis ──

    def import_raid(self, analysis: RaidAnalysis, source: str = "guild") -> None:
        """Import all performance data from a completed raid analysis."""
        conn = self._get_conn()
        raid_date = analysis.metadata.date.strftime("%Y-%m-%d %H:%M:%S")
        raid_id = self._upsert_raid(analysis.metadata, source=source)

        raid_size = len(analysis.composition.all_players)
        if raid_size > 0:
            conn.execute("UPDATE raids SET raid_size = ? WHERE id = ?", (raid_size, raid_id))

        for healer in analysis.healers:
            char_id = self._upsert_character(healer.name, healer.player_class, raid_date)
            self._import_healer(conn, char_id, raid_id, healer)

        for tank in analysis.tanks:
            char_id = self._upsert_character(tank.name, tank.player_class, raid_date)
            self._import_tank(conn, char_id, raid_id, tank)

        for dps in analysis.dps:
            char_id = self._upsert_character(dps.name, dps.player_class, raid_date)
            self._import_dps(conn, char_id, raid_id, dps)

        for cu in analysis.consumables:
            player = analysis.composition.get_player(cu.player_name)
            player_class = player.player_class if player else "Unknown"
            char_id = self._upsert_character(cu.player_name, player_class, raid_date)
            ts_json = json.dumps(cu.timestamps) if cu.timestamps else None
            conn.execute(
                """INSERT INTO consumable_usage (character_id, raid_id, consumable_name, count, timestamps)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(character_id, raid_id, consumable_name) DO UPDATE SET
                       count = excluded.count, timestamps = excluded.timestamps""",
                (char_id, raid_id, cu.consumable_name, cu.count, ts_json),
            )

        for iu in analysis.interrupts:
            char_id = self._upsert_character(iu.player_name, iu.player_class, raid_date)
            ts_json = json.dumps(iu.timestamps) if iu.timestamps else None
            conn.execute(
                """INSERT INTO interrupt_usage
                   (character_id, raid_id, spell_id, spell_name, count, timestamps)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(character_id, raid_id, spell_id) DO UPDATE SET
                       spell_name = excluded.spell_name,
                       count = excluded.count,
                       timestamps = excluded.timestamps""",
                (char_id, raid_id, iu.spell_id, iu.spell_name, iu.count, ts_json),
            )

        for cc in analysis.cancelled_casts:
            char_id = self._upsert_character(cc.player_name, cc.player_class, raid_date)
            conn.execute(
                """INSERT INTO cancelled_casts
                   (character_id, raid_id, total_casts, cancelled_casts, cancel_rate)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(character_id, raid_id) DO UPDATE SET
                       total_casts = excluded.total_casts,
                       cancelled_casts = excluded.cancelled_casts,
                       cancel_rate = excluded.cancel_rate""",
                (char_id, raid_id, cc.total_casts, cc.cancelled_casts, cc.cancel_rate),
            )

        if analysis.encounters:
            self._import_encounters(conn, raid_id, raid_date, analysis.encounters)

        if analysis.aura_uptimes:
            self._import_aura_uptimes(conn, raid_id, analysis.aura_uptimes)

        if analysis.totem_uptimes:
            self._import_totem_uptimes(conn, raid_id, analysis.totem_uptimes)

        conn.commit()

    def _import_encounters(
        self, conn: sqlite3.Connection, raid_id: int, raid_date: str, encounters: list[EncounterSummary]
    ) -> None:
        conn.execute(
            "DELETE FROM encounter_performance WHERE encounter_row_id IN (SELECT id FROM encounters WHERE raid_id = ?)",
            (raid_id,),
        )
        conn.execute("DELETE FROM encounters WHERE raid_id = ?", (raid_id,))

        for enc in encounters:
            conn.execute(
                """INSERT INTO encounters
                   (raid_id, encounter_id, name, start_time, end_time, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (raid_id, enc.encounter_id, enc.name, enc.start_time, enc.end_time, enc.duration_ms),
            )
            enc_row_id = conn.execute(
                "SELECT id FROM encounters WHERE raid_id = ? AND encounter_id = ? AND start_time = ?",
                (raid_id, enc.encounter_id, enc.start_time),
            ).fetchone()["id"]

            for player in enc.players:
                char_id = self._upsert_character(player.name, player.player_class, raid_date)
                conn.execute(
                    """INSERT INTO encounter_performance
                       (encounter_row_id, character_id, role, total_damage, total_healing,
                        total_damage_taken, active_time_percent)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(encounter_row_id, character_id) DO UPDATE SET
                           role = excluded.role,
                           total_damage = excluded.total_damage,
                           total_healing = excluded.total_healing,
                           total_damage_taken = excluded.total_damage_taken,
                           active_time_percent = excluded.active_time_percent""",
                    (
                        enc_row_id,
                        char_id,
                        player.role,
                        player.total_damage,
                        player.total_healing,
                        player.total_damage_taken,
                        player.active_time_percent,
                    ),
                )

    def _import_aura_uptimes(
        self, conn: sqlite3.Connection, raid_id: int, aura_uptimes: list[AuraUptime]
    ) -> None:
        conn.execute("DELETE FROM aura_uptime WHERE raid_id = ?", (raid_id,))
        for au in aura_uptimes:
            enc_row = conn.execute(
                "SELECT id FROM encounters WHERE raid_id = ? AND start_time = ?",
                (raid_id, au.fight_start),
            ).fetchone()
            if not enc_row:
                continue

            bands_json = json.dumps(
                [{"start": b.start_time, "end": b.end_time} for b in au.bands]
            ) if au.bands else None

            conn.execute(
                """INSERT INTO aura_uptime
                   (raid_id, encounter_row_id, spell_id, spell_name, uptime_percent, bands_json)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(raid_id, encounter_row_id, spell_id) DO UPDATE SET
                       spell_name = excluded.spell_name,
                       uptime_percent = excluded.uptime_percent,
                       bands_json = excluded.bands_json""",
                (raid_id, enc_row["id"], au.spell_id, au.spell_name, au.uptime_percent, bands_json),
            )

    def _import_totem_uptimes(
        self, conn: sqlite3.Connection, raid_id: int, totem_uptimes: list[AuraUptime]
    ) -> None:
        conn.execute("DELETE FROM totem_uptime WHERE raid_id = ?", (raid_id,))
        for tu in totem_uptimes:
            enc_row = conn.execute(
                "SELECT id FROM encounters WHERE raid_id = ? AND start_time = ?",
                (raid_id, tu.fight_start),
            ).fetchone()
            if not enc_row:
                continue

            bands_json = json.dumps(
                [{"start": b.start_time, "end": b.end_time} for b in tu.bands]
            ) if tu.bands else None

            conn.execute(
                """INSERT INTO totem_uptime
                   (raid_id, encounter_row_id, spell_id, spell_name, uptime_percent, bands_json)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(raid_id, encounter_row_id, spell_id) DO UPDATE SET
                       spell_name = excluded.spell_name,
                       uptime_percent = excluded.uptime_percent,
                       bands_json = excluded.bands_json""",
                (raid_id, enc_row["id"], tu.spell_id, tu.spell_name, tu.uptime_percent, bands_json),
            )

    def _import_healer(self, conn: sqlite3.Connection, char_id: int, raid_id: int, h: HealerPerformance) -> None:
        total_dispels = sum(d.casts for d in h.dispels)
        conn.execute(
            """INSERT INTO healer_performance
               (character_id, raid_id, total_healing, total_overhealing, overheal_percent,
                fear_ward_casts, total_dispels, active_time_percent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(character_id, raid_id) DO UPDATE SET
                   total_healing = excluded.total_healing,
                   total_overhealing = excluded.total_overhealing,
                   overheal_percent = excluded.overheal_percent,
                   fear_ward_casts = excluded.fear_ward_casts,
                   total_dispels = excluded.total_dispels,
                   active_time_percent = excluded.active_time_percent""",
            (
                char_id,
                raid_id,
                h.total_healing,
                h.total_overhealing,
                h.overheal_percent,
                h.fear_ward_casts,
                total_dispels,
                h.active_time_percent,
            ),
        )
        perf_id = conn.execute(
            "SELECT id FROM healer_performance WHERE character_id = ? AND raid_id = ?",
            (char_id, raid_id),
        ).fetchone()["id"]

        conn.execute("DELETE FROM healer_spells WHERE healer_performance_id = ?", (perf_id,))
        for spell in h.spells:
            conn.execute(
                """INSERT INTO healer_spells (healer_performance_id, spell_id, spell_name, casts, total_healing)
                   VALUES (?, ?, ?, ?, ?)""",
                (perf_id, spell.spell_id, spell.spell_name, spell.casts, spell.total_amount),
            )

    def _import_tank(self, conn: sqlite3.Connection, char_id: int, raid_id: int, t: TankPerformance) -> None:
        conn.execute(
            """INSERT INTO tank_performance
               (character_id, raid_id, total_damage_taken, total_mitigated, mitigation_percent,
                active_time_percent)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(character_id, raid_id) DO UPDATE SET
                   total_damage_taken = excluded.total_damage_taken,
                   total_mitigated = excluded.total_mitigated,
                   mitigation_percent = excluded.mitigation_percent,
                   active_time_percent = excluded.active_time_percent""",
            (char_id, raid_id, t.total_damage_taken, t.total_mitigated, t.mitigation_percent, t.active_time_percent),
        )
        perf_id = conn.execute(
            "SELECT id FROM tank_performance WHERE character_id = ? AND raid_id = ?",
            (char_id, raid_id),
        ).fetchone()["id"]

        conn.execute("DELETE FROM tank_damage_taken WHERE tank_performance_id = ?", (perf_id,))
        for s in t.damage_taken_breakdown:
            conn.execute(
                """INSERT INTO tank_damage_taken (tank_performance_id, spell_id, spell_name, hits)
                   VALUES (?, ?, ?, ?)""",
                (perf_id, s.spell_id, s.spell_name, s.casts),
            )

        conn.execute("DELETE FROM tank_abilities WHERE tank_performance_id = ?", (perf_id,))
        for s in t.abilities_used:
            conn.execute(
                """INSERT INTO tank_abilities (tank_performance_id, spell_id, spell_name, casts)
                   VALUES (?, ?, ?, ?)""",
                (perf_id, s.spell_id, s.spell_name, s.casts),
            )

    def _import_dps(self, conn: sqlite3.Connection, char_id: int, raid_id: int, d: DPSPerformance) -> None:
        conn.execute(
            """INSERT INTO dps_performance
               (character_id, raid_id, role, total_damage, active_time_percent)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(character_id, raid_id) DO UPDATE SET
                   role = excluded.role,
                   total_damage = excluded.total_damage,
                   active_time_percent = excluded.active_time_percent""",
            (char_id, raid_id, d.role, d.total_damage, d.active_time_percent),
        )
        perf_id = conn.execute(
            "SELECT id FROM dps_performance WHERE character_id = ? AND raid_id = ?",
            (char_id, raid_id),
        ).fetchone()["id"]

        conn.execute("DELETE FROM dps_abilities WHERE dps_performance_id = ?", (perf_id,))
        for ability in d.abilities:
            conn.execute(
                """INSERT INTO dps_abilities (dps_performance_id, spell_id, spell_name, casts, total_damage)
                   VALUES (?, ?, ?, ?, ?)""",
                (perf_id, ability.spell_id, ability.spell_name, ability.casts, ability.total_amount),
            )

    def import_consumables(self, metadata: RaidMetadata, usage_list: list[ConsumableUsage]) -> None:
        """Import consumable usage data for a raid."""
        conn = self._get_conn()
        raid_date = metadata.date.strftime("%Y-%m-%d %H:%M:%S")
        raid_id = self._upsert_raid(metadata)

        for usage in usage_list:
            char_id = self._upsert_character(usage.player_name, "Unknown", raid_date)
            ts_json = json.dumps(usage.timestamps) if usage.timestamps else None
            conn.execute(
                """INSERT INTO consumable_usage (character_id, raid_id, consumable_name, count, timestamps)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(character_id, raid_id, consumable_name) DO UPDATE SET
                       count = excluded.count, timestamps = excluded.timestamps""",
                (char_id, raid_id, usage.consumable_name, usage.count, ts_json),
            )

        conn.commit()

    # ── Query operations ──

    def get_character_history(self, character_name: str, source: str = "guild") -> CharacterHistory | None:
        """Get historical performance summary for a character."""
        conn = self._get_conn()
        char = conn.execute(
            "SELECT * FROM characters WHERE name = ? COLLATE NOCASE",
            (character_name,),
        ).fetchone()
        if not char:
            return None

        char_id = char["id"]

        raid_count = conn.execute(
            """SELECT COUNT(DISTINCT raid_id) as cnt FROM (
                SELECT hp.raid_id FROM healer_performance hp
                    JOIN raids r ON r.id = hp.raid_id
                    WHERE hp.character_id = ? AND r.source = ?
                UNION SELECT tp.raid_id FROM tank_performance tp
                    JOIN raids r ON r.id = tp.raid_id
                    WHERE tp.character_id = ? AND r.source = ?
                UNION SELECT dp.raid_id FROM dps_performance dp
                    JOIN raids r ON r.id = dp.raid_id
                    WHERE dp.character_id = ? AND r.source = ?
            )""",
            (char_id, source, char_id, source, char_id, source),
        ).fetchone()["cnt"]

        avg_healing = conn.execute(
            """SELECT AVG(hp.total_healing) as avg FROM healer_performance hp
               JOIN raids r ON r.id = hp.raid_id
               WHERE hp.character_id = ? AND r.source = ?""",
            (char_id, source),
        ).fetchone()["avg"]

        avg_damage = conn.execute(
            """SELECT AVG(dp.total_damage) as avg FROM dps_performance dp
               JOIN raids r ON r.id = dp.raid_id
               WHERE dp.character_id = ? AND r.source = ?""",
            (char_id, source),
        ).fetchone()["avg"]

        avg_mit = conn.execute(
            """SELECT AVG(tp.mitigation_percent) as avg FROM tank_performance tp
               JOIN raids r ON r.id = tp.raid_id
               WHERE tp.character_id = ? AND r.source = ?""",
            (char_id, source),
        ).fetchone()["avg"]

        total_consumes = conn.execute(
            """SELECT COALESCE(SUM(cu.count), 0) as total FROM consumable_usage cu
               JOIN raids r ON r.id = cu.raid_id
               WHERE cu.character_id = ? AND r.source = ?""",
            (char_id, source),
        ).fetchone()["total"]

        avg_at = conn.execute(
            """SELECT AVG(active_time_percent) as avg FROM (
                SELECT hp.active_time_percent FROM healer_performance hp
                    JOIN raids r ON r.id = hp.raid_id
                    WHERE hp.character_id = ? AND r.source = ? AND hp.active_time_percent > 0
                UNION ALL
                SELECT tp.active_time_percent FROM tank_performance tp
                    JOIN raids r ON r.id = tp.raid_id
                    WHERE tp.character_id = ? AND r.source = ? AND tp.active_time_percent > 0
                UNION ALL
                SELECT dp.active_time_percent FROM dps_performance dp
                    JOIN raids r ON r.id = dp.raid_id
                    WHERE dp.character_id = ? AND r.source = ? AND dp.active_time_percent > 0
            )""",
            (char_id, source, char_id, source, char_id, source),
        ).fetchone()["avg"]

        return CharacterHistory(
            name=char["name"],
            player_class=char["player_class"],
            total_raids=raid_count,
            first_seen=datetime.fromisoformat(char["first_seen"]),
            last_seen=datetime.fromisoformat(char["last_seen"]),
            avg_healing=round(avg_healing, 1) if avg_healing else None,
            avg_damage=round(avg_damage, 1) if avg_damage else None,
            avg_mitigation_percent=round(avg_mit, 2) if avg_mit else None,
            total_consumables_used=total_consumes,
            avg_active_time=round(avg_at, 1) if avg_at else None,
        )

    def get_all_characters(self) -> list[CharacterHistory]:
        """Get summary for all tracked characters (guild raids only)."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT DISTINCT c.name FROM characters c
            WHERE EXISTS (
                SELECT 1 FROM healer_performance hp
                JOIN raids r ON r.id = hp.raid_id
                WHERE hp.character_id = c.id AND r.source = 'guild'
            ) OR EXISTS (
                SELECT 1 FROM tank_performance tp
                JOIN raids r ON r.id = tp.raid_id
                WHERE tp.character_id = c.id AND r.source = 'guild'
            ) OR EXISTS (
                SELECT 1 FROM dps_performance dp
                JOIN raids r ON r.id = dp.raid_id
                WHERE dp.character_id = c.id AND r.source = 'guild'
            )
            ORDER BY c.name
        """).fetchall()
        results = []
        for row in rows:
            history = self.get_character_history(row["name"])
            if history:
                results.append(history)
        return results

    def get_healer_trend(self, character_name: str, limit: int = 20) -> list[dict]:
        """Get healing performance over time for a character."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.title, r.report_id, r.raid_size, r.zone,
                      hp.total_healing, hp.total_overhealing, hp.overheal_percent,
                      hp.fear_ward_casts, hp.total_dispels, hp.active_time_percent
               FROM healer_performance hp
               JOIN characters c ON c.id = hp.character_id
               JOIN raids r ON r.id = hp.raid_id
               WHERE c.name = ? COLLATE NOCASE AND r.source = 'guild'
               ORDER BY r.raid_date DESC
               LIMIT ?""",
            (character_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_tank_trend(self, character_name: str, limit: int = 20) -> list[dict]:
        """Get tank performance over time for a character."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.title, r.report_id, r.raid_size, r.zone,
                      tp.total_damage_taken, tp.total_mitigated, tp.mitigation_percent,
                      tp.active_time_percent
               FROM tank_performance tp
               JOIN characters c ON c.id = tp.character_id
               JOIN raids r ON r.id = tp.raid_id
               WHERE c.name = ? COLLATE NOCASE AND r.source = 'guild'
               ORDER BY r.raid_date DESC
               LIMIT ?""",
            (character_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dps_trend(self, character_name: str, limit: int = 20) -> list[dict]:
        """Get DPS performance over time for a character."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.title, r.report_id, r.raid_size, r.zone,
                      dp.role, dp.total_damage, dp.active_time_percent
               FROM dps_performance dp
               JOIN characters c ON c.id = dp.character_id
               JOIN raids r ON r.id = dp.raid_id
               WHERE c.name = ? COLLATE NOCASE AND r.source = 'guild'
               ORDER BY r.raid_date DESC
               LIMIT ?""",
            (character_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_healer_spell_trend(self, character_name: str, limit: int = 20) -> list[dict]:
        """Get per-spell healing data across raids for a character."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.title, r.report_id, r.raid_size, r.zone,
                      hs.spell_name, hs.casts, hs.total_healing
               FROM healer_spells hs
               JOIN healer_performance hp ON hp.id = hs.healer_performance_id
               JOIN characters c ON c.id = hp.character_id
               JOIN raids r ON r.id = hp.raid_id
               WHERE c.name = ? COLLATE NOCASE AND r.source = 'guild'
               ORDER BY r.raid_date DESC
               LIMIT ?""",
            (character_name, limit * 20),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dps_ability_trend(self, character_name: str, limit: int = 20) -> list[dict]:
        """Get per-ability damage data across raids for a character."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.title, r.report_id, r.raid_size, r.zone,
                      da.spell_name, da.casts, da.total_damage
               FROM dps_abilities da
               JOIN dps_performance dp ON dp.id = da.dps_performance_id
               JOIN characters c ON c.id = dp.character_id
               JOIN raids r ON r.id = dp.raid_id
               WHERE c.name = ? COLLATE NOCASE AND r.source = 'guild'
               ORDER BY r.raid_date DESC
               LIMIT ?""",
            (character_name, limit * 20),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_consumable_trend(self, character_name: str, limit: int = 20) -> list[dict]:
        """Get consumable usage over time for a character (all rows, for charting)."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.title, r.report_id, r.raid_size, r.zone,
                      cu.consumable_name, cu.count
               FROM consumable_usage cu
               JOIN characters c ON c.id = cu.character_id
               JOIN raids r ON r.id = cu.raid_id
               WHERE c.name = ? COLLATE NOCASE AND r.source = 'guild'
               ORDER BY r.raid_date DESC
               LIMIT ?""",
            (character_name, limit * 10),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_consumable_summary(self, character_name: str, limit: int = 5) -> list[dict]:
        """Get consumable usage pivoted by raid (last N raids) for table display."""
        conn = self._get_conn()
        raids = conn.execute(
            """SELECT DISTINCT r.raid_date, r.title, r.report_id, r.id as raid_id
               FROM consumable_usage cu
               JOIN characters c ON c.id = cu.character_id
               JOIN raids r ON r.id = cu.raid_id
               WHERE c.name = ? COLLATE NOCASE AND r.source = 'guild'
               ORDER BY r.raid_date DESC
               LIMIT ?""",
            (character_name, limit),
        ).fetchall()

        results = []
        for raid in raids:
            row = {"raid_date": raid["raid_date"], "title": raid["title"], "report_id": raid["report_id"]}
            items = conn.execute(
                """SELECT cu.consumable_name, cu.count, cu.timestamps
                   FROM consumable_usage cu
                   JOIN characters c ON c.id = cu.character_id
                   WHERE c.name = ? COLLATE NOCASE AND cu.raid_id = ?""",
                (character_name, raid["raid_id"]),
            ).fetchall()
            for item in items:
                row[item["consumable_name"]] = item["count"]
                if item["timestamps"]:
                    ts_list = json.loads(item["timestamps"])
                    parts = [datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S") for ms in ts_list]
                    row[f"{item['consumable_name']} times"] = ", ".join(parts)
            results.append(row)
        return results

    # ── Insights queries ──

    def _build_day_size_filter(
        self,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
        source: str = "guild",
    ) -> tuple[str, list]:
        def _core(alias: str) -> tuple[str, list]:
            frag = f" AND {alias}.source = ?"
            p: list = [source]
            if raid_day:
                day_map = {
                    "Monday": "1",
                    "Tuesday": "2",
                    "Wednesday": "3",
                    "Thursday": "4",
                    "Friday": "5",
                    "Saturday": "6",
                    "Sunday": "0",
                }
                days = [d.strip() for d in raid_day.split(",")]
                day_nums = [int(day_map[d]) for d in days if d in day_map]
                if day_nums:
                    placeholders = ",".join("?" * len(day_nums))
                    frag += f" AND CAST(strftime('%w', {alias}.raid_date) AS INTEGER) IN ({placeholders})"
                    p.extend(day_nums)
            if raid_size == "25-man":
                frag += f" AND {alias}.raid_size >= 20"
            elif raid_size == "10-man":
                frag += f" AND {alias}.raid_size BETWEEN 1 AND 19"
            if zone:
                frag += f" AND {alias}.zone = ?"
                p.append(zone)
            return frag, p

        sql, params = _core("r")
        if last_n:
            inner_sql, inner_params = _core("r2")
            sql += f" AND r.id IN (SELECT r2.id FROM raids r2 WHERE 1=1{inner_sql} ORDER BY r2.raid_date DESC LIMIT ?)"
            params.extend(inner_params)
            params.append(last_n)
        return sql, params

    def get_dps_progression(
        self,
        top_n: int = 10,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> list[dict]:
        """Per-raid damage for top N DPS characters by average."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)
        top_chars = conn.execute(
            f"""SELECT dp.character_id
               FROM dps_performance dp
               JOIN raids r ON r.id = dp.raid_id
               WHERE 1=1{ds_filter}
               GROUP BY dp.character_id
               HAVING COUNT(*) >= 3
               ORDER BY AVG(dp.total_damage) DESC
               LIMIT ?""",
            [*ds_params, top_n],
        ).fetchall()
        if not top_chars:
            return []
        ids = [r["character_id"] for r in top_chars]
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"""SELECT c.name, c.player_class, r.raid_date, dp.total_damage
                FROM dps_performance dp
                JOIN characters c ON c.id = dp.character_id
                JOIN raids r ON r.id = dp.raid_id
                WHERE dp.character_id IN ({placeholders}){ds_filter}
                ORDER BY r.raid_date ASC""",
            ids + ds_params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dps_consistency(
        self,
        min_raids: int = 3,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> list[dict]:
        """Consistency scores for DPS characters (100 - CV%)."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)
        rows = conn.execute(
            f"""SELECT c.name, c.player_class, dp.total_damage
               FROM dps_performance dp
               JOIN characters c ON c.id = dp.character_id
               JOIN raids r ON r.id = dp.raid_id
               WHERE 1=1{ds_filter}
               ORDER BY c.name""",
            ds_params,
        ).fetchall()
        import math
        from collections import defaultdict

        by_char: dict[str, dict] = {}
        values_by_char: dict[str, list[int]] = defaultdict(list)
        for r in rows:
            name = r["name"]
            if name not in by_char:
                by_char[name] = {"name": name, "player_class": r["player_class"]}
            values_by_char[name].append(r["total_damage"])
        results = []
        for name, info in by_char.items():
            vals = values_by_char[name]
            if len(vals) < min_raids:
                continue
            avg = sum(vals) / len(vals)
            if avg == 0:
                continue
            variance = sum((v - avg) ** 2 for v in vals) / len(vals)
            std = math.sqrt(variance)
            cv = std / avg * 100
            results.append(
                {
                    **info,
                    "raids": len(vals),
                    "avg_damage": avg,
                    "consistency": round(100 - cv, 1),
                }
            )
        results.sort(key=lambda x: x["consistency"], reverse=True)
        return results

    def get_raid_overview_trends(
        self,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> list[dict]:
        """Per-raid aggregates: duration, healing, damage, ratio."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)
        rows = conn.execute(
            f"""SELECT r.raid_date, r.title, r.raid_size,
                      r.start_time, r.end_time,
                      COALESCE(h.total_healing, 0) as total_healing,
                      COALESCE(d.total_damage, 0) as total_damage
               FROM raids r
               LEFT JOIN (
                   SELECT raid_id, SUM(total_healing) as total_healing
                   FROM healer_performance GROUP BY raid_id
               ) h ON h.raid_id = r.id
               LEFT JOIN (
                   SELECT raid_id, SUM(total_damage) as total_damage
                   FROM dps_performance GROUP BY raid_id
               ) d ON d.raid_id = r.id
               WHERE r.end_time IS NOT NULL AND r.end_time > r.start_time{ds_filter}
               ORDER BY r.raid_date ASC""",
            ds_params,
        ).fetchall()
        results = []
        for r in rows:
            duration = (r["end_time"] - r["start_time"]) / 60000.0
            total_dmg = r["total_damage"]
            total_heal = r["total_healing"]
            ratio = (total_heal / total_dmg * 100) if total_dmg > 0 else 0
            results.append(
                {
                    "raid_date": r["raid_date"],
                    "title": r["title"],
                    "raid_size": r["raid_size"],
                    "duration_minutes": round(duration, 1),
                    "total_healing": total_heal,
                    "total_damage": total_dmg,
                    "heal_damage_ratio": round(ratio, 1),
                }
            )
        return results

    def get_attendance_stats(
        self,
        min_raids: int = 1,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> list[dict]:
        """Per-character raid attendance counts."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)
        rows = conn.execute(
            f"""SELECT c.name, c.player_class, COUNT(DISTINCT perf.raid_id) as raid_count,
                      MIN(r.raid_date) as first_seen, MAX(r.raid_date) as last_seen
               FROM characters c
               JOIN (
                   SELECT character_id, raid_id FROM healer_performance
                   UNION SELECT character_id, raid_id FROM dps_performance
                   UNION SELECT character_id, raid_id FROM tank_performance
               ) perf ON perf.character_id = c.id
               JOIN raids r ON r.id = perf.raid_id
               WHERE 1=1{ds_filter}
               GROUP BY c.id
               HAVING raid_count >= ?
               ORDER BY raid_count DESC""",
            [*ds_params, min_raids],
        ).fetchall()
        return [dict(r) for r in rows]

    def get_consumable_compliance(
        self,
        min_raids: int = 3,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> dict:
        """Consumable usage matrix: character x consumable avg per raid."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)

        top_cons = conn.execute(
            f"""SELECT cu.consumable_name
                FROM consumable_usage cu
                JOIN raids r ON r.id = cu.raid_id
                WHERE 1=1{ds_filter}
                GROUP BY cu.consumable_name
                ORDER BY COUNT(DISTINCT cu.character_id) DESC
                LIMIT 10""",
            ds_params,
        ).fetchall()
        consumables = [r["consumable_name"] for r in top_cons]
        if not consumables:
            return {"characters": [], "consumables": [], "matrix": {}}

        char_raids = conn.execute(
            f"""SELECT c.name, c.player_class, COUNT(DISTINCT cu.raid_id) as raid_count
                FROM consumable_usage cu
                JOIN characters c ON c.id = cu.character_id
                JOIN raids r ON r.id = cu.raid_id
                WHERE 1=1{ds_filter}
                GROUP BY c.id
                HAVING raid_count >= ?
                ORDER BY c.name""",
            [*ds_params, min_raids],
        ).fetchall()
        characters = [{"name": r["name"], "player_class": r["player_class"]} for r in char_raids]
        char_raid_counts = {r["name"]: r["raid_count"] for r in char_raids}
        if not characters:
            return {"characters": [], "consumables": consumables, "matrix": {}}

        char_names = [c["name"] for c in characters]
        placeholders_c = ",".join("?" * len(char_names))
        placeholders_con = ",".join("?" * len(consumables))
        rows = conn.execute(
            f"""SELECT c.name, cu.consumable_name, SUM(cu.count) as total
                FROM consumable_usage cu
                JOIN characters c ON c.id = cu.character_id
                JOIN raids r ON r.id = cu.raid_id
                WHERE c.name IN ({placeholders_c})
                  AND cu.consumable_name IN ({placeholders_con})
                  {ds_filter}
                GROUP BY c.name, cu.consumable_name""",
            char_names + consumables + ds_params,
        ).fetchall()

        from collections import defaultdict

        matrix: dict[str, dict[str, float]] = defaultdict(dict)
        for r in rows:
            raids = char_raid_counts.get(r["name"], 1)
            matrix[r["name"]][r["consumable_name"]] = round(r["total"] / raids, 1)

        return {"characters": characters, "consumables": consumables, "matrix": dict(matrix)}

    def get_healer_insights(
        self,
        min_raids: int = 3,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> list[dict]:
        """Per-healer overheal %, dispels, and efficiency stats."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)
        rows = conn.execute(
            f"""SELECT c.name, c.player_class, COUNT(*) as raids,
                      AVG(hp.total_healing) as avg_healing,
                      AVG(hp.overheal_percent) as avg_overheal,
                      SUM(hp.total_dispels) as total_dispels,
                      SUM(hp.fear_ward_casts) as total_fear_wards
               FROM healer_performance hp
               JOIN characters c ON c.id = hp.character_id
               JOIN raids r ON r.id = hp.raid_id
               WHERE 1=1{ds_filter}
               GROUP BY c.id
               HAVING raids >= ?
               ORDER BY avg_healing DESC""",
            [*ds_params, min_raids],
        ).fetchall()
        return [dict(r) for r in rows]

    def get_healer_overheal_trend(
        self,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> list[dict]:
        """Per-raid average overheal % across all healers."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)
        rows = conn.execute(
            f"""SELECT r.raid_date, r.title, r.raid_size,
                      AVG(hp.overheal_percent) as avg_overheal,
                      COUNT(*) as healer_count
               FROM healer_performance hp
               JOIN raids r ON r.id = hp.raid_id
               WHERE 1=1{ds_filter}
               GROUP BY hp.raid_id
               ORDER BY r.raid_date ASC""",
            ds_params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dps_per_minute(
        self,
        min_raids: int = 3,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> list[dict]:
        """Per-character average DPS per minute (normalized by raid duration)."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)
        rows = conn.execute(
            f"""SELECT c.name, c.player_class,
                      dp.total_damage,
                      (r.end_time - r.start_time) / 60000.0 as duration_min
               FROM dps_performance dp
               JOIN characters c ON c.id = dp.character_id
               JOIN raids r ON r.id = dp.raid_id
               WHERE r.end_time IS NOT NULL AND r.end_time > r.start_time{ds_filter}
               ORDER BY c.name""",
            ds_params,
        ).fetchall()
        from collections import defaultdict

        by_char: dict[str, dict] = {}
        dpms: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            name = r["name"]
            if name not in by_char:
                by_char[name] = {"name": name, "player_class": r["player_class"]}
            dur = r["duration_min"]
            if dur > 0:
                dpms[name].append(r["total_damage"] / dur)
        results = []
        for name, info in by_char.items():
            vals = dpms[name]
            if len(vals) < min_raids:
                continue
            avg_dpm = sum(vals) / len(vals)
            results.append({**info, "raids": len(vals), "avg_dpm": round(avg_dpm, 0)})
        results.sort(key=lambda x: x["avg_dpm"], reverse=True)
        return results

    def get_tank_mitigation_stats(
        self,
        min_raids: int = 3,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> list[dict]:
        """Per-tank mitigation and damage taken stats."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)
        rows = conn.execute(
            f"""SELECT c.name, c.player_class, COUNT(*) as raids,
                      AVG(tp.mitigation_percent) as avg_mitigation,
                      AVG(tp.total_damage_taken) as avg_damage_taken
               FROM tank_performance tp
               JOIN characters c ON c.id = tp.character_id
               JOIN raids r ON r.id = tp.raid_id
               WHERE 1=1{ds_filter}
               GROUP BY c.id
               HAVING raids >= ?
               ORDER BY avg_mitigation DESC""",
            [*ds_params, min_raids],
        ).fetchall()
        return [dict(r) for r in rows]

    def get_consumable_usage_rates(
        self,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> list[dict]:
        """Per-consumable summary stats."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)
        rows = conn.execute(
            f"""SELECT cu.consumable_name,
                      COUNT(DISTINCT cu.character_id) as total_users,
                      SUM(cu.count) as total_uses
               FROM consumable_usage cu
               JOIN raids r ON r.id = cu.raid_id
               WHERE 1=1{ds_filter}
               GROUP BY cu.consumable_name
               ORDER BY total_users DESC""",
            ds_params,
        ).fetchall()
        results = []
        for r in rows:
            results.append(
                {
                    "consumable_name": r["consumable_name"],
                    "total_users": r["total_users"],
                    "total_uses": r["total_uses"],
                    "avg_per_user": round(r["total_uses"] / r["total_users"], 1) if r["total_users"] > 0 else 0,
                }
            )
        return results

    def get_distinct_zones(self, source: str = "guild") -> list[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT zone FROM raids WHERE zone IS NOT NULL AND source = ? ORDER BY zone",
            (source,),
        ).fetchall()
        return [r["zone"] for r in rows]

    def get_raid_list(self, limit: int = 50) -> list[dict]:
        """Get list of all imported guild raids."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT report_id, title, owner, raid_date, imported_at
               FROM raids WHERE source = 'guild'
               ORDER BY raid_date DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_guild_raids_for_comparison(self, limit: int = 50) -> list[dict]:
        """Get guild raids with zone and size for comparison dropdowns."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT report_id, title, raid_date, zone, raid_size
               FROM raids WHERE source = 'guild'
               ORDER BY raid_date DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_raid(self, report_id: str) -> None:
        """Delete a raid and all associated performance data."""
        conn = self._get_conn()
        raid = conn.execute("SELECT id FROM raids WHERE report_id = ?", (report_id,)).fetchone()
        if not raid:
            return
        raid_id = raid["id"]

        conn.execute(
            "DELETE FROM healer_spells WHERE healer_performance_id IN "
            "(SELECT id FROM healer_performance WHERE raid_id = ?)",
            (raid_id,),
        )
        conn.execute("DELETE FROM healer_performance WHERE raid_id = ?", (raid_id,))

        conn.execute(
            "DELETE FROM dps_abilities WHERE dps_performance_id IN (SELECT id FROM dps_performance WHERE raid_id = ?)",
            (raid_id,),
        )
        conn.execute("DELETE FROM dps_performance WHERE raid_id = ?", (raid_id,))

        conn.execute(
            "DELETE FROM tank_damage_taken WHERE tank_performance_id IN "
            "(SELECT id FROM tank_performance WHERE raid_id = ?)",
            (raid_id,),
        )
        conn.execute(
            "DELETE FROM tank_abilities WHERE tank_performance_id IN "
            "(SELECT id FROM tank_performance WHERE raid_id = ?)",
            (raid_id,),
        )
        conn.execute("DELETE FROM tank_performance WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM consumable_usage WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM interrupt_usage WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM cancelled_casts WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM aura_uptime WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM totem_uptime WHERE raid_id = ?", (raid_id,))
        conn.execute(
            "DELETE FROM encounter_performance WHERE encounter_row_id IN (SELECT id FROM encounters WHERE raid_id = ?)",
            (raid_id,),
        )
        conn.execute("DELETE FROM encounters WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM raids WHERE id = ?", (raid_id,))
        conn.commit()

        cache_file = _cache_file(report_id)
        if os.path.exists(cache_file):
            with contextlib.suppress(OSError):
                os.remove(cache_file)
        clear_response_cache()

    def clear_raid_cache(self, report_id: str) -> None:
        """Clear cached API data for a specific report."""
        cache_file = _cache_file(report_id)
        if os.path.exists(cache_file):
            with contextlib.suppress(OSError):
                os.remove(cache_file)
        clear_response_cache()

    def is_raid_imported(self, report_id: str) -> bool:
        """Check if a raid has already been imported."""
        conn = self._get_conn()
        row = conn.execute("SELECT id FROM raids WHERE report_id = ?", (report_id,)).fetchone()
        return row is not None

    def get_imported_report_codes(self) -> dict[str, str]:
        """Return a mapping of report_id -> imported_at for all stored raids."""
        conn = self._get_conn()
        rows = conn.execute("SELECT report_id, imported_at FROM raids").fetchall()
        return {r["report_id"]: r["imported_at"] for r in rows}

    # ── Raid Group operations ──

    def create_raid_group(self, name: str, raid_days: list[str] | None = None) -> RaidGroup:
        conn = self._get_conn()
        days_json = json.dumps(raid_days or [])
        conn.execute(
            "INSERT INTO raid_groups (name, raid_days) VALUES (?, ?)",
            (name, days_json),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM raid_groups WHERE name = ?", (name,)).fetchone()
        return RaidGroup(
            id=row["id"],
            name=row["name"],
            raid_days=json.loads(row["raid_days"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def update_raid_group(self, group_id: int, name: str | None = None, raid_days: list[str] | None = None) -> None:
        conn = self._get_conn()
        if name is not None:
            conn.execute("UPDATE raid_groups SET name = ? WHERE id = ?", (name, group_id))
        if raid_days is not None:
            conn.execute("UPDATE raid_groups SET raid_days = ? WHERE id = ?", (json.dumps(raid_days), group_id))
        conn.commit()

    def delete_raid_group(self, group_id: int) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM raid_group_members WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM raid_groups WHERE id = ?", (group_id,))
        conn.commit()

    def get_all_raid_groups(self) -> list[RaidGroup]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM raid_groups ORDER BY name").fetchall()
        groups = []
        for r in rows:
            members = conn.execute(
                """SELECT c.name FROM raid_group_members rgm
                   JOIN characters c ON c.id = rgm.character_id
                   WHERE rgm.group_id = ?
                   ORDER BY c.name""",
                (r["id"],),
            ).fetchall()
            groups.append(
                RaidGroup(
                    id=r["id"],
                    name=r["name"],
                    raid_days=json.loads(r["raid_days"]),
                    created_at=datetime.fromisoformat(r["created_at"]),
                    members=[m["name"] for m in members],
                )
            )
        return groups

    def get_raid_group(self, group_id: int) -> RaidGroup | None:
        conn = self._get_conn()
        r = conn.execute("SELECT * FROM raid_groups WHERE id = ?", (group_id,)).fetchone()
        if not r:
            return None
        members = conn.execute(
            """SELECT c.name FROM raid_group_members rgm
               JOIN characters c ON c.id = rgm.character_id
               WHERE rgm.group_id = ?
               ORDER BY c.name""",
            (r["id"],),
        ).fetchall()
        return RaidGroup(
            id=r["id"],
            name=r["name"],
            raid_days=json.loads(r["raid_days"]),
            created_at=datetime.fromisoformat(r["created_at"]),
            members=[m["name"] for m in members],
        )

    def add_raid_group_member(self, group_id: int, character_name: str) -> bool:
        conn = self._get_conn()
        char = conn.execute(
            "SELECT id FROM characters WHERE name = ? COLLATE NOCASE",
            (character_name,),
        ).fetchone()
        if not char:
            return False
        try:
            conn.execute(
                "INSERT INTO raid_group_members (group_id, character_id) VALUES (?, ?)",
                (group_id, char["id"]),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_raid_group_member(self, group_id: int, character_name: str) -> None:
        conn = self._get_conn()
        char = conn.execute(
            "SELECT id FROM characters WHERE name = ? COLLATE NOCASE",
            (character_name,),
        ).fetchone()
        if char:
            conn.execute(
                "DELETE FROM raid_group_members WHERE group_id = ? AND character_id = ?",
                (group_id, char["id"]),
            )
            conn.commit()

    def get_groups_for_character(self, character_name: str) -> list[str]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT rg.name FROM raid_groups rg
               JOIN raid_group_members rgm ON rgm.group_id = rg.id
               JOIN characters c ON c.id = rgm.character_id
               WHERE c.name = ? COLLATE NOCASE
               ORDER BY rg.name""",
            (character_name,),
        ).fetchall()
        return [r["name"] for r in rows]

    # ── Analytics queries ──

    def get_group_performance_trend(self, group_id: int) -> list[dict]:
        """Aggregate performance for all group members per raid, ordered by date."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.title, r.report_id, r.raid_size,
                      AVG(hp.total_healing) as avg_healing,
                      AVG(dp.total_damage) as avg_damage,
                      AVG(tp.mitigation_percent) as avg_mitigation,
                      COUNT(DISTINCT c.id) as members_present
               FROM raids r
               JOIN raid_group_members rgm ON rgm.group_id = ?
               JOIN characters c ON c.id = rgm.character_id
               LEFT JOIN healer_performance hp ON hp.character_id = c.id AND hp.raid_id = r.id
               LEFT JOIN dps_performance dp ON dp.character_id = c.id AND dp.raid_id = r.id
               LEFT JOIN tank_performance tp ON tp.character_id = c.id AND tp.raid_id = r.id
               WHERE r.source = 'guild'
                 AND (hp.id IS NOT NULL OR dp.id IS NOT NULL OR tp.id IS NOT NULL)
               GROUP BY r.id
               ORDER BY r.raid_date ASC""",
            (group_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_group_attendance(self, group_id: int) -> list[dict]:
        """Attendance for each group member: raids attended, total raids, %."""
        conn = self._get_conn()
        members = conn.execute(
            """SELECT c.id, c.name, c.player_class
               FROM raid_group_members rgm
               JOIN characters c ON c.id = rgm.character_id
               WHERE rgm.group_id = ?
               ORDER BY c.name""",
            (group_id,),
        ).fetchall()

        group_raid_ids = conn.execute(
            """SELECT DISTINCT r.id FROM raids r
               JOIN raid_group_members rgm ON rgm.group_id = ?
               JOIN characters c ON c.id = rgm.character_id
               LEFT JOIN healer_performance hp ON hp.character_id = c.id AND hp.raid_id = r.id
               LEFT JOIN dps_performance dp ON dp.character_id = c.id AND dp.raid_id = r.id
               LEFT JOIN tank_performance tp ON tp.character_id = c.id AND tp.raid_id = r.id
               WHERE r.source = 'guild'
                 AND (hp.id IS NOT NULL OR dp.id IS NOT NULL OR tp.id IS NOT NULL)""",
            (group_id,),
        ).fetchall()
        total_raids = len(group_raid_ids)
        raid_id_set = {r["id"] for r in group_raid_ids}

        results = []
        for m in members:
            attended_rows = conn.execute(
                """SELECT DISTINCT raid_id FROM (
                    SELECT raid_id FROM healer_performance WHERE character_id = ?
                    UNION SELECT raid_id FROM tank_performance WHERE character_id = ?
                    UNION SELECT raid_id FROM dps_performance WHERE character_id = ?
                )""",
                (m["id"], m["id"], m["id"]),
            ).fetchall()
            attended = sum(1 for r in attended_rows if r["raid_id"] in raid_id_set)
            pct = round(attended / total_raids * 100, 1) if total_raids > 0 else 0.0
            results.append(
                {
                    "name": m["name"],
                    "player_class": m["player_class"],
                    "attended": attended,
                    "total_raids": total_raids,
                    "attendance_pct": pct,
                }
            )
        return results

    def get_group_role_coverage(self, group_id: int) -> list[dict]:
        """For each group member, count raids in each role."""
        conn = self._get_conn()
        members = conn.execute(
            """SELECT c.id, c.name, c.player_class
               FROM raid_group_members rgm
               JOIN characters c ON c.id = rgm.character_id
               WHERE rgm.group_id = ?
               ORDER BY c.name""",
            (group_id,),
        ).fetchall()

        results = []
        for m in members:
            healer_count = conn.execute(
                """SELECT COUNT(*) as cnt FROM healer_performance hp
                   JOIN raids r ON r.id = hp.raid_id
                   WHERE hp.character_id = ? AND r.source = 'guild'""",
                (m["id"],),
            ).fetchone()["cnt"]
            tank_count = conn.execute(
                """SELECT COUNT(*) as cnt FROM tank_performance tp
                   JOIN raids r ON r.id = tp.raid_id
                   WHERE tp.character_id = ? AND r.source = 'guild'""",
                (m["id"],),
            ).fetchone()["cnt"]
            dps_count = conn.execute(
                """SELECT COUNT(*) as cnt FROM dps_performance dp
                   JOIN raids r ON r.id = dp.raid_id
                   WHERE dp.character_id = ? AND r.source = 'guild'""",
                (m["id"],),
            ).fetchone()["cnt"]
            results.append(
                {
                    "name": m["name"],
                    "player_class": m["player_class"],
                    "healer": healer_count,
                    "tank": tank_count,
                    "dps": dps_count,
                }
            )
        return results

    def get_group_classes(self, group_id: int) -> list[str]:
        """Get distinct player classes of members in a raid group."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT DISTINCT c.player_class
               FROM raid_group_members rgm
               JOIN characters c ON c.id = rgm.character_id
               WHERE rgm.group_id = ?
               ORDER BY c.player_class""",
            (group_id,),
        ).fetchall()
        return [r["player_class"] for r in rows]

    def get_class_comparison_trend(
        self, group_id: int, class_name: str, role: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Get per-player performance trend for a class within a group.

        Returns rows with: name, raid_date, title, metric_value, metric_key.
        Role is auto-detected if not specified.
        """
        conn = self._get_conn()
        members = conn.execute(
            """SELECT c.id, c.name
               FROM raid_group_members rgm
               JOIN characters c ON c.id = rgm.character_id
               WHERE rgm.group_id = ? AND c.player_class = ? COLLATE NOCASE
               ORDER BY c.name""",
            (group_id, class_name),
        ).fetchall()

        if not members:
            return []

        results = []
        for m in members:
            cid, name = m["id"], m["name"]

            if role in (None, "healer"):
                rows = conn.execute(
                    """SELECT r.raid_date, r.title, r.raid_size, hp.total_healing as metric_value
                       FROM healer_performance hp
                       JOIN raids r ON r.id = hp.raid_id
                       WHERE hp.character_id = ? AND r.source = 'guild'
                       ORDER BY r.raid_date DESC LIMIT ?""",
                    (cid, limit),
                ).fetchall()
                if rows:
                    for r in reversed(rows):
                        results.append(
                            {
                                "name": name,
                                "raid_date": r["raid_date"],
                                "title": r["title"],
                                "raid_size": r["raid_size"],
                                "metric_value": r["metric_value"],
                                "metric_key": "healing",
                            }
                        )
                    if role is not None:
                        continue

            if role in (None, "tank"):
                rows = conn.execute(
                    """SELECT r.raid_date, r.title, r.raid_size, tp.mitigation_percent as metric_value
                       FROM tank_performance tp
                       JOIN raids r ON r.id = tp.raid_id
                       WHERE tp.character_id = ? AND r.source = 'guild'
                       ORDER BY r.raid_date DESC LIMIT ?""",
                    (cid, limit),
                ).fetchall()
                if rows:
                    for r in reversed(rows):
                        results.append(
                            {
                                "name": name,
                                "raid_date": r["raid_date"],
                                "title": r["title"],
                                "raid_size": r["raid_size"],
                                "metric_value": r["metric_value"],
                                "metric_key": "mitigation",
                            }
                        )
                    if role is not None:
                        continue

            if role in (None, "dps"):
                rows = conn.execute(
                    """SELECT r.raid_date, r.title, r.raid_size, dp.total_damage as metric_value
                       FROM dps_performance dp
                       JOIN raids r ON r.id = dp.raid_id
                       WHERE dp.character_id = ? AND r.source = 'guild'
                       ORDER BY r.raid_date DESC LIMIT ?""",
                    (cid, limit),
                ).fetchall()
                if rows:
                    for r in reversed(rows):
                        results.append(
                            {
                                "name": name,
                                "raid_date": r["raid_date"],
                                "title": r["title"],
                                "raid_size": r["raid_size"],
                                "metric_value": r["metric_value"],
                                "metric_key": "damage",
                            }
                        )

        return results

    def get_class_comparison_summary(self, group_id: int, class_name: str) -> list[dict]:
        """Get summary stats per player of a class in a group.

        Returns: name, player_class, raids, avg_performance, best, worst,
        consistency, metric_key.
        """
        conn = self._get_conn()
        members = conn.execute(
            """SELECT c.id, c.name, c.player_class
               FROM raid_group_members rgm
               JOIN characters c ON c.id = rgm.character_id
               WHERE rgm.group_id = ? AND c.player_class = ? COLLATE NOCASE
               ORDER BY c.name""",
            (group_id, class_name),
        ).fetchall()

        results = []
        for m in members:
            cid = m["id"]
            row: dict = {"name": m["name"], "player_class": m["player_class"]}

            healer_rows = conn.execute(
                "SELECT total_healing FROM healer_performance WHERE character_id = ?",
                (cid,),
            ).fetchall()
            tank_rows = conn.execute(
                "SELECT mitigation_percent FROM tank_performance WHERE character_id = ?",
                (cid,),
            ).fetchall()
            dps_rows = conn.execute(
                "SELECT total_damage FROM dps_performance WHERE character_id = ?",
                (cid,),
            ).fetchall()

            if healer_rows:
                vals = [r["total_healing"] for r in healer_rows]
                row["metric_key"] = "healing"
            elif tank_rows:
                vals = [r["mitigation_percent"] for r in tank_rows]
                row["metric_key"] = "mitigation"
            elif dps_rows:
                vals = [r["total_damage"] for r in dps_rows]
                row["metric_key"] = "damage"
            else:
                continue

            row["raids"] = len(vals)
            row["avg_performance"] = round(sum(vals) / len(vals), 1) if vals else 0
            row["best"] = round(max(vals), 1) if vals else 0
            row["worst"] = round(min(vals), 1) if vals else 0

            if len(vals) >= 2:
                mean = sum(vals) / len(vals)
                variance = sum((v - mean) ** 2 for v in vals) / len(vals)
                std = variance**0.5
                row["consistency"] = round(100 - (std / mean * 100), 1) if mean > 0 else 0
            else:
                row["consistency"] = 100.0

            compliance = self.get_character_consumable_compliance(m["name"])
            row["consumable_compliance"] = (
                f"{compliance['avg_per_raid']:.1f}/raid" if compliance and compliance.get("total_raids", 0) > 0 else "-"
            )

            results.append(row)

        return results

    def get_character_primary_role(self, character_name: str) -> str | None:
        """Detect primary role by counting performance rows per table."""
        conn = self._get_conn()
        char = conn.execute(
            "SELECT id FROM characters WHERE name = ? COLLATE NOCASE",
            (character_name,),
        ).fetchone()
        if not char:
            return None
        cid = char["id"]

        healer_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM healer_performance hp "
            "JOIN raids r ON r.id = hp.raid_id "
            "WHERE hp.character_id = ? AND r.source = 'guild'",
            (cid,),
        ).fetchone()["cnt"]

        tank_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM tank_performance tp "
            "JOIN raids r ON r.id = tp.raid_id "
            "WHERE tp.character_id = ? AND r.source = 'guild'",
            (cid,),
        ).fetchone()["cnt"]

        dps_row = conn.execute(
            "SELECT COUNT(*) as cnt, dp.role FROM dps_performance dp "
            "JOIN raids r ON r.id = dp.raid_id "
            "WHERE dp.character_id = ? AND r.source = 'guild' "
            "GROUP BY dp.role ORDER BY cnt DESC LIMIT 1",
            (cid,),
        ).fetchone()
        dps_count = dps_row["cnt"] if dps_row else 0
        dps_role = dps_row["role"] if dps_row else "melee"

        candidates = [
            (healer_count, "healer"),
            (tank_count, "tank"),
            (dps_count, dps_role),
        ]
        best = max(candidates, key=lambda x: x[0])
        return best[1] if best[0] > 0 else None

    def get_character_boss_comparison(self, character_name: str) -> list[dict]:
        """Per-boss performance comparison against role peers."""
        conn = self._get_conn()
        char = conn.execute(
            "SELECT id FROM characters WHERE name = ? COLLATE NOCASE",
            (character_name,),
        ).fetchone()
        if not char:
            return []
        cid = char["id"]

        boss_rows = conn.execute(
            """SELECT DISTINCT e.encounter_id, e.name
               FROM encounter_performance ep
               JOIN encounters e ON e.id = ep.encounter_row_id
               JOIN raids r ON r.id = e.raid_id
               WHERE ep.character_id = ? AND r.source = 'guild'
               ORDER BY e.name""",
            (cid,),
        ).fetchall()

        results = []
        for boss in boss_rows:
            enc_id = boss["encounter_id"]

            my_row = conn.execute(
                """SELECT ep.role,
                          COUNT(*) as kills,
                          CAST(AVG(ep.total_damage) AS INTEGER) as avg_damage,
                          CAST(AVG(ep.total_healing) AS INTEGER) as avg_healing,
                          CAST(AVG(ep.total_damage_taken) AS INTEGER) as avg_damage_taken,
                          AVG(ep.active_time_percent) as avg_active_time
                   FROM encounter_performance ep
                   JOIN encounters e ON e.id = ep.encounter_row_id
                   JOIN raids r ON r.id = e.raid_id
                   WHERE ep.character_id = ? AND e.encounter_id = ? AND r.source = 'guild'
                   GROUP BY ep.role
                   ORDER BY kills DESC LIMIT 1""",
                (cid, enc_id),
            ).fetchone()
            if not my_row:
                continue

            my_role = my_row["role"]

            peers = conn.execute(
                """SELECT c.name,
                          CAST(AVG(ep.total_damage) AS INTEGER) as avg_damage,
                          CAST(AVG(ep.total_healing) AS INTEGER) as avg_healing,
                          CAST(AVG(ep.total_damage_taken) AS INTEGER) as avg_damage_taken
                   FROM encounter_performance ep
                   JOIN encounters e ON e.id = ep.encounter_row_id
                   JOIN raids r ON r.id = e.raid_id
                   JOIN characters c ON c.id = ep.character_id
                   WHERE e.encounter_id = ? AND ep.role = ? AND r.source = 'guild'
                   GROUP BY c.id""",
                (enc_id, my_role),
            ).fetchall()

            peer_count = len(peers)
            if peer_count == 0:
                continue

            if my_role == "healer":
                primary_key = "avg_healing"
                reverse_sort = True
            elif my_role == "tank":
                primary_key = "avg_damage_taken"
                reverse_sort = False
            else:
                primary_key = "avg_damage"
                reverse_sort = True

            my_value = my_row[primary_key] or 0
            role_avg = sum(p[primary_key] or 0 for p in peers) / peer_count

            sorted_peers = sorted(peers, key=lambda p: p[primary_key] or 0, reverse=reverse_sort)
            rank = next(
                (i + 1 for i, p in enumerate(sorted_peers) if p["name"].lower() == character_name.lower()),
                peer_count,
            )

            delta_pct = ((my_value - role_avg) / role_avg * 100) if role_avg else 0.0

            results.append({
                "boss_name": boss["name"],
                "encounter_id": enc_id,
                "role": my_role,
                "kills": my_row["kills"],
                "my_value": my_value,
                "role_avg": round(role_avg),
                "delta_pct": round(delta_pct, 1),
                "rank": rank,
                "peer_count": peer_count,
            })

        return results

    def get_healer_role_avg_trend(self) -> list[dict]:
        """Per-raid average healing stats across all healers (for overlay)."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.raid_size,
                      AVG(hp.total_healing) as avg_healing,
                      AVG(hp.overheal_percent) as avg_overheal,
                      AVG(hp.active_time_percent) as avg_active_time
               FROM healer_performance hp
               JOIN raids r ON r.id = hp.raid_id
               WHERE r.source = 'guild'
               GROUP BY hp.raid_id
               ORDER BY r.raid_date DESC
               LIMIT 20""",
        ).fetchall()
        return [dict(r) for r in rows]

    def get_tank_role_avg_trend(self) -> list[dict]:
        """Per-raid average tank stats across all tanks (for overlay)."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.raid_size,
                      AVG(tp.total_damage_taken) as avg_damage_taken,
                      AVG(tp.mitigation_percent) as avg_mitigation,
                      AVG(tp.active_time_percent) as avg_active_time
               FROM tank_performance tp
               JOIN raids r ON r.id = tp.raid_id
               WHERE r.source = 'guild'
               GROUP BY tp.raid_id
               ORDER BY r.raid_date DESC
               LIMIT 20""",
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dps_role_avg_trend(self) -> list[dict]:
        """Per-raid average DPS stats across all DPS (for overlay)."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.raid_size,
                      AVG(dp.total_damage) as avg_damage,
                      AVG(dp.active_time_percent) as avg_active_time
               FROM dps_performance dp
               JOIN raids r ON r.id = dp.raid_id
               WHERE r.source = 'guild'
               GROUP BY dp.raid_id
               ORDER BY r.raid_date DESC
               LIMIT 20""",
        ).fetchall()
        return [dict(r) for r in rows]

    def get_cancelled_cast_trend(self, character_name: str) -> list[dict]:
        """Per-raid cancel rate trend for a character."""
        conn = self._get_conn()
        char = conn.execute(
            "SELECT id FROM characters WHERE name = ? COLLATE NOCASE",
            (character_name,),
        ).fetchone()
        if not char:
            return []
        rows = conn.execute(
            """SELECT r.raid_date, r.raid_size, r.title,
                      cc.total_casts, cc.cancelled_casts, cc.cancel_rate
               FROM cancelled_casts cc
               JOIN raids r ON r.id = cc.raid_id
               WHERE cc.character_id = ? AND r.source = 'guild'
               ORDER BY r.raid_date DESC
               LIMIT 20""",
            (char["id"],),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_cancelled_cast_raid_summary(self, raid_id: int) -> list[dict]:
        """All players' cancel stats for a single raid."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT c.name as player_name, c.player_class,
                      cc.total_casts, cc.cancelled_casts, cc.cancel_rate
               FROM cancelled_casts cc
               JOIN characters c ON c.id = cc.character_id
               WHERE cc.raid_id = ?
               ORDER BY cc.cancel_rate ASC""",
            (raid_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_character_consistency(self, character_name: str) -> dict:
        """Compute consistency scores (std dev) for a character's performance."""
        conn = self._get_conn()
        char = conn.execute(
            "SELECT id FROM characters WHERE name = ? COLLATE NOCASE",
            (character_name,),
        ).fetchone()
        if not char:
            return {}
        cid = char["id"]

        result = {"name": character_name}

        healing_rows = conn.execute(
            """SELECT hp.total_healing FROM healer_performance hp
               JOIN raids r ON r.id = hp.raid_id
               WHERE hp.character_id = ? AND r.source = 'guild'""",
            (cid,),
        ).fetchall()
        if len(healing_rows) >= 2:
            vals = [r["total_healing"] for r in healing_rows]
            mean = sum(vals) / len(vals)
            variance = sum((v - mean) ** 2 for v in vals) / len(vals)
            std = variance**0.5
            result["healing_mean"] = round(mean)
            result["healing_std"] = round(std)
            result["healing_consistency"] = round(100 - (std / mean * 100), 1) if mean > 0 else 0

        damage_rows = conn.execute(
            """SELECT dp.total_damage FROM dps_performance dp
               JOIN raids r ON r.id = dp.raid_id
               WHERE dp.character_id = ? AND r.source = 'guild'""",
            (cid,),
        ).fetchall()
        if len(damage_rows) >= 2:
            vals = [r["total_damage"] for r in damage_rows]
            mean = sum(vals) / len(vals)
            variance = sum((v - mean) ** 2 for v in vals) / len(vals)
            std = variance**0.5
            result["damage_mean"] = round(mean)
            result["damage_std"] = round(std)
            result["damage_consistency"] = round(100 - (std / mean * 100), 1) if mean > 0 else 0

        tank_rows = conn.execute(
            """SELECT tp.mitigation_percent FROM tank_performance tp
               JOIN raids r ON r.id = tp.raid_id
               WHERE tp.character_id = ? AND r.source = 'guild'""",
            (cid,),
        ).fetchall()
        if len(tank_rows) >= 2:
            vals = [r["mitigation_percent"] for r in tank_rows]
            mean = sum(vals) / len(vals)
            variance = sum((v - mean) ** 2 for v in vals) / len(vals)
            std = variance**0.5
            result["mitigation_mean"] = round(mean, 1)
            result["mitigation_std"] = round(std, 1)
            result["mitigation_consistency"] = round(100 - (std / max(mean, 0.01) * 100), 1)

        return result

    def get_character_personal_bests(self, character_name: str) -> list[dict]:
        """Get top and bottom performance raids for a character."""
        conn = self._get_conn()
        char = conn.execute(
            "SELECT id FROM characters WHERE name = ? COLLATE NOCASE",
            (character_name,),
        ).fetchone()
        if not char:
            return []
        cid = char["id"]
        results = []

        for label, table, metric, order in [
            ("Best Healing", "healer_performance", "total_healing", "DESC"),
            ("Worst Healing", "healer_performance", "total_healing", "ASC"),
            ("Best DPS", "dps_performance", "total_damage", "DESC"),
            ("Worst DPS", "dps_performance", "total_damage", "ASC"),
            ("Best Mitigation", "tank_performance", "mitigation_percent", "DESC"),
            ("Worst Mitigation", "tank_performance", "mitigation_percent", "ASC"),
        ]:
            row = conn.execute(
                f"""SELECT r.raid_date, r.title, r.report_id, p.{metric} as value
                    FROM {table} p
                    JOIN raids r ON r.id = p.raid_id
                    WHERE p.character_id = ? AND r.source = 'guild'
                    ORDER BY p.{metric} {order}
                    LIMIT 1""",
                (cid,),
            ).fetchone()
            if row:
                results.append(
                    {
                        "label": label,
                        "raid_date": row["raid_date"],
                        "title": row["title"],
                        "report_id": row["report_id"],
                        "value": row["value"],
                    }
                )
        return results

    def get_character_consumable_compliance(self, character_name: str) -> dict:
        """Consumable usage rate: % of raids where character used any consumables."""
        conn = self._get_conn()
        char = conn.execute(
            "SELECT id FROM characters WHERE name = ? COLLATE NOCASE",
            (character_name,),
        ).fetchone()
        if not char:
            return {}
        cid = char["id"]

        total_raids = conn.execute(
            """SELECT COUNT(DISTINCT raid_id) as cnt FROM (
                SELECT hp.raid_id FROM healer_performance hp
                    JOIN raids r ON r.id = hp.raid_id
                    WHERE hp.character_id = ? AND r.source = 'guild'
                UNION SELECT tp.raid_id FROM tank_performance tp
                    JOIN raids r ON r.id = tp.raid_id
                    WHERE tp.character_id = ? AND r.source = 'guild'
                UNION SELECT dp.raid_id FROM dps_performance dp
                    JOIN raids r ON r.id = dp.raid_id
                    WHERE dp.character_id = ? AND r.source = 'guild'
            )""",
            (cid, cid, cid),
        ).fetchone()["cnt"]

        raids_with_consumes = conn.execute(
            """SELECT COUNT(DISTINCT cu.raid_id) as cnt FROM consumable_usage cu
               JOIN raids r ON r.id = cu.raid_id
               WHERE cu.character_id = ? AND r.source = 'guild'""",
            (cid,),
        ).fetchone()["cnt"]

        avg_per_raid = conn.execute(
            """SELECT AVG(total) as avg FROM (
                SELECT SUM(cu.count) as total FROM consumable_usage cu
                JOIN raids r ON r.id = cu.raid_id
                WHERE cu.character_id = ? AND r.source = 'guild'
                GROUP BY cu.raid_id
            )""",
            (cid,),
        ).fetchone()["avg"]

        return {
            "total_raids": total_raids,
            "raids_with_consumes": raids_with_consumes,
            "compliance_pct": round(raids_with_consumes / total_raids * 100, 1) if total_raids > 0 else 0,
            "avg_per_raid": round(avg_per_raid, 1) if avg_per_raid else 0,
        }

    def get_character_spider_data(self, character_name: str) -> dict:
        """Normalized 0-100 scores across multiple dimensions for radar chart."""
        conn = self._get_conn()
        char = conn.execute(
            "SELECT id FROM characters WHERE name = ? COLLATE NOCASE",
            (character_name,),
        ).fetchone()
        if not char:
            return {}
        char["id"]

        history = self.get_character_history(character_name)
        if not history or history.total_raids == 0:
            return {}

        all_chars = self.get_all_characters()
        if not all_chars:
            return {}

        def percentile(value, all_values):
            if not all_values or value is None:
                return 0
            sorted_vals = sorted(v for v in all_values if v is not None)
            if not sorted_vals:
                return 0
            pos = sum(1 for v in sorted_vals if v <= value)
            return round(pos / len(sorted_vals) * 100)

        all_healing = [c.avg_healing for c in all_chars if c.avg_healing]
        all_damage = [c.avg_damage for c in all_chars if c.avg_damage]
        all_mitigation = [c.avg_mitigation_percent for c in all_chars if c.avg_mitigation_percent]
        all_raids = [c.total_raids for c in all_chars]
        all_consumes = [c.total_consumables_used for c in all_chars]
        all_active_time = [c.avg_active_time for c in all_chars if c.avg_active_time]

        consistency = self.get_character_consistency(character_name)
        con_scores = []
        for key in ["healing_consistency", "damage_consistency", "mitigation_consistency"]:
            if key in consistency:
                con_scores.append(consistency[key])
        avg_consistency = sum(con_scores) / len(con_scores) if con_scores else 50

        return {
            "healing": percentile(history.avg_healing, all_healing),
            "damage": percentile(history.avg_damage, all_damage),
            "mitigation": percentile(history.avg_mitigation_percent, all_mitigation),
            "active_time": percentile(history.avg_active_time, all_active_time),
            "activity": percentile(history.total_raids, all_raids),
            "consumables": percentile(history.total_consumables_used, all_consumes),
            "consistency": min(100, max(0, round(avg_consistency))),
        }

    def get_character_raid_calendar(self, character_name: str) -> list[dict]:
        """Get raid dates and a performance score for calendar heatmap."""
        conn = self._get_conn()
        char = conn.execute(
            "SELECT id FROM characters WHERE name = ? COLLATE NOCASE",
            (character_name,),
        ).fetchone()
        if not char:
            return []
        cid = char["id"]

        rows = conn.execute(
            """SELECT r.raid_date, r.title, r.report_id,
                      hp.total_healing, dp.total_damage, tp.mitigation_percent
               FROM raids r
               LEFT JOIN healer_performance hp ON hp.character_id = ? AND hp.raid_id = r.id
               LEFT JOIN dps_performance dp ON dp.character_id = ? AND dp.raid_id = r.id
               LEFT JOIN tank_performance tp ON tp.character_id = ? AND tp.raid_id = r.id
               WHERE r.source = 'guild'
                 AND (hp.id IS NOT NULL OR dp.id IS NOT NULL OR tp.id IS NOT NULL)
               ORDER BY r.raid_date ASC""",
            (cid, cid, cid),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Cross-analysis queries ──

    def get_raid_aggregate_stats(self, report_id: str) -> dict | None:
        conn = self._get_conn()
        raid = conn.execute(
            "SELECT id, report_id, title, raid_date, start_time, end_time, raid_size, zone FROM raids WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        if not raid:
            return None
        raid_id = raid["id"]

        total_healing = conn.execute(
            "SELECT COALESCE(SUM(total_healing), 0) as val FROM healer_performance WHERE raid_id = ?",
            (raid_id,),
        ).fetchone()["val"]

        total_damage = conn.execute(
            "SELECT COALESCE(SUM(total_damage), 0) as val FROM dps_performance WHERE raid_id = ?",
            (raid_id,),
        ).fetchone()["val"]

        total_damage_taken = conn.execute(
            "SELECT COALESCE(SUM(total_damage_taken), 0) as val FROM tank_performance WHERE raid_id = ?",
            (raid_id,),
        ).fetchone()["val"]

        duration_ms = (raid["end_time"] - raid["start_time"]) if raid["end_time"] and raid["start_time"] else 0
        return {
            "report_id": raid["report_id"],
            "title": raid["title"],
            "raid_date": raid["raid_date"],
            "raid_size": raid["raid_size"],
            "zone": raid["zone"],
            "duration_ms": duration_ms,
            "total_healing": total_healing,
            "total_damage": total_damage,
            "total_damage_taken": total_damage_taken,
        }

    def get_historical_raid_aggregates(
        self, raid_size_mode: int, exclude_report_id: str, zone: str | None = None, limit: int = 50
    ) -> list[dict]:
        conn = self._get_conn()
        if raid_size_mode == 1:
            size_clause = "AND r.raid_size <= 15"
        elif raid_size_mode == 2:
            size_clause = "AND r.raid_size > 15"
        else:
            size_clause = ""

        params: list = [exclude_report_id]
        zone_clause = ""
        if zone:
            zone_clause = "AND (r.zone = ? OR r.zone IS NULL)"
            params.append(zone)
        params.append(limit)

        rows = conn.execute(
            f"""SELECT r.report_id, r.title, r.raid_date, r.start_time, r.end_time, r.raid_size, r.zone,
                       COALESCE((SELECT SUM(hp.total_healing) FROM healer_performance hp WHERE hp.raid_id = r.id), 0) as total_healing,
                       COALESCE((SELECT SUM(dp.total_damage) FROM dps_performance dp WHERE dp.raid_id = r.id), 0) as total_damage,
                       COALESCE((SELECT SUM(tp.total_damage_taken) FROM tank_performance tp WHERE tp.raid_id = r.id), 0) as total_damage_taken
                FROM raids r
                WHERE r.report_id != ? AND r.source = 'guild' {size_clause} {zone_clause} AND r.raid_size IS NOT NULL
                ORDER BY r.raid_date ASC
                LIMIT ?""",
            params,
        ).fetchall()

        results = []
        for r in rows:
            duration_ms = (r["end_time"] - r["start_time"]) if r["end_time"] and r["start_time"] else 0
            results.append(
                {
                    "report_id": r["report_id"],
                    "title": r["title"],
                    "raid_date": r["raid_date"],
                    "raid_size": r["raid_size"],
                    "zone": r["zone"],
                    "duration_ms": duration_ms,
                    "total_healing": r["total_healing"],
                    "total_damage": r["total_damage"],
                    "total_damage_taken": r["total_damage_taken"],
                }
            )
        return results

    def get_player_performance_for_raid(self, report_id: str) -> list[dict]:
        conn = self._get_conn()
        raid = conn.execute("SELECT id FROM raids WHERE report_id = ?", (report_id,)).fetchone()
        if not raid:
            return []
        raid_id = raid["id"]
        results = []

        for r in conn.execute(
            """SELECT c.name, c.player_class, hp.total_healing, hp.overheal_percent
               FROM healer_performance hp
               JOIN characters c ON c.id = hp.character_id
               WHERE hp.raid_id = ?""",
            (raid_id,),
        ).fetchall():
            results.append(
                {
                    "name": r["name"],
                    "player_class": r["player_class"],
                    "role": "healer",
                    "total_healing": r["total_healing"],
                    "overheal_percent": r["overheal_percent"],
                }
            )

        for r in conn.execute(
            """SELECT c.name, c.player_class, tp.total_damage_taken, tp.mitigation_percent
               FROM tank_performance tp
               JOIN characters c ON c.id = tp.character_id
               WHERE tp.raid_id = ?""",
            (raid_id,),
        ).fetchall():
            results.append(
                {
                    "name": r["name"],
                    "player_class": r["player_class"],
                    "role": "tank",
                    "total_damage_taken": r["total_damage_taken"],
                    "mitigation_percent": r["mitigation_percent"],
                }
            )

        for r in conn.execute(
            """SELECT c.name, c.player_class, dp.role as sub_role, dp.total_damage
               FROM dps_performance dp
               JOIN characters c ON c.id = dp.character_id
               WHERE dp.raid_id = ?""",
            (raid_id,),
        ).fetchall():
            results.append(
                {
                    "name": r["name"],
                    "player_class": r["player_class"],
                    "role": r["sub_role"],
                    "total_damage": r["total_damage"],
                }
            )

        return results

    def clear_all(self) -> None:
        """Delete all data from the database."""
        conn = self._get_conn()
        conn.execute("DELETE FROM encounter_performance")
        conn.execute("DELETE FROM encounters")
        conn.execute("DELETE FROM raid_group_members")
        conn.execute("DELETE FROM raid_groups")
        conn.execute("DELETE FROM healer_spells")
        conn.execute("DELETE FROM healer_performance")
        conn.execute("DELETE FROM tank_damage_taken")
        conn.execute("DELETE FROM tank_abilities")
        conn.execute("DELETE FROM tank_performance")
        conn.execute("DELETE FROM dps_abilities")
        conn.execute("DELETE FROM dps_performance")
        conn.execute("DELETE FROM consumable_usage")
        conn.execute("DELETE FROM raids")
        conn.execute("DELETE FROM characters")
        conn.commit()

    def get_raid_roster(self, report_id: str) -> list[dict]:
        """Get all characters who participated in a specific raid."""
        conn = self._get_conn()
        raid = conn.execute("SELECT id FROM raids WHERE report_id = ?", (report_id,)).fetchone()
        if not raid:
            return []
        raid_id = raid["id"]

        rows = conn.execute(
            """SELECT DISTINCT c.name, c.player_class,
                CASE
                    WHEN hp.id IS NOT NULL THEN 'healer'
                    WHEN tp.id IS NOT NULL THEN 'tank'
                    WHEN dp.role IS NOT NULL THEN dp.role
                    ELSE 'unknown'
                END as role
               FROM characters c
               LEFT JOIN healer_performance hp ON hp.character_id = c.id AND hp.raid_id = ?
               LEFT JOIN tank_performance tp ON tp.character_id = c.id AND tp.raid_id = ?
               LEFT JOIN dps_performance dp ON dp.character_id = c.id AND dp.raid_id = ?
               WHERE hp.id IS NOT NULL OR tp.id IS NOT NULL OR dp.id IS NOT NULL
               ORDER BY role, c.name""",
            (raid_id, raid_id, raid_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_raid_analysis(self, report_id: str) -> RaidAnalysis | None:
        """Reconstruct a full RaidAnalysis from stored database data."""
        conn = self._get_conn()
        raid_row = conn.execute("SELECT * FROM raids WHERE report_id = ?", (report_id,)).fetchone()
        if not raid_row:
            return None

        raid_id = raid_row["id"]
        metadata = RaidMetadata(
            report_id=raid_row["report_id"],
            title=raid_row["title"],
            owner=raid_row["owner"] or "",
            start_time=raid_row["start_time"],
            end_time=raid_row["end_time"],
        )

        healers = self._load_healers_for_raid(conn, raid_id)
        tanks = self._load_tanks_for_raid(conn, raid_id)
        dps_list = self._load_dps_for_raid(conn, raid_id)
        consumables = self._load_consumables_for_raid(conn, raid_id, report_id)
        interrupts = self._load_interrupts_for_raid(conn, raid_id)
        cancelled_casts = self._load_cancelled_casts_for_raid(conn, raid_id)
        aura_uptimes = self._load_aura_uptimes_for_raid(conn, raid_id)
        totem_uptimes = self._load_totem_uptimes_for_raid(conn, raid_id)
        encounters = self._load_encounters_for_raid(conn, raid_id)

        tank_ids = [
            PlayerIdentity(name=t.name, player_class=t.player_class, source_id=t.source_id, role="tank") for t in tanks
        ]
        healer_ids = [
            PlayerIdentity(name=h.name, player_class=h.player_class, source_id=h.source_id, role="healer")
            for h in healers
        ]
        melee_ids = [
            PlayerIdentity(name=d.name, player_class=d.player_class, source_id=d.source_id, role="melee")
            for d in dps_list
            if d.role == "melee"
        ]
        ranged_ids = [
            PlayerIdentity(name=d.name, player_class=d.player_class, source_id=d.source_id, role="ranged")
            for d in dps_list
            if d.role == "ranged"
        ]

        return RaidAnalysis(
            metadata=metadata,
            composition=RaidComposition(tanks=tank_ids, healers=healer_ids, melee=melee_ids, ranged=ranged_ids),
            healers=healers,
            tanks=tanks,
            dps=dps_list,
            consumables=consumables,
            interrupts=interrupts,
            cancelled_casts=cancelled_casts,
            aura_uptimes=aura_uptimes,
            totem_uptimes=totem_uptimes,
            encounters=encounters,
        )

    def _load_healers_for_raid(self, conn: sqlite3.Connection, raid_id: int) -> list[HealerPerformance]:
        rows = conn.execute(
            """SELECT hp.*, c.name, c.player_class
               FROM healer_performance hp
               JOIN characters c ON c.id = hp.character_id
               WHERE hp.raid_id = ?""",
            (raid_id,),
        ).fetchall()

        perf_ids = [r["id"] for r in rows]
        spells_by_perf: dict[int, list[SpellUsage]] = {pid: [] for pid in perf_ids}
        if perf_ids:
            placeholders = ",".join("?" * len(perf_ids))
            for s in conn.execute(
                f"SELECT * FROM healer_spells WHERE healer_performance_id IN ({placeholders})",
                perf_ids,
            ).fetchall():
                spells_by_perf[s["healer_performance_id"]].append(
                    SpellUsage(
                        spell_id=s["spell_id"],
                        spell_name=_resolve_name(s["spell_id"], s["spell_name"]),
                        casts=s["casts"],
                        total_amount=s["total_healing"],
                    )
                )

        return [
            HealerPerformance(
                name=r["name"],
                player_class=r["player_class"],
                source_id=0,
                total_healing=r["total_healing"],
                total_overhealing=r["total_overhealing"],
                spells=spells_by_perf.get(r["id"], []),
                fear_ward_casts=r["fear_ward_casts"],
                active_time_percent=r["active_time_percent"] or 0.0,
            )
            for r in rows
        ]

    def _load_tanks_for_raid(self, conn: sqlite3.Connection, raid_id: int) -> list[TankPerformance]:
        rows = conn.execute(
            """SELECT tp.*, c.name, c.player_class
               FROM tank_performance tp
               JOIN characters c ON c.id = tp.character_id
               WHERE tp.raid_id = ?""",
            (raid_id,),
        ).fetchall()

        perf_ids = [r["id"] for r in rows]
        taken_by_perf: dict[int, list[SpellUsage]] = {pid: [] for pid in perf_ids}
        abilities_by_perf: dict[int, list[SpellUsage]] = {pid: [] for pid in perf_ids}
        if perf_ids:
            placeholders = ",".join("?" * len(perf_ids))
            for a in conn.execute(
                f"SELECT * FROM tank_damage_taken WHERE tank_performance_id IN ({placeholders})",
                perf_ids,
            ).fetchall():
                taken_by_perf[a["tank_performance_id"]].append(
                    SpellUsage(
                        spell_id=a["spell_id"],
                        spell_name=_resolve_name(a["spell_id"], a["spell_name"]),
                        casts=a["hits"],
                    )
                )
            for a in conn.execute(
                f"SELECT * FROM tank_abilities WHERE tank_performance_id IN ({placeholders})",
                perf_ids,
            ).fetchall():
                abilities_by_perf[a["tank_performance_id"]].append(
                    SpellUsage(
                        spell_id=a["spell_id"],
                        spell_name=_resolve_name(a["spell_id"], a["spell_name"]),
                        casts=a["casts"],
                    )
                )

        return [
            TankPerformance(
                name=r["name"],
                player_class=r["player_class"],
                source_id=0,
                total_damage_taken=r["total_damage_taken"],
                total_mitigated=r["total_mitigated"],
                damage_taken_breakdown=taken_by_perf.get(r["id"], []),
                abilities_used=abilities_by_perf.get(r["id"], []),
                active_time_percent=r["active_time_percent"] or 0.0,
            )
            for r in rows
        ]

    def _load_dps_for_raid(self, conn: sqlite3.Connection, raid_id: int) -> list[DPSPerformance]:
        rows = conn.execute(
            """SELECT dp.*, c.name, c.player_class
               FROM dps_performance dp
               JOIN characters c ON c.id = dp.character_id
               WHERE dp.raid_id = ?""",
            (raid_id,),
        ).fetchall()

        perf_ids = [r["id"] for r in rows]
        abilities_by_perf: dict[int, list[SpellUsage]] = {pid: [] for pid in perf_ids}
        if perf_ids:
            placeholders = ",".join("?" * len(perf_ids))
            for a in conn.execute(
                f"SELECT * FROM dps_abilities WHERE dps_performance_id IN ({placeholders})",
                perf_ids,
            ).fetchall():
                abilities_by_perf[a["dps_performance_id"]].append(
                    SpellUsage(
                        spell_id=a["spell_id"],
                        spell_name=_resolve_name(a["spell_id"], a["spell_name"]),
                        casts=a["casts"],
                        total_amount=a["total_damage"],
                    )
                )

        return [
            DPSPerformance(
                name=r["name"],
                player_class=r["player_class"],
                source_id=0,
                role=r["role"],
                total_damage=r["total_damage"],
                abilities=abilities_by_perf.get(r["id"], []),
                active_time_percent=r["active_time_percent"] or 0.0,
            )
            for r in rows
        ]

    def _load_consumables_for_raid(
        self, conn: sqlite3.Connection, raid_id: int, report_id: str
    ) -> list[ConsumableUsage]:
        rows = conn.execute(
            """SELECT cu.consumable_name, cu.count, cu.timestamps, c.name as player_name
               FROM consumable_usage cu
               JOIN characters c ON c.id = cu.character_id
               WHERE cu.raid_id = ?""",
            (raid_id,),
        ).fetchall()
        roster = self.get_raid_roster(report_id)
        role_map = {r["name"]: r["role"] for r in roster}
        return [
            ConsumableUsage(
                player_name=r["player_name"],
                player_role=role_map.get(r["player_name"], "unknown"),
                report_id=report_id,
                consumable_name=r["consumable_name"],
                count=r["count"],
                timestamps=json.loads(r["timestamps"]) if r["timestamps"] else [],
            )
            for r in rows
        ]

    def _load_interrupts_for_raid(
        self, conn: sqlite3.Connection, raid_id: int
    ) -> list[InterruptUsage]:
        rows = conn.execute(
            """SELECT iu.spell_id, iu.spell_name, iu.count, iu.timestamps,
                      c.name as player_name, c.player_class
               FROM interrupt_usage iu
               JOIN characters c ON c.id = iu.character_id
               WHERE iu.raid_id = ?""",
            (raid_id,),
        ).fetchall()
        return [
            InterruptUsage(
                player_name=r["player_name"],
                player_class=r["player_class"],
                source_id=0,
                spell_id=r["spell_id"],
                spell_name=r["spell_name"],
                count=r["count"],
                timestamps=json.loads(r["timestamps"]) if r["timestamps"] else [],
            )
            for r in rows
        ]

    def _load_cancelled_casts_for_raid(
        self, conn: sqlite3.Connection, raid_id: int
    ) -> list[CancelledCastSummary]:
        rows = conn.execute(
            """SELECT cc.total_casts, cc.cancelled_casts, cc.cancel_rate,
                      c.name as player_name, c.player_class
               FROM cancelled_casts cc
               JOIN characters c ON c.id = cc.character_id
               WHERE cc.raid_id = ?""",
            (raid_id,),
        ).fetchall()
        return [
            CancelledCastSummary(
                player_name=r["player_name"],
                player_class=r["player_class"],
                source_id=0,
                total_casts=r["total_casts"],
                cancelled_casts=r["cancelled_casts"],
                cancel_rate=r["cancel_rate"],
            )
            for r in rows
        ]

    def _load_aura_uptimes_for_raid(
        self, conn: sqlite3.Connection, raid_id: int
    ) -> list[AuraUptime]:
        rows = conn.execute(
            """SELECT au.spell_id, au.spell_name, au.uptime_percent, au.bands_json,
                      e.name as fight_name, e.start_time as fight_start, e.end_time as fight_end
               FROM aura_uptime au
               JOIN encounters e ON e.id = au.encounter_row_id
               WHERE au.raid_id = ?""",
            (raid_id,),
        ).fetchall()
        results = []
        for r in rows:
            bands = []
            if r["bands_json"]:
                for b in json.loads(r["bands_json"]):
                    bands.append(AuraBand(start_time=b["start"], end_time=b["end"]))
            results.append(
                AuraUptime(
                    spell_id=r["spell_id"],
                    spell_name=r["spell_name"],
                    fight_name=r["fight_name"],
                    fight_start=r["fight_start"],
                    fight_end=r["fight_end"],
                    uptime_percent=r["uptime_percent"],
                    bands=bands,
                )
            )
        return results

    def _load_totem_uptimes_for_raid(
        self, conn: sqlite3.Connection, raid_id: int
    ) -> list[AuraUptime]:
        rows = conn.execute(
            """SELECT tu.spell_id, tu.spell_name, tu.uptime_percent, tu.bands_json,
                      e.name as fight_name, e.start_time as fight_start, e.end_time as fight_end
               FROM totem_uptime tu
               JOIN encounters e ON e.id = tu.encounter_row_id
               WHERE tu.raid_id = ?""",
            (raid_id,),
        ).fetchall()
        results = []
        for r in rows:
            bands = []
            if r["bands_json"]:
                for b in json.loads(r["bands_json"]):
                    bands.append(AuraBand(start_time=b["start"], end_time=b["end"]))
            results.append(
                AuraUptime(
                    spell_id=r["spell_id"],
                    spell_name=r["spell_name"],
                    fight_name=r["fight_name"],
                    fight_start=r["fight_start"],
                    fight_end=r["fight_end"],
                    uptime_percent=r["uptime_percent"],
                    bands=bands,
                )
            )
        return results

    def get_encounter_history(
        self,
        encounter_id: int,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> list[dict]:
        """Historical kills of a specific boss across raids."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)
        rows = conn.execute(
            f"""SELECT e.name, e.duration_ms, r.raid_date, r.report_id, r.title,
                      SUM(ep.total_damage) as total_damage,
                      SUM(ep.total_healing) as total_healing,
                      COUNT(ep.id) as player_count
               FROM encounters e
               JOIN raids r ON r.id = e.raid_id
               JOIN encounter_performance ep ON ep.encounter_row_id = e.id
               WHERE e.encounter_id = ?{ds_filter}
               GROUP BY e.id
               ORDER BY r.raid_date DESC""",
            [encounter_id, *ds_params],
        ).fetchall()
        return [dict(r) for r in rows]

    def get_character_encounter_history(self, character_name: str, encounter_id: int) -> list[dict]:
        """A character's performance on a specific boss over time."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT e.name as encounter_name, e.duration_ms,
                      r.raid_date, r.report_id, r.title,
                      ep.role, ep.total_damage, ep.total_healing, ep.total_damage_taken
               FROM encounter_performance ep
               JOIN encounters e ON e.id = ep.encounter_row_id
               JOIN raids r ON r.id = e.raid_id
               JOIN characters c ON c.id = ep.character_id
               WHERE c.name = ? AND e.encounter_id = ? AND r.source = 'guild'
               ORDER BY r.raid_date DESC""",
            (character_name, encounter_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_distinct_encounters(
        self,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> list[dict]:
        """All unique boss encounters in the database with kill counts."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)
        rows = conn.execute(
            f"""SELECT e.encounter_id, e.name,
                       COUNT(DISTINCT e.id) as kill_count
                FROM encounters e
                JOIN raids r ON r.id = e.raid_id
                WHERE 1=1{ds_filter}
                GROUP BY e.encounter_id
                ORDER BY e.name""",
            ds_params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_encounter_player_breakdown(
        self,
        encounter_id: int,
        raid_day: str | None = None,
        raid_size: str | None = None,
        last_n: int | None = None,
        zone: str | None = None,
    ) -> list[dict]:
        """Per-player averages for a specific boss across kills."""
        conn = self._get_conn()
        ds_filter, ds_params = self._build_day_size_filter(raid_day, raid_size, last_n, zone=zone)
        rows = conn.execute(
            f"""SELECT c.name, c.player_class, ep.role,
                       COUNT(*) as kills,
                       CAST(AVG(ep.total_damage) AS INTEGER) as avg_damage,
                       CAST(AVG(ep.total_healing) AS INTEGER) as avg_healing,
                       CAST(AVG(ep.total_damage_taken) AS INTEGER) as avg_damage_taken
                FROM encounter_performance ep
                JOIN encounters e ON e.id = ep.encounter_row_id
                JOIN raids r ON r.id = e.raid_id
                JOIN characters c ON c.id = ep.character_id
                WHERE e.encounter_id = ?{ds_filter}
                GROUP BY c.id, ep.role
                ORDER BY avg_damage DESC""",
            [encounter_id, *ds_params],
        ).fetchall()
        return [dict(r) for r in rows]

    def _load_encounters_for_raid(self, conn: sqlite3.Connection, raid_id: int) -> list[EncounterSummary]:
        enc_rows = conn.execute(
            "SELECT * FROM encounters WHERE raid_id = ? ORDER BY start_time",
            (raid_id,),
        ).fetchall()
        results = []
        for er in enc_rows:
            perf_rows = conn.execute(
                """SELECT ep.*, c.name, c.player_class
                   FROM encounter_performance ep
                   JOIN characters c ON c.id = ep.character_id
                   WHERE ep.encounter_row_id = ?
                   ORDER BY ep.total_damage DESC""",
                (er["id"],),
            ).fetchall()
            players = [
                EncounterPerformance(
                    name=pr["name"],
                    player_class=pr["player_class"],
                    source_id=0,
                    role=pr["role"] or "unknown",
                    total_damage=pr["total_damage"],
                    total_healing=pr["total_healing"],
                    total_damage_taken=pr["total_damage_taken"],
                    active_time_percent=pr["active_time_percent"] or 0.0,
                )
                for pr in perf_rows
            ]
            results.append(
                EncounterSummary(
                    encounter_id=er["encounter_id"],
                    name=er["name"],
                    start_time=er["start_time"],
                    end_time=er["end_time"],
                    duration_ms=er["duration_ms"],
                    players=players,
                )
            )
        return results

    def compare_characters(self, names: list[str], role: str) -> list[dict]:
        """Compare multiple characters' average performance (guild raids only)."""
        conn = self._get_conn()
        results = []
        for name in names:
            if role == "healer":
                row = conn.execute(
                    """SELECT c.name, c.player_class,
                              COUNT(*) as raids,
                              AVG(hp.total_healing) as avg_healing,
                              AVG(hp.overheal_percent) as avg_overheal,
                              AVG(hp.total_dispels) as avg_dispels
                       FROM healer_performance hp
                       JOIN characters c ON c.id = hp.character_id
                       JOIN raids r ON r.id = hp.raid_id
                       WHERE c.name = ? COLLATE NOCASE AND r.source = 'guild'
                       GROUP BY c.id""",
                    (name,),
                ).fetchone()
            elif role == "tank":
                row = conn.execute(
                    """SELECT c.name, c.player_class,
                              COUNT(*) as raids,
                              AVG(tp.total_damage_taken) as avg_taken,
                              AVG(tp.mitigation_percent) as avg_mitigation
                       FROM tank_performance tp
                       JOIN characters c ON c.id = tp.character_id
                       JOIN raids r ON r.id = tp.raid_id
                       WHERE c.name = ? COLLATE NOCASE AND r.source = 'guild'
                       GROUP BY c.id""",
                    (name,),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT c.name, c.player_class,
                              COUNT(*) as raids,
                              AVG(dp.total_damage) as avg_damage
                       FROM dps_performance dp
                       JOIN characters c ON c.id = dp.character_id
                       JOIN raids r ON r.id = dp.raid_id
                       WHERE c.name = ? COLLATE NOCASE AND dp.role = ? AND r.source = 'guild'
                       GROUP BY c.id""",
                    (name, role),
                ).fetchone()

            if row:
                results.append(dict(row))
        return results

    # ── Reference report operations ──

    def get_reference_raids(self, limit: int = 50) -> list[dict]:
        """Get list of all imported reference raids."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT report_id, title, owner, raid_date, imported_at, zone, label, raid_size
               FROM raids WHERE source = 'reference'
               ORDER BY raid_date DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_raid_label(self, report_id: str, label: str) -> None:
        """Set a user-supplied label on a raid (typically a reference raid)."""
        conn = self._get_conn()
        conn.execute("UPDATE raids SET label = ? WHERE report_id = ?", (label, report_id))
        conn.commit()

    def get_raid_source(self, report_id: str) -> str | None:
        """Get the source classification of a raid, or None if not imported."""
        conn = self._get_conn()
        row = conn.execute("SELECT source FROM raids WHERE report_id = ?", (report_id,)).fetchone()
        return row["source"] if row else None

    def get_comparison_aggregates(
        self, source: str = "guild", zone: str | None = None, raid_size: str | None = None
    ) -> dict:
        """Aggregate performance metrics for guild or reference raids."""
        conn = self._get_conn()
        params: list = [source]
        size_clause = ""
        if raid_size == "25-man":
            size_clause = " AND r.raid_size >= 20"
        elif raid_size == "10-man":
            size_clause = " AND r.raid_size BETWEEN 1 AND 19"
        zone_clause = ""
        if zone:
            zone_clause = " AND r.zone = ?"
            params.append(zone)

        base_where = f"r.source = ?{size_clause}{zone_clause}"

        healer = conn.execute(
            f"""SELECT AVG(hp.total_healing) as avg_healing,
                       AVG(hp.overheal_percent) as avg_overheal,
                       AVG(hp.active_time_percent) as avg_active_time,
                       COUNT(DISTINCT hp.character_id) as healer_count
                FROM healer_performance hp
                JOIN raids r ON r.id = hp.raid_id
                WHERE {base_where}""",
            params,
        ).fetchone()

        dps = conn.execute(
            f"""SELECT AVG(dp.total_damage) as avg_damage,
                       AVG(dp.active_time_percent) as avg_active_time,
                       COUNT(DISTINCT dp.character_id) as dps_count
                FROM dps_performance dp
                JOIN raids r ON r.id = dp.raid_id
                WHERE {base_where}""",
            params,
        ).fetchone()

        tank = conn.execute(
            f"""SELECT AVG(tp.mitigation_percent) as avg_mitigation,
                       AVG(tp.total_damage_taken) as avg_damage_taken,
                       AVG(tp.active_time_percent) as avg_active_time,
                       COUNT(DISTINCT tp.character_id) as tank_count
                FROM tank_performance tp
                JOIN raids r ON r.id = tp.raid_id
                WHERE {base_where}""",
            params,
        ).fetchone()

        raid_count = conn.execute(
            f"SELECT COUNT(*) as cnt FROM raids r WHERE {base_where}",
            params,
        ).fetchone()["cnt"]

        return {
            "raid_count": raid_count,
            "avg_healing": healer["avg_healing"],
            "avg_overheal": healer["avg_overheal"],
            "healer_count": healer["healer_count"],
            "avg_damage": dps["avg_damage"],
            "dps_count": dps["dps_count"],
            "avg_mitigation": tank["avg_mitigation"],
            "avg_damage_taken": tank["avg_damage_taken"],
            "tank_count": tank["tank_count"],
        }

    def get_common_encounters(self) -> list[dict]:
        """Get encounters that exist in both guild and reference data."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT DISTINCT e.encounter_id, e.name
               FROM encounters e
               JOIN raids r ON r.id = e.raid_id
               WHERE r.source = 'guild'
                 AND e.encounter_id IN (
                     SELECT e2.encounter_id FROM encounters e2
                     JOIN raids r2 ON r2.id = e2.raid_id
                     WHERE r2.source = 'reference'
                 )
               ORDER BY e.name"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_encounter_comparison(self, encounter_id: int) -> dict:
        """Side-by-side guild vs reference averages for a specific boss."""
        conn = self._get_conn()
        result = {}
        for source in ("guild", "reference"):
            row = conn.execute(
                """SELECT AVG(e.duration_ms) as avg_duration,
                          AVG(ep.total_damage) as avg_damage,
                          AVG(ep.total_healing) as avg_healing,
                          COUNT(DISTINCT e.id) as kill_count
                   FROM encounter_performance ep
                   JOIN encounters e ON e.id = ep.encounter_row_id
                   JOIN raids r ON r.id = e.raid_id
                   WHERE e.encounter_id = ? AND r.source = ?""",
                (encounter_id, source),
            ).fetchone()
            result[source] = dict(row) if row else {}
        return result
