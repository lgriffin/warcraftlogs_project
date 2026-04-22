"""
SQLite database for historical character performance tracking.

Stores per-character, per-raid performance metrics so users can
track trends over time: healing output, damage dealt, mitigation,
consumable habits, etc.
"""

import json
import sqlite3
import os
from datetime import datetime
from typing import Optional

from .models import (
    CharacterHistory,
    ConsumableUsage,
    DPSPerformance,
    DispelUsage,
    HealerPerformance,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidGroup,
    RaidMetadata,
    ResourceUsage,
    SpellUsage,
    TankPerformance,
)

SCHEMA_VERSION = 2

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
    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
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
"""


class PerformanceDB:
    """SQLite database for storing and querying historical character performance."""

    DEFAULT_PATH = "warcraftlogs_history.db"

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or self.DEFAULT_PATH
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
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

        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
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

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # ── Character operations ──

    def _upsert_character(self, name: str, player_class: str, raid_date: str) -> int:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO characters (name, player_class, first_seen, last_seen)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   player_class = excluded.player_class,
                   last_seen = MAX(last_seen, excluded.last_seen)""",
            (name, player_class, raid_date, raid_date),
        )
        cursor = conn.execute("SELECT id FROM characters WHERE name = ?", (name,))
        return cursor.fetchone()["id"]

    def _upsert_raid(self, metadata: RaidMetadata) -> int:
        conn = self._get_conn()
        raid_date = metadata.date.strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO raids (report_id, title, owner, raid_date, start_time, end_time)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(report_id) DO UPDATE SET
                   title = excluded.title""",
            (metadata.report_id, metadata.title, metadata.owner, raid_date,
             metadata.start_time, metadata.end_time),
        )
        cursor = conn.execute("SELECT id FROM raids WHERE report_id = ?", (metadata.report_id,))
        return cursor.fetchone()["id"]

    # ── Import a full raid analysis ──

    def import_raid(self, analysis: RaidAnalysis) -> None:
        """Import all performance data from a completed raid analysis."""
        conn = self._get_conn()
        raid_date = analysis.metadata.date.strftime("%Y-%m-%d %H:%M:%S")
        raid_id = self._upsert_raid(analysis.metadata)

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

        conn.commit()

    def _import_healer(self, conn: sqlite3.Connection, char_id: int, raid_id: int, h: HealerPerformance) -> None:
        total_dispels = sum(d.casts for d in h.dispels)
        conn.execute(
            """INSERT INTO healer_performance
               (character_id, raid_id, total_healing, total_overhealing, overheal_percent, fear_ward_casts, total_dispels)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(character_id, raid_id) DO UPDATE SET
                   total_healing = excluded.total_healing,
                   total_overhealing = excluded.total_overhealing,
                   overheal_percent = excluded.overheal_percent,
                   fear_ward_casts = excluded.fear_ward_casts,
                   total_dispels = excluded.total_dispels""",
            (char_id, raid_id, h.total_healing, h.total_overhealing,
             h.overheal_percent, h.fear_ward_casts, total_dispels),
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
               (character_id, raid_id, total_damage_taken, total_mitigated, mitigation_percent)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(character_id, raid_id) DO UPDATE SET
                   total_damage_taken = excluded.total_damage_taken,
                   total_mitigated = excluded.total_mitigated,
                   mitigation_percent = excluded.mitigation_percent""",
            (char_id, raid_id, t.total_damage_taken, t.total_mitigated, t.mitigation_percent),
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
            """INSERT INTO dps_performance (character_id, raid_id, role, total_damage)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(character_id, raid_id) DO UPDATE SET
                   role = excluded.role,
                   total_damage = excluded.total_damage""",
            (char_id, raid_id, d.role, d.total_damage),
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

    def get_character_history(self, character_name: str) -> Optional[CharacterHistory]:
        """Get historical performance summary for a character."""
        conn = self._get_conn()
        char = conn.execute(
            "SELECT * FROM characters WHERE name = ?", (character_name,)
        ).fetchone()
        if not char:
            return None

        char_id = char["id"]

        raid_count = conn.execute(
            """SELECT COUNT(DISTINCT raid_id) as cnt FROM (
                SELECT raid_id FROM healer_performance WHERE character_id = ?
                UNION SELECT raid_id FROM tank_performance WHERE character_id = ?
                UNION SELECT raid_id FROM dps_performance WHERE character_id = ?
            )""",
            (char_id, char_id, char_id),
        ).fetchone()["cnt"]

        avg_healing = conn.execute(
            "SELECT AVG(total_healing) as avg FROM healer_performance WHERE character_id = ?",
            (char_id,),
        ).fetchone()["avg"]

        avg_damage = conn.execute(
            "SELECT AVG(total_damage) as avg FROM dps_performance WHERE character_id = ?",
            (char_id,),
        ).fetchone()["avg"]

        avg_mit = conn.execute(
            "SELECT AVG(mitigation_percent) as avg FROM tank_performance WHERE character_id = ?",
            (char_id,),
        ).fetchone()["avg"]

        total_consumes = conn.execute(
            "SELECT COALESCE(SUM(count), 0) as total FROM consumable_usage WHERE character_id = ?",
            (char_id,),
        ).fetchone()["total"]

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
        )

    def get_all_characters(self) -> list[CharacterHistory]:
        """Get summary for all tracked characters."""
        conn = self._get_conn()
        rows = conn.execute("SELECT name FROM characters ORDER BY name").fetchall()
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
            """SELECT r.raid_date, r.title, r.report_id,
                      hp.total_healing, hp.total_overhealing, hp.overheal_percent,
                      hp.fear_ward_casts, hp.total_dispels
               FROM healer_performance hp
               JOIN characters c ON c.id = hp.character_id
               JOIN raids r ON r.id = hp.raid_id
               WHERE c.name = ?
               ORDER BY r.raid_date DESC
               LIMIT ?""",
            (character_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_tank_trend(self, character_name: str, limit: int = 20) -> list[dict]:
        """Get tank performance over time for a character."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.title, r.report_id,
                      tp.total_damage_taken, tp.total_mitigated, tp.mitigation_percent
               FROM tank_performance tp
               JOIN characters c ON c.id = tp.character_id
               JOIN raids r ON r.id = tp.raid_id
               WHERE c.name = ?
               ORDER BY r.raid_date DESC
               LIMIT ?""",
            (character_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dps_trend(self, character_name: str, limit: int = 20) -> list[dict]:
        """Get DPS performance over time for a character."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.title, r.report_id,
                      dp.role, dp.total_damage
               FROM dps_performance dp
               JOIN characters c ON c.id = dp.character_id
               JOIN raids r ON r.id = dp.raid_id
               WHERE c.name = ?
               ORDER BY r.raid_date DESC
               LIMIT ?""",
            (character_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_healer_spell_trend(self, character_name: str, limit: int = 20) -> list[dict]:
        """Get per-spell healing data across raids for a character."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.title, hs.spell_name, hs.casts, hs.total_healing
               FROM healer_spells hs
               JOIN healer_performance hp ON hp.id = hs.healer_performance_id
               JOIN characters c ON c.id = hp.character_id
               JOIN raids r ON r.id = hp.raid_id
               WHERE c.name = ?
               ORDER BY r.raid_date DESC
               LIMIT ?""",
            (character_name, limit * 20),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dps_ability_trend(self, character_name: str, limit: int = 20) -> list[dict]:
        """Get per-ability damage data across raids for a character."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.title, da.spell_name, da.casts, da.total_damage
               FROM dps_abilities da
               JOIN dps_performance dp ON dp.id = da.dps_performance_id
               JOIN characters c ON c.id = dp.character_id
               JOIN raids r ON r.id = dp.raid_id
               WHERE c.name = ?
               ORDER BY r.raid_date DESC
               LIMIT ?""",
            (character_name, limit * 20),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_consumable_trend(self, character_name: str, limit: int = 20) -> list[dict]:
        """Get consumable usage over time for a character (all rows, for charting)."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT r.raid_date, r.title, r.report_id,
                      cu.consumable_name, cu.count
               FROM consumable_usage cu
               JOIN characters c ON c.id = cu.character_id
               JOIN raids r ON r.id = cu.raid_id
               WHERE c.name = ?
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
               WHERE c.name = ?
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
                   WHERE c.name = ? AND cu.raid_id = ?""",
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

    def get_raid_list(self, limit: int = 50) -> list[dict]:
        """Get list of all imported raids."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT report_id, title, owner, raid_date, imported_at
               FROM raids ORDER BY raid_date DESC LIMIT ?""",
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
            "(SELECT id FROM healer_performance WHERE raid_id = ?)", (raid_id,))
        conn.execute("DELETE FROM healer_performance WHERE raid_id = ?", (raid_id,))

        conn.execute(
            "DELETE FROM dps_abilities WHERE dps_performance_id IN "
            "(SELECT id FROM dps_performance WHERE raid_id = ?)", (raid_id,))
        conn.execute("DELETE FROM dps_performance WHERE raid_id = ?", (raid_id,))

        conn.execute(
            "DELETE FROM tank_damage_taken WHERE tank_performance_id IN "
            "(SELECT id FROM tank_performance WHERE raid_id = ?)", (raid_id,))
        conn.execute(
            "DELETE FROM tank_abilities WHERE tank_performance_id IN "
            "(SELECT id FROM tank_performance WHERE raid_id = ?)", (raid_id,))
        conn.execute("DELETE FROM tank_performance WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM consumable_usage WHERE raid_id = ?", (raid_id,))
        conn.execute("DELETE FROM raids WHERE id = ?", (raid_id,))
        conn.commit()

    def is_raid_imported(self, report_id: str) -> bool:
        """Check if a raid has already been imported."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id FROM raids WHERE report_id = ?", (report_id,)
        ).fetchone()
        return row is not None

    def get_imported_report_codes(self) -> set[str]:
        """Return the set of all report codes stored in the database."""
        conn = self._get_conn()
        rows = conn.execute("SELECT report_id FROM raids").fetchall()
        return {r["report_id"] for r in rows}

    # ── Raid Group operations ──

    def create_raid_group(self, name: str, raid_days: list[str] | None = None) -> RaidGroup:
        conn = self._get_conn()
        days_json = json.dumps(raid_days or [])
        conn.execute(
            "INSERT INTO raid_groups (name, raid_days) VALUES (?, ?)",
            (name, days_json),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM raid_groups WHERE name = ?", (name,)
        ).fetchone()
        return RaidGroup(
            id=row["id"], name=row["name"],
            raid_days=json.loads(row["raid_days"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def update_raid_group(self, group_id: int, name: str | None = None,
                          raid_days: list[str] | None = None) -> None:
        conn = self._get_conn()
        if name is not None:
            conn.execute("UPDATE raid_groups SET name = ? WHERE id = ?", (name, group_id))
        if raid_days is not None:
            conn.execute("UPDATE raid_groups SET raid_days = ? WHERE id = ?",
                         (json.dumps(raid_days), group_id))
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
            groups.append(RaidGroup(
                id=r["id"], name=r["name"],
                raid_days=json.loads(r["raid_days"]),
                created_at=datetime.fromisoformat(r["created_at"]),
                members=[m["name"] for m in members],
            ))
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
            id=r["id"], name=r["name"],
            raid_days=json.loads(r["raid_days"]),
            created_at=datetime.fromisoformat(r["created_at"]),
            members=[m["name"] for m in members],
        )

    def add_raid_group_member(self, group_id: int, character_name: str) -> bool:
        conn = self._get_conn()
        char = conn.execute(
            "SELECT id FROM characters WHERE name = ?", (character_name,)
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
            "SELECT id FROM characters WHERE name = ?", (character_name,)
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
               WHERE c.name = ?
               ORDER BY rg.name""",
            (character_name,),
        ).fetchall()
        return [r["name"] for r in rows]

    def clear_all(self) -> None:
        """Delete all data from the database."""
        conn = self._get_conn()
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

    def get_raid_analysis(self, report_id: str) -> Optional[RaidAnalysis]:
        """Reconstruct a full RaidAnalysis from stored database data."""
        conn = self._get_conn()
        raid_row = conn.execute(
            "SELECT * FROM raids WHERE report_id = ?", (report_id,)
        ).fetchone()
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

        tank_ids = [PlayerIdentity(name=t.name, player_class=t.player_class, source_id=t.source_id, role="tank") for t in tanks]
        healer_ids = [PlayerIdentity(name=h.name, player_class=h.player_class, source_id=h.source_id, role="healer") for h in healers]
        melee_ids = [PlayerIdentity(name=d.name, player_class=d.player_class, source_id=d.source_id, role="melee") for d in dps_list if d.role == "melee"]
        ranged_ids = [PlayerIdentity(name=d.name, player_class=d.player_class, source_id=d.source_id, role="ranged") for d in dps_list if d.role == "ranged"]

        return RaidAnalysis(
            metadata=metadata,
            composition=RaidComposition(tanks=tank_ids, healers=healer_ids, melee=melee_ids, ranged=ranged_ids),
            healers=healers,
            tanks=tanks,
            dps=dps_list,
            consumables=consumables,
        )

    def _load_healers_for_raid(self, conn: sqlite3.Connection, raid_id: int) -> list[HealerPerformance]:
        rows = conn.execute(
            """SELECT hp.*, c.name, c.player_class
               FROM healer_performance hp
               JOIN characters c ON c.id = hp.character_id
               WHERE hp.raid_id = ?""",
            (raid_id,),
        ).fetchall()
        results = []
        for r in rows:
            spells_rows = conn.execute(
                "SELECT * FROM healer_spells WHERE healer_performance_id = ?", (r["id"],)
            ).fetchall()
            spells = [SpellUsage(spell_id=s["spell_id"], spell_name=s["spell_name"],
                                 casts=s["casts"], total_amount=s["total_healing"]) for s in spells_rows]
            results.append(HealerPerformance(
                name=r["name"], player_class=r["player_class"], source_id=0,
                total_healing=r["total_healing"], total_overhealing=r["total_overhealing"],
                spells=spells, fear_ward_casts=r["fear_ward_casts"],
            ))
        return results

    def _load_tanks_for_raid(self, conn: sqlite3.Connection, raid_id: int) -> list[TankPerformance]:
        rows = conn.execute(
            """SELECT tp.*, c.name, c.player_class
               FROM tank_performance tp
               JOIN characters c ON c.id = tp.character_id
               WHERE tp.raid_id = ?""",
            (raid_id,),
        ).fetchall()
        results = []
        for r in rows:
            taken_rows = conn.execute(
                "SELECT * FROM tank_damage_taken WHERE tank_performance_id = ?", (r["id"],)
            ).fetchall()
            taken_breakdown = [SpellUsage(spell_id=a["spell_id"], spell_name=a["spell_name"],
                                          casts=a["hits"]) for a in taken_rows]

            ability_rows = conn.execute(
                "SELECT * FROM tank_abilities WHERE tank_performance_id = ?", (r["id"],)
            ).fetchall()
            abilities = [SpellUsage(spell_id=a["spell_id"], spell_name=a["spell_name"],
                                    casts=a["casts"]) for a in ability_rows]

            results.append(TankPerformance(
                name=r["name"], player_class=r["player_class"], source_id=0,
                total_damage_taken=r["total_damage_taken"], total_mitigated=r["total_mitigated"],
                damage_taken_breakdown=taken_breakdown, abilities_used=abilities,
            ))
        return results

    def _load_dps_for_raid(self, conn: sqlite3.Connection, raid_id: int) -> list[DPSPerformance]:
        rows = conn.execute(
            """SELECT dp.*, c.name, c.player_class
               FROM dps_performance dp
               JOIN characters c ON c.id = dp.character_id
               WHERE dp.raid_id = ?""",
            (raid_id,),
        ).fetchall()
        results = []
        for r in rows:
            ability_rows = conn.execute(
                "SELECT * FROM dps_abilities WHERE dps_performance_id = ?", (r["id"],)
            ).fetchall()
            abilities = [SpellUsage(spell_id=a["spell_id"], spell_name=a["spell_name"],
                                    casts=a["casts"], total_amount=a["total_damage"]) for a in ability_rows]
            results.append(DPSPerformance(
                name=r["name"], player_class=r["player_class"], source_id=0,
                role=r["role"], total_damage=r["total_damage"], abilities=abilities,
            ))
        return results

    def _load_consumables_for_raid(self, conn: sqlite3.Connection, raid_id: int,
                                    report_id: str) -> list[ConsumableUsage]:
        rows = conn.execute(
            """SELECT cu.consumable_name, cu.count, cu.timestamps, c.name as player_name
               FROM consumable_usage cu
               JOIN characters c ON c.id = cu.character_id
               WHERE cu.raid_id = ?""",
            (raid_id,),
        ).fetchall()
        roster = self.get_raid_roster(report_id)
        role_map = {r["name"]: r["role"] for r in roster}
        return [ConsumableUsage(
            player_name=r["player_name"],
            player_role=role_map.get(r["player_name"], "unknown"),
            report_id=report_id,
            consumable_name=r["consumable_name"],
            count=r["count"],
            timestamps=json.loads(r["timestamps"]) if r["timestamps"] else [],
        ) for r in rows]

    def compare_characters(self, names: list[str], role: str) -> list[dict]:
        """Compare multiple characters' average performance."""
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
                       WHERE c.name = ?
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
                       WHERE c.name = ?
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
                       WHERE c.name = ? AND dp.role = ?
                       GROUP BY c.id""",
                    (name, role),
                ).fetchone()

            if row:
                results.append(dict(row))
        return results
