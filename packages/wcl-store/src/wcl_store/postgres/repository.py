"""``RaidRepository`` on Postgres, through SQLAlchemy Core and psycopg 3.

Each public method runs in one transaction, so a failed import leaves nothing behind. Queries follow the
SQLite backend statement for statement; where SQLite relies on ``COLLATE NOCASE`` this matches on
``nocase(...)`` (ASCII-only folding), and where SQLite orders text by bytes this orders with ``COLLATE "C"``,
so both backends return rows in the same order whatever the database's default collation.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import (
    Connection,
    Engine,
    and_,
    case,
    create_engine,
    delete,
    func,
    literal,
    null,
    or_,
    select,
    text,
    union,
    union_all,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from wcl_core.models import (
    AuraUptime,
    CancelledCastDetail,
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
    RaidMetadata,
    SpellUsage,
    TankPerformance,
)

from .. import _codec
from ..errors import StorageError
from . import schema as t
from .schema import NOW_TEXT, nocase

_F = TypeVar("_F", bound=Callable[..., Any])


class PostgresStorageError(StorageError):
    """A database error from ``PostgresRaidRepository``; the SQLAlchemy error is the ``__cause__``."""


def _storage_errors(method: _F) -> _F:
    @functools.wraps(method)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except SQLAlchemyError as e:
            raise PostgresStorageError(str(e)) from e

    return wrapper  # type: ignore[return-value]


def make_engine(url: str, **kwargs: Any) -> Engine:
    """Engine for ``url``; a plain ``postgresql://`` URL uses the psycopg 3 driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return create_engine(url, **kwargs)


def _nocase_eq(column: Any, value: str) -> Any:
    return nocase(column) == nocase(value)


def _c(expr: Any) -> Any:
    """Byte-order collation, matching SQLite's default ordering of text."""
    return expr.collate("C")


def _dicts(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in rows]


def _raid_date(metadata: RaidMetadata) -> str:
    date: datetime = metadata.date
    return date.strftime("%Y-%m-%d %H:%M:%S")


def _upsert(table: Any, values: dict[str, Any], keys: Sequence[Any], update_cols: Sequence[str]) -> Any:
    stmt = insert(table).values(**values)
    return stmt.on_conflict_do_update(
        index_elements=list(keys), set_={c: getattr(stmt.excluded, c) for c in update_cols}
    )


class PostgresRaidRepository:
    """Postgres ``RaidRepository``. Pass a URL or an existing SQLAlchemy engine.

    The schema must already be at the latest migration: run ``wcl_store.postgres.upgrade(url)`` on deploy.
    ``close()`` disposes the engine only when this object created it.
    """

    def __init__(self, url_or_engine: str | Engine, **engine_kwargs: Any):
        if isinstance(url_or_engine, str):
            self._engine = make_engine(url_or_engine, **engine_kwargs)
            self._owns_engine = True
        else:
            self._engine = url_or_engine
            self._owns_engine = False

    def close(self) -> None:
        if self._owns_engine:
            self._engine.dispose()

    def __enter__(self) -> PostgresRaidRepository:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ── Characters and raids (write helpers) ──

    def _upsert_character(self, conn: Connection, name: str, player_class: str, raid_date: str) -> int:
        stmt = insert(t.characters).values(
            name=name, player_class=player_class, first_seen=raid_date, last_seen=raid_date
        )
        upsert = stmt.on_conflict_do_update(
            index_elements=[nocase(t.characters.c.name)],
            set_={
                "player_class": stmt.excluded.player_class,
                "last_seen": func.greatest(t.characters.c.last_seen, stmt.excluded.last_seen),
            },
        ).returning(t.characters.c.id)
        return conn.execute(upsert).scalar_one()

    def _upsert_raid(self, conn: Connection, metadata: RaidMetadata, source: str) -> int:
        stmt = insert(t.raids).values(
            report_id=metadata.report_id,
            title=metadata.title,
            owner=metadata.owner,
            raid_date=_raid_date(metadata),
            start_time=metadata.start_time,
            end_time=metadata.end_time,
            zone=metadata.zone,
            source=source,
        )
        upsert = stmt.on_conflict_do_update(
            index_elements=[t.raids.c.report_id],
            set_={
                "title": stmt.excluded.title,
                "zone": func.coalesce(stmt.excluded.zone, t.raids.c.zone),
                "imported_at": NOW_TEXT,
            },
        ).returning(t.raids.c.id)
        return conn.execute(upsert).scalar_one()

    def _raid_id(self, conn: Connection, report_id: str) -> int | None:
        return conn.execute(select(t.raids.c.id).where(t.raids.c.report_id == report_id)).scalar_one_or_none()

    def _delete_raid_rows(self, conn: Connection, raid_id: int, keep_raid_row: bool = False) -> None:
        # Child rows of the per-role tables and of encounters go by ON DELETE CASCADE.
        for table in (
            t.healer_performance,
            t.dps_performance,
            t.tank_performance,
            t.consumable_usage,
            t.interrupt_usage,
            t.cancelled_casts,
            t.cancelled_cast_spells,
            t.aura_uptime,
            t.totem_uptime,
            t.encounters,
            t.role_override_raids,
        ):
            conn.execute(delete(table).where(table.c.raid_id == raid_id))
        if not keep_raid_row:
            conn.execute(delete(t.raids).where(t.raids.c.id == raid_id))

    # ── Raids ──

    @_storage_errors
    def import_raid(self, analysis: RaidAnalysis, source: str = "guild") -> None:
        with self._engine.begin() as conn:
            self._write_raid(conn, analysis, source)

    @_storage_errors
    def replace_raid_analysis(self, analysis: RaidAnalysis, source: str = "guild") -> None:
        with self._engine.begin() as conn:
            raid_id = self._raid_id(conn, analysis.metadata.report_id)
            if raid_id is not None:
                self._delete_raid_rows(conn, raid_id, keep_raid_row=True)
            self._write_raid(conn, analysis, source)

    def _write_raid(self, conn: Connection, analysis: RaidAnalysis, source: str) -> None:
        raid_date = _raid_date(analysis.metadata)
        raid_id = self._upsert_raid(conn, analysis.metadata, source)

        raid_size = len(analysis.composition.all_players)
        if raid_size > 0:
            conn.execute(update(t.raids).where(t.raids.c.id == raid_id).values(raid_size=raid_size))

        def char(name: str, player_class: str) -> int:
            return self._upsert_character(conn, name, player_class, raid_date)

        conn.execute(delete(t.healer_performance).where(t.healer_performance.c.raid_id == raid_id))
        for h in analysis.healers:
            self._write_healer(conn, char(h.name, h.player_class), raid_id, h)

        conn.execute(delete(t.tank_performance).where(t.tank_performance.c.raid_id == raid_id))
        for tank in analysis.tanks:
            self._write_tank(conn, char(tank.name, tank.player_class), raid_id, tank)

        conn.execute(delete(t.dps_performance).where(t.dps_performance.c.raid_id == raid_id))
        for d in analysis.dps:
            self._write_dps(conn, char(d.name, d.player_class), raid_id, d)

        for cu in analysis.consumables:
            player = analysis.composition.get_player(cu.player_name)
            values = {
                "character_id": char(cu.player_name, player.player_class if player else "Unknown"),
                "raid_id": raid_id,
                "consumable_name": cu.consumable_name,
                "count": cu.count,
                "timestamps": _codec.dump_list(cu.timestamps),
            }
            conn.execute(
                _upsert(
                    t.consumable_usage,
                    values,
                    ["character_id", "raid_id", "consumable_name"],
                    ["count", "timestamps"],
                )
            )

        for iu in analysis.interrupts:
            values = {
                "character_id": char(iu.player_name, iu.player_class),
                "raid_id": raid_id,
                "spell_id": iu.spell_id,
                "spell_name": iu.spell_name,
                "count": iu.count,
                "timestamps": _codec.dump_list(iu.timestamps),
            }
            conn.execute(
                _upsert(
                    t.interrupt_usage,
                    values,
                    ["character_id", "raid_id", "spell_id"],
                    ["spell_name", "count", "timestamps"],
                )
            )

        for cc in analysis.cancelled_casts:
            char_id = char(cc.player_name, cc.player_class)
            values = {
                "character_id": char_id,
                "raid_id": raid_id,
                "total_casts": cc.total_casts,
                "cancelled_casts": cc.cancelled_casts,
                "cancel_rate": cc.cancel_rate,
            }
            conn.execute(
                _upsert(
                    t.cancelled_casts,
                    values,
                    ["character_id", "raid_id"],
                    ["total_casts", "cancelled_casts", "cancel_rate"],
                )
            )
            for detail in cc.spell_details:
                values = {
                    "character_id": char_id,
                    "raid_id": raid_id,
                    "spell_id": detail.spell_id,
                    "spell_name": detail.spell_name,
                    "total_casts": detail.total_casts,
                    "cancelled_casts": detail.cancelled_casts,
                    "cancel_rate": detail.cancel_rate,
                    "timestamps": _codec.dump_list(detail.timestamps),
                    "correlations": _codec.dump_correlations(detail.correlations),
                    "next_casts": _codec.dump_next_casts(detail.next_casts),
                }
                conn.execute(
                    _upsert(
                        t.cancelled_cast_spells,
                        values,
                        ["character_id", "raid_id", "spell_id"],
                        [
                            "spell_name",
                            "total_casts",
                            "cancelled_casts",
                            "cancel_rate",
                            "timestamps",
                            "correlations",
                            "next_casts",
                        ],
                    )
                )

        if analysis.encounters:
            self._write_encounters(conn, raid_id, analysis.encounters, char)
        if analysis.aura_uptimes:
            self._write_uptimes(conn, t.aura_uptime, raid_id, analysis.aura_uptimes)
        if analysis.totem_uptimes:
            self._write_uptimes(conn, t.totem_uptime, raid_id, analysis.totem_uptimes)

        conn.execute(delete(t.role_override_raids).where(t.role_override_raids.c.raid_id == raid_id))
        if analysis.role_overrides_applied:
            conn.execute(
                insert(t.role_override_raids),
                [
                    {"raid_id": raid_id, "character_name": name, "detected_role": detected}
                    for name, detected in analysis.role_overrides_applied.items()
                ],
            )

    def _write_healer(self, conn: Connection, char_id: int, raid_id: int, h: HealerPerformance) -> None:
        values = {
            "character_id": char_id,
            "raid_id": raid_id,
            "total_healing": h.total_healing,
            "total_overhealing": h.total_overhealing,
            "overheal_percent": h.overheal_percent,
            "fear_ward_casts": h.fear_ward_casts,
            "total_dispels": sum(d.casts for d in h.dispels),
            "active_time_percent": h.active_time_percent,
        }
        perf_id: int = conn.execute(
            _upsert(
                t.healer_performance,
                values,
                ["character_id", "raid_id"],
                [k for k in values if k not in ("character_id", "raid_id")],
            ).returning(t.healer_performance.c.id)
        ).scalar_one()
        conn.execute(delete(t.healer_spells).where(t.healer_spells.c.healer_performance_id == perf_id))
        if h.spells:
            conn.execute(
                insert(t.healer_spells),
                [
                    {
                        "healer_performance_id": perf_id,
                        "spell_id": s.spell_id,
                        "spell_name": s.spell_name,
                        "casts": s.casts,
                        "total_healing": s.total_amount,
                    }
                    for s in h.spells
                ],
            )

    def _write_tank(self, conn: Connection, char_id: int, raid_id: int, tank: TankPerformance) -> None:
        values = {
            "character_id": char_id,
            "raid_id": raid_id,
            "total_damage_taken": tank.total_damage_taken,
            "total_mitigated": tank.total_mitigated,
            "mitigation_percent": tank.mitigation_percent,
            "active_time_percent": tank.active_time_percent,
        }
        perf_id: int = conn.execute(
            _upsert(
                t.tank_performance,
                values,
                ["character_id", "raid_id"],
                [k for k in values if k not in ("character_id", "raid_id")],
            ).returning(t.tank_performance.c.id)
        ).scalar_one()
        conn.execute(delete(t.tank_damage_taken).where(t.tank_damage_taken.c.tank_performance_id == perf_id))
        if tank.damage_taken_breakdown:
            conn.execute(
                insert(t.tank_damage_taken),
                [
                    {
                        "tank_performance_id": perf_id,
                        "spell_id": s.spell_id,
                        "spell_name": s.spell_name,
                        "hits": s.casts,
                    }
                    for s in tank.damage_taken_breakdown
                ],
            )
        conn.execute(delete(t.tank_abilities).where(t.tank_abilities.c.tank_performance_id == perf_id))
        if tank.abilities_used:
            conn.execute(
                insert(t.tank_abilities),
                [
                    {
                        "tank_performance_id": perf_id,
                        "spell_id": s.spell_id,
                        "spell_name": s.spell_name,
                        "casts": s.casts,
                    }
                    for s in tank.abilities_used
                ],
            )

    def _write_dps(self, conn: Connection, char_id: int, raid_id: int, d: DPSPerformance) -> None:
        values = {
            "character_id": char_id,
            "raid_id": raid_id,
            "role": d.role,
            "total_damage": d.total_damage,
            "active_time_percent": d.active_time_percent,
        }
        perf_id: int = conn.execute(
            _upsert(
                t.dps_performance,
                values,
                ["character_id", "raid_id"],
                ["role", "total_damage", "active_time_percent"],
            ).returning(t.dps_performance.c.id)
        ).scalar_one()
        conn.execute(delete(t.dps_abilities).where(t.dps_abilities.c.dps_performance_id == perf_id))
        if d.abilities:
            conn.execute(
                insert(t.dps_abilities),
                [
                    {
                        "dps_performance_id": perf_id,
                        "spell_id": a.spell_id,
                        "spell_name": a.spell_name,
                        "casts": a.casts,
                        "total_damage": a.total_amount,
                    }
                    for a in d.abilities
                ],
            )

    def _write_encounters(
        self,
        conn: Connection,
        raid_id: int,
        encounters: list[EncounterSummary],
        char: Callable[[str, str], int],
    ) -> None:
        conn.execute(delete(t.encounters).where(t.encounters.c.raid_id == raid_id))
        for enc in encounters:
            enc_row_id: int = conn.execute(
                insert(t.encounters)
                .values(
                    raid_id=raid_id,
                    encounter_id=enc.encounter_id,
                    name=enc.name,
                    start_time=enc.start_time,
                    end_time=enc.end_time,
                    duration_ms=enc.duration_ms,
                    boss_events=_codec.dump_boss_events(enc.boss_events),
                )
                .returning(t.encounters.c.id)
            ).scalar_one()
            for p in enc.players:
                values = {
                    "encounter_row_id": enc_row_id,
                    "character_id": char(p.name, p.player_class),
                    "role": p.role,
                    "total_damage": p.total_damage,
                    "total_healing": p.total_healing,
                    "total_damage_taken": p.total_damage_taken,
                    "active_time_percent": p.active_time_percent,
                }
                conn.execute(
                    _upsert(
                        t.encounter_performance,
                        values,
                        ["encounter_row_id", "character_id"],
                        ["role", "total_damage", "total_healing", "total_damage_taken", "active_time_percent"],
                    )
                )

    def _write_uptimes(self, conn: Connection, table: Any, raid_id: int, uptimes: list[AuraUptime]) -> None:
        conn.execute(delete(table).where(table.c.raid_id == raid_id))
        for u in uptimes:
            # As in SQLite: the first encounter starting at the fight's start time.
            enc_row_id: int | None = conn.execute(
                select(t.encounters.c.id)
                .where(t.encounters.c.raid_id == raid_id, t.encounters.c.start_time == u.fight_start)
                .order_by(t.encounters.c.id)
                .limit(1)
            ).scalar_one_or_none()
            if enc_row_id is None:
                continue
            values = {
                "raid_id": raid_id,
                "encounter_row_id": enc_row_id,
                "spell_id": u.spell_id,
                "spell_name": u.spell_name,
                "uptime_percent": u.uptime_percent,
                "bands_json": _codec.dump_bands(u.bands),
            }
            conn.execute(
                _upsert(
                    table,
                    values,
                    ["raid_id", "encounter_row_id", "spell_id"],
                    ["spell_name", "uptime_percent", "bands_json"],
                )
            )

    @_storage_errors
    def delete_raid(self, report_id: str) -> None:
        with self._engine.begin() as conn:
            raid_id = self._raid_id(conn, report_id)
            if raid_id is not None:
                self._delete_raid_rows(conn, raid_id)

    @_storage_errors
    def is_raid_imported(self, report_id: str) -> bool:
        with self._engine.connect() as conn:
            return self._raid_id(conn, report_id) is not None

    @_storage_errors
    def get_imported_report_codes(self) -> dict[str, str]:
        with self._engine.connect() as conn:
            rows = conn.execute(select(t.raids.c.report_id, t.raids.c.imported_at))
            return {r.report_id: r.imported_at for r in rows}

    @_storage_errors
    def count_raids(self, source: str = "guild") -> int:
        with self._engine.connect() as conn:
            query = select(func.count()).select_from(t.raids).where(t.raids.c.source == source)
            return int(conn.execute(query).scalar_one())

    @_storage_errors
    def get_raid_list(self, limit: int = 50) -> list[dict[str, Any]]:
        r = t.raids.c
        with self._engine.connect() as conn:
            return _dicts(
                conn.execute(
                    select(r.report_id, r.title, r.owner, r.raid_date, r.imported_at)
                    .where(r.source == "guild")
                    .order_by(_c(r.raid_date).desc())
                    .limit(limit)
                )
            )

    @_storage_errors
    def get_raids_by_source(self, source: str = "guild", limit: int = 50) -> list[dict[str, Any]]:
        r = t.raids.c
        with self._engine.connect() as conn:
            return _dicts(
                conn.execute(
                    select(r.report_id, r.title, r.owner, r.raid_date, r.imported_at, r.zone, r.raid_size, r.label)
                    .where(r.source == source)
                    .order_by(_c(r.raid_date).desc())
                    .limit(limit)
                )
            )

    @_storage_errors
    def set_raid_label(self, report_id: str, label: str | None) -> None:
        with self._engine.begin() as conn:
            conn.execute(update(t.raids).where(t.raids.c.report_id == report_id).values(label=label or None))

    @_storage_errors
    def get_healing_by_raid(self, since: str) -> list[dict[str, Any]]:
        r, c, hp = t.raids.c, t.characters.c, t.healer_performance
        stmt = (
            select(
                r.report_id,
                r.raid_date,
                c.name,
                c.player_class,
                hp.c.total_healing.label("healing"),
                hp.c.total_overhealing.label("overhealing"),
            )
            .select_from(hp.join(t.raids, t.raids.c.id == hp.c.raid_id).join(t.characters, c.id == hp.c.character_id))
            .where(r.source == "guild", _c(r.raid_date) >= since)
            .order_by(_c(r.raid_date), _c(r.report_id), _c(c.name))
        )
        with self._engine.connect() as conn:
            return _dicts(conn.execute(stmt))

    @_storage_errors
    def get_raid_source(self, report_id: str) -> str | None:
        with self._engine.connect() as conn:
            return conn.execute(select(t.raids.c.source).where(t.raids.c.report_id == report_id)).scalar_one_or_none()

    @_storage_errors
    def get_raid_roster(self, report_id: str) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            raid_id = self._raid_id(conn, report_id)
            return [] if raid_id is None else self._roster(conn, raid_id)

    def _roster(self, conn: Connection, raid_id: int) -> list[dict[str, Any]]:
        c, hp, tp, dp = t.characters, t.healer_performance, t.tank_performance, t.dps_performance
        role = case(
            (hp.c.id.is_not(None), literal("healer")),
            (tp.c.id.is_not(None), literal("tank")),
            (dp.c.role.is_not(None), dp.c.role),
            else_=literal("unknown"),
        ).label("role")
        stmt = (
            select(c.c.name, c.c.player_class, role)
            .select_from(
                c.outerjoin(hp, and_(hp.c.character_id == c.c.id, hp.c.raid_id == raid_id))
                .outerjoin(tp, and_(tp.c.character_id == c.c.id, tp.c.raid_id == raid_id))
                .outerjoin(dp, and_(dp.c.character_id == c.c.id, dp.c.raid_id == raid_id))
            )
            .where(or_(hp.c.id.is_not(None), tp.c.id.is_not(None), dp.c.id.is_not(None)))
            .order_by(_c(role), _c(c.c.name))
        )
        return _dicts(conn.execute(stmt))

    @_storage_errors
    def get_raid_analysis(self, report_id: str) -> RaidAnalysis | None:
        with self._engine.connect() as conn:
            raid = conn.execute(select(t.raids).where(t.raids.c.report_id == report_id)).one_or_none()
            if raid is None:
                return None
            metadata = RaidMetadata(
                report_id=raid.report_id,
                title=raid.title,
                owner=raid.owner or "",
                start_time=raid.start_time,
                end_time=raid.end_time,
            )
            healers = self._load_healers(conn, raid.id)
            tanks = self._load_tanks(conn, raid.id)
            dps = self._load_dps(conn, raid.id)
            role_map = {r["name"]: r["role"] for r in self._roster(conn, raid.id)}
            consumables = self._load_consumables(conn, raid.id, report_id, role_map)
            interrupts = self._load_interrupts(conn, raid.id)
            cancelled = self._load_cancelled_casts(conn, raid.id)
            auras = self._load_uptimes(conn, t.aura_uptime, raid.id)
            totems = self._load_uptimes(conn, t.totem_uptime, raid.id)
            encounters = self._load_encounters(conn, raid.id)

        def ids(players: Iterable[Any], role: str) -> list[PlayerIdentity]:
            return [
                PlayerIdentity(name=p.name, player_class=p.player_class, source_id=p.source_id, role=role)
                for p in players
            ]

        return RaidAnalysis(
            metadata=metadata,
            composition=RaidComposition(
                tanks=ids(tanks, "tank"),
                healers=ids(healers, "healer"),
                melee=ids((d for d in dps if d.role == "melee"), "melee"),
                ranged=ids((d for d in dps if d.role == "ranged"), "ranged"),
            ),
            healers=healers,
            tanks=tanks,
            dps=dps,
            consumables=consumables,
            interrupts=interrupts,
            cancelled_casts=cancelled,
            aura_uptimes=auras,
            totem_uptimes=totems,
            encounters=encounters,
        )

    def _perf_rows(self, conn: Connection, table: Any, raid_id: int) -> list[Any]:
        c = t.characters
        return list(
            conn.execute(
                select(table, c.c.name, c.c.player_class)
                .join(c, c.c.id == table.c.character_id)
                .where(table.c.raid_id == raid_id)
                .order_by(table.c.id)
            )
        )

    def _children(self, conn: Connection, table: Any, fk: str, parent_ids: list[int]) -> dict[int, list[Any]]:
        by_parent: dict[int, list[Any]] = {pid: [] for pid in parent_ids}
        if parent_ids:
            col = table.c[fk]
            for row in conn.execute(select(table).where(col.in_(parent_ids)).order_by(table.c.id)):
                by_parent[row._mapping[fk]].append(row)
        return by_parent

    @staticmethod
    def _spell(row: Any, casts_col: str = "casts", amount_col: str | None = None) -> SpellUsage:
        m: Mapping[str, Any] = row._mapping
        return SpellUsage(
            spell_id=m["spell_id"],
            spell_name=_codec.resolve_name(m["spell_id"], m["spell_name"]),
            casts=m[casts_col],
            total_amount=m[amount_col] if amount_col else 0,
        )

    def _load_healers(self, conn: Connection, raid_id: int) -> list[HealerPerformance]:
        rows = self._perf_rows(conn, t.healer_performance, raid_id)
        spells = self._children(conn, t.healer_spells, "healer_performance_id", [r.id for r in rows])
        return [
            HealerPerformance(
                name=r.name,
                player_class=r.player_class,
                source_id=0,
                total_healing=r.total_healing,
                total_overhealing=r.total_overhealing,
                spells=[self._spell(s, amount_col="total_healing") for s in spells[r.id]],
                fear_ward_casts=r.fear_ward_casts,
                active_time_percent=r.active_time_percent or 0.0,
            )
            for r in rows
        ]

    def _load_tanks(self, conn: Connection, raid_id: int) -> list[TankPerformance]:
        rows = self._perf_rows(conn, t.tank_performance, raid_id)
        perf_ids = [r.id for r in rows]
        taken = self._children(conn, t.tank_damage_taken, "tank_performance_id", perf_ids)
        abilities = self._children(conn, t.tank_abilities, "tank_performance_id", perf_ids)
        return [
            TankPerformance(
                name=r.name,
                player_class=r.player_class,
                source_id=0,
                total_damage_taken=r.total_damage_taken,
                total_mitigated=r.total_mitigated,
                damage_taken_breakdown=[self._spell(s, casts_col="hits") for s in taken[r.id]],
                abilities_used=[self._spell(s) for s in abilities[r.id]],
                active_time_percent=r.active_time_percent or 0.0,
            )
            for r in rows
        ]

    def _load_dps(self, conn: Connection, raid_id: int) -> list[DPSPerformance]:
        rows = self._perf_rows(conn, t.dps_performance, raid_id)
        abilities = self._children(conn, t.dps_abilities, "dps_performance_id", [r.id for r in rows])
        return [
            DPSPerformance(
                name=r.name,
                player_class=r.player_class,
                source_id=0,
                role=r.role,
                total_damage=r.total_damage,
                abilities=[self._spell(s, amount_col="total_damage") for s in abilities[r.id]],
                active_time_percent=r.active_time_percent or 0.0,
            )
            for r in rows
        ]

    def _load_consumables(
        self, conn: Connection, raid_id: int, report_id: str, role_map: dict[str, str]
    ) -> list[ConsumableUsage]:
        return [
            ConsumableUsage(
                player_name=r.name,
                player_role=role_map.get(r.name, "unknown"),
                report_id=report_id,
                consumable_name=r.consumable_name,
                count=r._mapping["count"],
                timestamps=_codec.load_list(r.timestamps),
            )
            for r in self._perf_rows(conn, t.consumable_usage, raid_id)
        ]

    def _load_interrupts(self, conn: Connection, raid_id: int) -> list[InterruptUsage]:
        return [
            InterruptUsage(
                player_name=r.name,
                player_class=r.player_class,
                source_id=0,
                spell_id=r.spell_id,
                spell_name=r.spell_name,
                count=r._mapping["count"],
                timestamps=_codec.load_list(r.timestamps),
            )
            for r in self._perf_rows(conn, t.interrupt_usage, raid_id)
        ]

    def _load_cancelled_casts(self, conn: Connection, raid_id: int) -> list[CancelledCastSummary]:
        details: dict[int, list[CancelledCastDetail]] = {}
        ccs = t.cancelled_cast_spells
        for s in conn.execute(select(ccs).where(ccs.c.raid_id == raid_id).order_by(ccs.c.id)):
            details.setdefault(s.character_id, []).append(
                CancelledCastDetail(
                    spell_id=s.spell_id,
                    spell_name=s.spell_name,
                    total_casts=s.total_casts,
                    cancelled_casts=s.cancelled_casts,
                    cancel_rate=s.cancel_rate,
                    timestamps=_codec.load_list(s.timestamps),
                    correlations=_codec.load_correlations(s.correlations),
                    next_casts=_codec.load_next_casts(s.next_casts),
                )
            )
        return [
            CancelledCastSummary(
                player_name=r.name,
                player_class=r.player_class,
                source_id=0,
                total_casts=r.total_casts,
                cancelled_casts=r.cancelled_casts,
                cancel_rate=r.cancel_rate,
                spell_details=sorted(details.get(r.character_id, []), key=lambda d: d.cancelled_casts, reverse=True),
            )
            for r in self._perf_rows(conn, t.cancelled_casts, raid_id)
        ]

    def _load_uptimes(self, conn: Connection, table: Any, raid_id: int) -> list[AuraUptime]:
        e = t.encounters
        rows = conn.execute(
            select(
                table.c.spell_id,
                table.c.spell_name,
                table.c.uptime_percent,
                table.c.bands_json,
                e.c.name.label("fight_name"),
                e.c.start_time.label("fight_start"),
                e.c.end_time.label("fight_end"),
            )
            .join(e, e.c.id == table.c.encounter_row_id)
            .where(table.c.raid_id == raid_id)
            .order_by(table.c.id)
        )
        return [
            AuraUptime(
                spell_id=r.spell_id,
                spell_name=r.spell_name,
                fight_name=r.fight_name,
                fight_start=r.fight_start,
                fight_end=r.fight_end,
                uptime_percent=r.uptime_percent,
                bands=_codec.load_bands(r.bands_json),
            )
            for r in rows
        ]

    def _load_encounters(self, conn: Connection, raid_id: int) -> list[EncounterSummary]:
        e, ep, c = t.encounters, t.encounter_performance, t.characters
        results = []
        for er in conn.execute(select(e).where(e.c.raid_id == raid_id).order_by(e.c.start_time, e.c.id)):
            perf = conn.execute(
                select(ep, c.c.name, c.c.player_class)
                .join(c, c.c.id == ep.c.character_id)
                .where(ep.c.encounter_row_id == er.id)
                .order_by(ep.c.total_damage.desc(), ep.c.id)
            )
            players = [
                EncounterPerformance(
                    name=p.name,
                    player_class=p.player_class,
                    source_id=0,
                    role=p.role or "unknown",
                    total_damage=p.total_damage,
                    total_healing=p.total_healing,
                    total_damage_taken=p.total_damage_taken,
                    active_time_percent=p.active_time_percent or 0.0,
                )
                for p in perf
            ]
            results.append(
                EncounterSummary(
                    encounter_id=er.encounter_id,
                    name=er.name,
                    start_time=er.start_time,
                    end_time=er.end_time,
                    duration_ms=er.duration_ms,
                    players=players,
                    boss_events=_codec.load_boss_events(er.boss_events),
                )
            )
        return results

    # ── Characters ──

    @_storage_errors
    def get_character_history(self, character_name: str, source: str = "guild") -> CharacterHistory | None:
        with self._engine.connect() as conn:
            char = conn.execute(
                select(t.characters).where(_nocase_eq(t.characters.c.name, character_name))
            ).one_or_none()
            if char is None:
                return None
            params = {"cid": char.id, "source": source}
            role_tables = ("healer_performance", "tank_performance", "dps_performance")

            def one(sql: str) -> Any:
                return conn.execute(text(sql), params).scalar()

            raid_count = one(
                "SELECT COUNT(DISTINCT raid_id) FROM ("
                + " UNION ".join(
                    f"SELECT p.raid_id FROM {tbl} p JOIN raids r ON r.id = p.raid_id "
                    "WHERE p.character_id = :cid AND r.source = :source"
                    for tbl in role_tables
                )
                + ") x"
            )

            def avg(tbl: str, col: str) -> float | None:
                value = one(
                    f"SELECT AVG(p.{col}) FROM {tbl} p JOIN raids r ON r.id = p.raid_id "
                    "WHERE p.character_id = :cid AND r.source = :source"
                )
                return float(value) if value is not None else None

            avg_healing = avg("healer_performance", "total_healing")
            avg_damage = avg("dps_performance", "total_damage")
            avg_mit = avg("tank_performance", "mitigation_percent")
            total_consumes = one(
                "SELECT COALESCE(SUM(cu.count), 0) FROM consumable_usage cu JOIN raids r ON r.id = cu.raid_id "
                "WHERE cu.character_id = :cid AND r.source = :source"
            )
            avg_at = one(
                "SELECT AVG(active_time_percent) FROM ("
                + " UNION ALL ".join(
                    f"SELECT p.active_time_percent FROM {tbl} p JOIN raids r ON r.id = p.raid_id "
                    "WHERE p.character_id = :cid AND r.source = :source AND p.active_time_percent > 0"
                    for tbl in role_tables
                )
                + ") x"
            )

        return CharacterHistory(
            name=char.name,
            player_class=char.player_class,
            total_raids=int(raid_count),
            first_seen=datetime.fromisoformat(char.first_seen),
            last_seen=datetime.fromisoformat(char.last_seen),
            avg_healing=round(avg_healing, 1) if avg_healing else None,
            avg_damage=round(avg_damage, 1) if avg_damage else None,
            avg_mitigation_percent=round(avg_mit, 2) if avg_mit else None,
            total_consumables_used=int(total_consumes),
            avg_active_time=round(float(avg_at), 1) if avg_at else None,
        )

    def _character_raid_ids(self, character_id: Any) -> Any:
        """Ids of raids with a role row for the character (as a subquery)."""
        return union(
            *(
                select(tbl.c.raid_id).where(tbl.c.character_id == character_id)
                for tbl in (t.healer_performance, t.tank_performance, t.dps_performance)
            )
        )

    @_storage_errors
    def get_reports_for_character(self, character_name: str) -> list[dict[str, Any]]:
        r, c = t.raids, t.characters
        stmt = (
            select(r.c.report_id, r.c.title, r.c.owner, r.c.zone, r.c.start_time, r.c.end_time, r.c.source)
            .distinct()
            .select_from(r.join(c, _nocase_eq(c.c.name, character_name)))
            .where(r.c.id.in_(self._character_raid_ids(c.c.id)))
            .order_by(r.c.start_time.desc())
        )
        with self._engine.connect() as conn:
            return _dicts(conn.execute(stmt))

    def _for_character(self, stmt: Any, table: Any, character_name: str, sources: tuple[str, ...]) -> Any:
        r, c = t.raids, t.characters
        return (
            stmt.join(r, r.c.id == table.c.raid_id)
            .join(c, c.c.id == table.c.character_id)
            .where(_nocase_eq(c.c.name, character_name), r.c.source.in_(sources))
        )

    @_storage_errors
    def get_character_raid_roles(
        self, character_name: str, sources: tuple[str, ...] = ("guild",)
    ) -> list[dict[str, Any]]:
        r = t.raids.c
        hp, tp, dp = t.healer_performance, t.tank_performance, t.dps_performance
        base = (r.id.label("raid_id"), r.report_id, r.title, r.raid_date, r.zone)
        big, real = hp.c.total_healing.type, hp.c.overheal_percent.type
        healer = select(
            *base,
            literal("healer").label("role"),
            hp.c.total_healing.label("healing"),
            hp.c.overheal_percent,
            null().cast(big).label("damage"),
            null().cast(big).label("damage_taken"),
            null().cast(real).label("mitigation_percent"),
        ).select_from(hp)
        tank = select(
            *base,
            literal("tank"),
            null().cast(big),
            null().cast(real),
            null().cast(big),
            tp.c.total_damage_taken,
            tp.c.mitigation_percent,
        ).select_from(tp)
        dps = select(
            *base,
            dp.c.role,
            null().cast(big),
            null().cast(real),
            dp.c.total_damage,
            null().cast(big),
            null().cast(real),
        ).select_from(dp)
        parts = [
            self._for_character(q, tbl, character_name, sources) for q, tbl in ((healer, hp), (tank, tp), (dps, dp))
        ]
        stmt = union_all(*parts).subquery()
        with self._engine.connect() as conn:
            return _dicts(conn.execute(select(stmt).order_by(_c(stmt.c.raid_date))))

    @_storage_errors
    def get_character_spell_casts(
        self, character_name: str, sources: tuple[str, ...] = ("guild",)
    ) -> list[dict[str, Any]]:
        hp, tp, dp = t.healer_performance, t.tank_performance, t.dps_performance
        hs, ta, da = t.healer_spells, t.tank_abilities, t.dps_abilities
        healer = select(
            hp.c.raid_id, literal("healer").label("role"), hs.c.spell_id, hs.c.spell_name, hs.c.casts
        ).select_from(hs.join(hp, hp.c.id == hs.c.healer_performance_id))
        tank = select(tp.c.raid_id, literal("tank"), ta.c.spell_id, ta.c.spell_name, ta.c.casts).select_from(
            ta.join(tp, tp.c.id == ta.c.tank_performance_id)
        )
        dps = select(dp.c.raid_id, dp.c.role, da.c.spell_id, da.c.spell_name, da.c.casts).select_from(
            da.join(dp, dp.c.id == da.c.dps_performance_id)
        )
        stmt = union_all(
            *(self._for_character(q, tbl, character_name, sources) for q, tbl in ((healer, hp), (tank, tp), (dps, dp)))
        )
        with self._engine.connect() as conn:
            return _dicts(conn.execute(stmt))

    @_storage_errors
    def get_character_consumable_counts(
        self, character_name: str, sources: tuple[str, ...] = ("guild",)
    ) -> list[dict[str, Any]]:
        cu = t.consumable_usage
        stmt = self._for_character(
            select(cu.c.raid_id, cu.c.consumable_name, cu.c.count).select_from(cu), cu, character_name, sources
        )
        with self._engine.connect() as conn:
            return _dicts(conn.execute(stmt))

    # ── Guild totals ──

    @_storage_errors
    def get_raid_attendance(self, sources: tuple[str, ...] = ("guild",)) -> list[dict[str, Any]]:
        c, r = t.characters, t.raids
        rows = union(
            *(
                select(tbl.c.character_id, tbl.c.raid_id)
                for tbl in (t.healer_performance, t.tank_performance, t.dps_performance)
            )
        ).subquery()
        stmt = (
            select(c.c.name, c.c.player_class, func.count(rows.c.raid_id.distinct()).label("raids"))
            .select_from(rows.join(r, r.c.id == rows.c.raid_id).join(c, c.c.id == rows.c.character_id))
            .where(r.c.source.in_(sources))
            .group_by(c.c.id, c.c.name, c.c.player_class)
            .order_by(_c(c.c.name))
        )
        with self._engine.connect() as conn:
            return _dicts(conn.execute(stmt))

    @_storage_errors
    def get_consumable_totals(self, sources: tuple[str, ...] = ("guild",)) -> list[dict[str, Any]]:
        c, r, cu = t.characters, t.raids, t.consumable_usage
        stmt = (
            select(
                c.c.name,
                cu.c.consumable_name,
                func.sum(cu.c.count).label("count"),
                func.count(cu.c.raid_id.distinct()).label("raids"),
            )
            .select_from(cu.join(r, r.c.id == cu.c.raid_id).join(c, c.c.id == cu.c.character_id))
            .where(cu.c.count > 0, r.c.source.in_(sources))
            .group_by(c.c.id, c.c.name, cu.c.consumable_name)
            .order_by(_c(c.c.name), _c(cu.c.consumable_name))
        )
        with self._engine.connect() as conn:
            return [{**row, "count": int(row["count"])} for row in _dicts(conn.execute(stmt))]

    @_storage_errors
    def get_consumable_raids(
        self, consumable_names: tuple[str, ...], sources: tuple[str, ...] = ("guild",)
    ) -> list[dict[str, Any]]:
        if not consumable_names:
            return []
        c, r, cu = t.characters, t.raids, t.consumable_usage
        stmt = (
            select(c.c.name, cu.c.raid_id, cu.c.consumable_name)
            .select_from(cu.join(r, r.c.id == cu.c.raid_id).join(c, c.c.id == cu.c.character_id))
            .where(cu.c.count > 0, cu.c.consumable_name.in_(consumable_names), r.c.source.in_(sources))
        )
        with self._engine.connect() as conn:
            return _dicts(conn.execute(stmt))

    # ── Player pages ──

    @_storage_errors
    def get_or_create_player_page(self, name: str, server: str, region: str) -> int:
        p = t.player_pages
        with self._engine.begin() as conn:
            conn.execute(insert(p).values(name=name, server=server, region=region).on_conflict_do_nothing())
            return conn.execute(
                select(p.c.id).where(
                    _nocase_eq(p.c.name, name), _nocase_eq(p.c.server, server), _nocase_eq(p.c.region, region)
                )
            ).scalar_one()

    @_storage_errors
    def find_player_pages(self, name: str | None = None) -> list[dict[str, Any]]:
        p, pl = t.player_pages, t.player_page_logs
        log_count = (
            select(func.count())
            .select_from(pl)
            .where(pl.c.player_page_id == p.c.id, pl.c.status == "added")
            .scalar_subquery()
            .label("log_count")
        )
        stmt = select(p.c.id, p.c.name, p.c.server, p.c.region, p.c.created_at, log_count)
        if name:
            stmt = stmt.where(_nocase_eq(p.c.name, name))
        stmt = stmt.order_by(_c(nocase(p.c.name)), _c(nocase(p.c.server)))
        with self._engine.connect() as conn:
            return _dicts(conn.execute(stmt))

    @_storage_errors
    def set_player_page_log(
        self,
        page_id: int,
        report_id: str,
        status: str,
        title: str = "",
        zone: str | None = None,
        owner: str | None = None,
        start_time: int = 0,
    ) -> None:
        pl = t.player_page_logs
        stmt = insert(pl).values(
            player_page_id=page_id,
            report_id=report_id,
            status=status,
            title=title,
            zone=zone,
            owner=owner,
            start_time=start_time,
        )
        ex = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=[pl.c.player_page_id, pl.c.report_id],
            set_={
                "status": ex.status,
                "title": case((ex.title != "", ex.title), else_=pl.c.title),
                "zone": func.coalesce(ex.zone, pl.c.zone),
                "owner": func.coalesce(ex.owner, pl.c.owner),
                "start_time": case((ex.start_time > 0, ex.start_time), else_=pl.c.start_time),
                "updated_at": NOW_TEXT,
            },
        )
        with self._engine.begin() as conn:
            conn.execute(stmt)

    @_storage_errors
    def remove_player_page_log(self, page_id: int, report_id: str) -> bool:
        pl = t.player_page_logs
        with self._engine.begin() as conn:
            result = conn.execute(delete(pl).where(pl.c.player_page_id == page_id, pl.c.report_id == report_id))
            return result.rowcount > 0

    @_storage_errors
    def get_player_page_logs(self, page_id: int, status: str | None = None) -> list[dict[str, Any]]:
        pl, r = t.player_page_logs, t.raids
        stmt = (
            select(
                pl.c.report_id,
                pl.c.status,
                pl.c.title,
                pl.c.zone,
                pl.c.owner,
                pl.c.start_time,
                pl.c.updated_at,
                r.c.id.is_not(None).label("imported"),
            )
            .select_from(pl.outerjoin(r, r.c.report_id == pl.c.report_id))
            .where(pl.c.player_page_id == page_id)
        )
        if status:
            stmt = stmt.where(pl.c.status == status)
        with self._engine.connect() as conn:
            rows = _dicts(conn.execute(stmt.order_by(pl.c.start_time.desc())))
        return [{**row, "imported": bool(row["imported"])} for row in rows]

    # ── Role overrides ──

    @_storage_errors
    def set_role_override(self, character_name: str, role: str, report_id: str = "") -> None:
        ro = t.role_overrides
        stmt = insert(ro).values(character_name=character_name, report_id=report_id, role=role)
        stmt = stmt.on_conflict_do_update(
            index_elements=[nocase(ro.c.character_name), ro.c.report_id],
            set_={"role": stmt.excluded.role, "updated_at": NOW_TEXT},
        )
        with self._engine.begin() as conn:
            conn.execute(stmt)

    @_storage_errors
    def clear_role_override(self, character_name: str, report_id: str = "") -> bool:
        ro = t.role_overrides
        with self._engine.begin() as conn:
            result = conn.execute(
                delete(ro).where(_nocase_eq(ro.c.character_name, character_name), ro.c.report_id == report_id)
            )
            return result.rowcount > 0

    @_storage_errors
    def get_role_overrides(self, character_name: str | None = None) -> list[dict[str, Any]]:
        ro = t.role_overrides
        stmt = select(ro.c.character_name, ro.c.report_id, ro.c.role, ro.c.updated_at)
        if character_name:
            stmt = stmt.where(_nocase_eq(ro.c.character_name, character_name))
        stmt = stmt.order_by(_c(nocase(ro.c.character_name)), _c(ro.c.report_id))
        with self._engine.connect() as conn:
            return _dicts(conn.execute(stmt))

    @_storage_errors
    def get_role_overrides_for_report(self, report_id: str) -> dict[str, str]:
        ro = t.role_overrides
        stmt = (
            select(ro.c.character_name, ro.c.role)
            .where(ro.c.report_id.in_(["", report_id]))
            # '' sorts first, so a raid-specific row overwrites the character-wide one.
            .order_by(_c(ro.c.report_id))
        )
        with self._engine.connect() as conn:
            return {r.character_name: r.role for r in conn.execute(stmt)}

    @_storage_errors
    def get_role_override_raids(self, character_name: str) -> set[str]:
        o, r = t.role_override_raids, t.raids
        stmt = (
            select(r.c.report_id)
            .select_from(o.join(r, r.c.id == o.c.raid_id))
            .where(_nocase_eq(o.c.character_name, character_name))
        )
        with self._engine.connect() as conn:
            return set(conn.execute(stmt).scalars())
