"""JSON encodings for the list-valued model fields both backends store in text columns.

Backends must share these so a row written by one reads back the same through the other.
"""

from __future__ import annotations

import json
from typing import Any

from wcl_core.models import AuraBand, BossEvent, CancelledCastCorrelation, NextCastInfo
from wcl_core.spell_manager import get_spell_manager


def resolve_name(spell_id: int, stored_name: str) -> str:
    """The stored spell name, or a better one if it was stored as a ``(ID n)`` placeholder."""
    if stored_name.startswith("(ID "):
        resolved: str = get_spell_manager().get_spell_name(spell_id)
        if not resolved.startswith("(ID "):
            return resolved
    return stored_name


def dump_list(values: list[Any]) -> str | None:
    return json.dumps(values) if values else None


def load_list(raw: str | None) -> list[Any]:
    return json.loads(raw) if raw else []


def dump_correlations(correlations: list[CancelledCastCorrelation]) -> str | None:
    if not correlations:
        return None
    return json.dumps(
        [
            {
                "ts": c.cancel_timestamp,
                "events": [
                    {
                        "type": e.event_type,
                        "name": e.ability_name,
                        "aid": e.ability_id,
                        "src": e.source_name,
                        "offset": e.offset_ms,
                    }
                    for e in c.nearby_events
                ],
            }
            for c in correlations
        ]
    )


def load_correlations(raw: str | None) -> list[CancelledCastCorrelation]:
    result = []
    for entry in load_list(raw):
        events = [
            BossEvent(
                timestamp=entry["ts"] + ev.get("offset", 0),
                event_type=ev["type"],
                ability_name=ev["name"],
                ability_id=ev.get("aid", 0),
                source_name=ev.get("src", "Boss"),
                offset_ms=ev.get("offset", 0),
            )
            for ev in entry.get("events", [])
        ]
        result.append(CancelledCastCorrelation(cancel_timestamp=entry["ts"], nearby_events=events))
    return result


def dump_next_casts(next_casts: list[NextCastInfo | None]) -> str | None:
    if not next_casts:
        return None
    return json.dumps([{"id": n.spell_id, "name": n.spell_name, "ts": n.timestamp} if n else None for n in next_casts])


def load_next_casts(raw: str | None) -> list[NextCastInfo | None]:
    return [
        NextCastInfo(spell_id=item["id"], spell_name=item["name"], timestamp=item["ts"]) if item else None
        for item in load_list(raw)
    ]


def dump_boss_events(events: list[BossEvent]) -> str | None:
    if not events:
        return None
    return json.dumps(
        [
            {
                "ts": be.timestamp,
                "type": be.event_type,
                "name": be.ability_name,
                "aid": be.ability_id,
                "src": be.source_name,
            }
            for be in events
        ]
    )


def load_boss_events(raw: str | None) -> list[BossEvent]:
    return [
        BossEvent(
            timestamp=item["ts"],
            event_type=item["type"],
            ability_name=item["name"],
            ability_id=item.get("aid", 0),
            source_name=item.get("src", ""),
        )
        for item in load_list(raw)
    ]


def dump_bands(bands: list[AuraBand]) -> str | None:
    if not bands:
        return None
    return json.dumps([{"start": b.start_time, "end": b.end_time} for b in bands])


def load_bands(raw: str | None) -> list[AuraBand]:
    return [AuraBand(start_time=b["start"], end_time=b["end"]) for b in load_list(raw)]


_ASCII_FOLD = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def ascii_lower(text: str) -> str:
    """Fold ASCII letters only, as SQLite's ``LOWER``/``NOCASE`` and the Postgres ``nocase`` do."""
    return text.translate(_ASCII_FOLD)
