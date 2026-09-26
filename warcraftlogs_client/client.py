"""
WarcraftLogs GraphQL API client.

All API interactions go through WarcraftLogsClient. Methods return
extracted data (not raw JSON wrappers), with consistent signatures.
"""

import json
import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

from .cache import get_cached_response, save_response_cache
from .models import (
    GEAR_SLOT_ORDER,
    GEAR_SLOTS_HIDDEN,
    AllStarRanking,
    CharacterProfile,
    CharacterReportEntry,
    EncounterRanking,
    GearItem,
    RaidMetadata,
    ZoneRankingResult,
)


def _extract_report(result: dict) -> dict:
    """Safely extract the report object from a GraphQL response."""
    report = result.get("data", {}).get("reportData", {}).get("report")
    if report is None:
        raise ValueError("Report not found or inaccessible")
    return report


DEFAULT_API_URL = "https://www.warcraftlogs.com/api/v2/client"

# End timestamp used for "whole report" queries (report-relative milliseconds).
FULL_REPORT_END = 999999999
# Largest page size the events endpoint accepts; the API default is far smaller.
EVENTS_PAGE_LIMIT = 10000

# GraphQL types for the variables the query builders send. Values always travel as
# variables; only enum arguments are written into the query text, and those are
# checked against the allow-lists below first.
_VAR_TYPES = {
    "code": "String!",
    "startTime": "Float!",
    "endTime": "Float!",
    "sourceID": "Int!",
    "targetID": "Int!",
    "abilityID": "Float!",
    "fightIDs": "[Int]!",
    "limit": "Int!",
}
_EVENT_DATA_TYPES = {
    "All",
    "Buffs",
    "Casts",
    "CombatantInfo",
    "DamageDone",
    "DamageTaken",
    "Deaths",
    "Debuffs",
    "Dispels",
    "Healing",
    "Interrupts",
    "Resources",
    "Summons",
    "Threat",
}
_TABLE_DATA_TYPES = (_EVENT_DATA_TYPES - {"All", "CombatantInfo"}) | {"Summary", "Survivability"}
_HOSTILITY_TYPES = {"Friendlies", "Enemies"}
_RANKING_METRICS = {
    "bossdps",
    "bossrdps",
    "default",
    "dps",
    "hps",
    "krsi",
    "playerscore",
    "playerspeed",
    "rdps",
    "tankhps",
    "wdps",
}


def _enum(value: str, allowed: set[str]) -> str:
    """Return *value* for use as a GraphQL enum literal, rejecting anything not allow-listed."""
    if value not in allowed:
        raise ValueError(f"Unsupported GraphQL enum value: {value!r}")
    return value


class WarcraftLogsClient:
    """GraphQL client for Warcraft Logs.

    Pass ``api_url`` from config (``wcl_api_url``) so Fresh vs retail hosts stay
    consistent. Temporary per-call overrides (e.g. character profile) still work
    via the ``api_url`` argument on those methods.
    """

    MIN_REQUEST_INTERVAL = 0.25
    MAX_RETRIES = 3

    def __init__(self, token_manager, cache_enabled: bool = True, api_url: str | None = None):
        self.token_manager = token_manager
        self._last_request_time = 0.0
        self.cache_enabled = cache_enabled
        self.api_url = (api_url or DEFAULT_API_URL).rstrip("/")

    # Back-compat for callers that read/assign API_URL on the instance.
    @property
    def API_URL(self) -> str:
        return self.api_url

    @API_URL.setter
    def API_URL(self, value: str) -> None:
        self.api_url = value.rstrip("/")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)

    def run_query(self, query: str, use_cache: bool = True, variables: dict | None = None) -> dict:
        """POST a GraphQL query. Pass user- or report-derived values in *variables*, never in *query*."""
        use_cache = use_cache and self.cache_enabled
        cache_key = query if not variables else f"{query}\n{json.dumps(variables, sort_keys=True)}"
        if use_cache:
            cached = get_cached_response(cache_key)
            if cached is not None:
                logger.debug("Cache hit for query")
                return cached

        token = self.token_manager.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables

        logger.info("API request: POST %s", self.api_url)
        logger.debug("Query: %s variables=%s", query[:200], variables)

        for attempt in range(self.MAX_RETRIES):
            self._throttle()
            self._last_request_time = time.monotonic()

            response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)

            logger.info("API response: %d (attempt %d)", response.status_code, attempt + 1)

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.MAX_RETRIES - 1:
                    backoff = 2**attempt
                    time.sleep(backoff)
                    continue
            response.raise_for_status()
            result = response.json()
            logger.debug(
                "Response data keys: %s", list(result.get("data", {}).keys()) if "data" in result else "no data key"
            )
            if result.get("errors"):
                logger.warning("GraphQL errors: %s", result["errors"])
            if use_cache:
                save_response_cache(cache_key, result)
            return result

        response.raise_for_status()
        result = response.json()
        if use_cache:
            save_response_cache(cache_key, result)
        return result

    # ── Query builders ──

    def _query_report(self, report_id: str, body: str, args: dict | None = None, use_cache: bool = True) -> dict:
        """Run ``reportData { report(code: $code) { <body> } }`` and return the report object.

        *body* may reference ``$name`` for each key in *args*; values are sent as GraphQL variables.
        """
        variables = {"code": report_id, **(args or {})}
        decls = ", ".join(f"${name}: {_VAR_TYPES[name]}" for name in variables)
        query = f"query({decls}) {{ reportData {{ report(code: $code) {{ {body} }} }} }}"
        return _extract_report(self.run_query(query, use_cache=use_cache, variables=variables))

    def _table(self, report_id: str, data_type: str, start_time: float, end_time: float, **filters) -> Any:
        """Fetch a report ``table`` for a data type. *filters* take hostilityType/sourceID/targetID."""
        hostility = filters.pop("hostilityType", None)
        args: dict = {"startTime": start_time, "endTime": end_time}
        args.update({k: v for k, v in filters.items() if v})
        call = [f"dataType: {_enum(data_type, _TABLE_DATA_TYPES)}"]
        if hostility:
            call.append(f"hostilityType: {_enum(hostility, _HOSTILITY_TYPES)}")
        call += [f"{name}: ${name}" for name in args]
        report = self._query_report(report_id, f"table({', '.join(call)})", args)
        return report.get("table")

    def _table_entries(self, report_id: str, data_type: str, start_time: float, end_time: float, **filters) -> list:
        raw_table = self._table(report_id, data_type, start_time, end_time, **filters)
        if isinstance(raw_table, dict):
            if "data" in raw_table and "entries" in raw_table["data"]:
                return raw_table["data"]["entries"]
            if "entries" in raw_table:
                return raw_table["entries"]
        return []

    def _events(
        self,
        report_id: str,
        data_type: str,
        start_time: float = 0,
        end_time: float = FULL_REPORT_END,
        *,
        hostility: str | None = "Friendlies",
        **filters,
    ) -> list[dict]:
        """Fetch every ``events`` page for a data type, following ``nextPageTimestamp``.

        *filters* take sourceID/abilityID/fightIDs/limit; falsy values are omitted.
        """
        base: dict = {"limit": EVENTS_PAGE_LIMIT, **{k: v for k, v in filters.items() if v}}
        call = [f"dataType: {_enum(data_type, _EVENT_DATA_TYPES)}"]
        if hostility:
            call.append(f"hostilityType: {_enum(hostility, _HOSTILITY_TYPES)}")
        call += ["startTime: $startTime", "endTime: $endTime"]
        call += [f"{name}: ${name}" for name in base]
        body = f"events({', '.join(call)}) {{ data nextPageTimestamp }}"

        all_data: list[dict] = []
        page_start = start_time
        while True:
            args = {"startTime": page_start, "endTime": end_time, **base}
            report = self._query_report(report_id, body, args)
            events = report.get("events") or {}
            all_data.extend(events.get("data") or [])
            next_page = events.get("nextPageTimestamp")
            if not next_page:
                return all_data
            page_start = next_page

    # ── Report-level queries ──

    def get_report_metadata(self, report_id: str) -> RaidMetadata:
        report = self._query_report(report_id, "title owner { name } startTime endTime zone { name }")
        zone_data = report.get("zone")
        return RaidMetadata(
            report_id=report_id,
            title=report["title"],
            owner=report["owner"]["name"],
            start_time=report["startTime"],
            end_time=report.get("endTime"),
            zone=zone_data["name"] if zone_data else None,
        )

    def get_guild_info(self, guild_id: int) -> dict:
        """Fetch guild name and server by guild ID."""
        query = """
        query($id: Int!) {
          guildData {
            guild(id: $id) {
              name
              server { name region { name } }
            }
          }
        }
        """
        result = self.run_query(query, variables={"id": guild_id})
        guild = result["data"]["guildData"]["guild"]
        if not guild:
            return {"name": "", "server": ""}
        server = guild.get("server") or {}
        return {
            "name": guild.get("name", ""),
            "server": server.get("name", ""),
        }

    def get_guild_reports(self, guild_id: int, total: int = 350) -> list[dict]:
        """Fetch recent reports for a guild, paginating to collect *total* reports."""
        all_reports: list[dict] = []
        page = 1
        per_page = min(total, 100)
        query = """
        query($guildID: Int!, $limit: Int!, $page: Int!) {
          reportData {
            reports(guildID: $guildID, limit: $limit, page: $page) {
              data {
                code
                title
                owner { name }
                startTime
                endTime
                zone { name }
              }
              has_more_pages
            }
          }
        }
        """

        while len(all_reports) < total:
            variables = {"guildID": guild_id, "limit": per_page, "page": page}
            result = self.run_query(query, use_cache=False, variables=variables)
            page_data = result["data"]["reportData"]["reports"]
            for r in page_data["data"]:
                all_reports.append(
                    {
                        "code": r["code"],
                        "title": r["title"],
                        "owner": r["owner"]["name"] if r.get("owner") else "",
                        "start_time": r["startTime"],
                        "end_time": r.get("endTime"),
                        "zone": r["zone"]["name"] if r.get("zone") else "",
                    }
                )
            if not page_data.get("has_more_pages"):
                break
            page += 1

        return all_reports[:total]

    def get_master_data(self, report_id: str) -> list[dict]:
        return [a for a in self.get_all_actors(report_id) if a["type"] == "Player"]

    def get_ability_names(self, report_id: str) -> dict[int, str]:
        report = self._query_report(report_id, "masterData { abilities { gameID name } }")
        abilities = (report.get("masterData") or {}).get("abilities") or []
        return {a["gameID"]: a["name"] for a in abilities if a.get("gameID") and a.get("name")}

    def get_fights(self, report_id: str) -> list[dict]:
        report = self._query_report(report_id, "fights { id name startTime endTime kill encounterID }")
        return report.get("fights") or []

    def get_encounter_table(self, report_id: str, start_time: int, end_time: int, data_type: str) -> list[dict]:
        """Query the table endpoint for a time window without sourceID.

        Returns per-player aggregate totals for the given data_type
        (DamageDone, Healing, or DamageTaken) within the fight window.
        """
        return self._table_entries(report_id, data_type, start_time, end_time, hostilityType="Friendlies")

    # ── Player event queries ──

    def get_healing_data(self, report_id: str, source_id: int) -> list[dict]:
        return self._events(report_id, "Healing", sourceID=source_id)

    def get_cast_data(self, report_id: str, source_id: int) -> list[dict]:
        return self._events(report_id, "Casts", sourceID=source_id)

    def get_cast_events_paginated(self, report_id: str, source_id: int) -> list[dict]:
        return self._events(report_id, "Casts", sourceID=source_id)

    def get_cast_events_for_encounter(
        self, report_id: str, source_id: int, start_time: int, end_time: int
    ) -> list[dict]:
        return self._events(report_id, "Casts", start_time, end_time, sourceID=source_id)

    def get_resource_events_paginated(
        self, report_id: str, source_id: int, start_time: int, end_time: int
    ) -> list[dict]:
        return self._events(report_id, "Resources", start_time, end_time, sourceID=source_id)

    def get_buffs_table_for_encounter(
        self,
        report_id: str,
        start_time: int,
        end_time: int,
        source_id: int = 0,
        target_id: int = 0,
    ) -> dict:
        table = self._table(
            report_id,
            "Buffs",
            start_time,
            end_time,
            hostilityType="Friendlies",
            sourceID=source_id,
            targetID=target_id,
        )
        return table or {}

    def get_cast_table(self, report_id: str, source_id: int) -> list[dict]:
        return self._table_entries(report_id, "Casts", 0, FULL_REPORT_END, sourceID=source_id)

    def get_damage_taken_table(self, report_id: str, source_id: int) -> list[dict]:
        return self._table_entries(
            report_id, "DamageTaken", 0, FULL_REPORT_END, hostilityType="Friendlies", sourceID=source_id
        )

    def get_damage_done_table(self, report_id: str, source_id: int) -> list[dict]:
        return self._table_entries(report_id, "DamageDone", 0, FULL_REPORT_END, sourceID=source_id)

    def get_aura_data(self, report_id: str, source_id: int) -> list[dict]:
        return self._events(report_id, "Buffs", sourceID=source_id)

    def get_auras_paginated(self, report_id: str, source_id: int) -> list[dict]:
        return self._events(report_id, "Buffs", sourceID=source_id)

    def get_aura_data_by_ability(self, report_id: str, source_id: int, ability_id: int) -> list[dict]:
        return self._events(report_id, "Buffs", sourceID=source_id, abilityID=ability_id)

    def get_buffs_table(self, report_id: str, source_id: int) -> dict:
        table = self._table(report_id, "Buffs", 0, FULL_REPORT_END, hostilityType="Friendlies", sourceID=source_id)
        return table or {}

    def get_debuffs_table(self, report_id: str, start_time: int, end_time: int) -> dict:
        """Fetch debuff table for enemies in a fight time window."""
        table = self._table(report_id, "Debuffs", start_time, end_time, hostilityType="Enemies")
        return table or {}

    def get_damage_done_data(self, report_id: str, source_id: int) -> list[dict]:
        return self._events(report_id, "DamageDone", sourceID=source_id)

    def get_damage_taken_data(self, report_id: str, source_id: int) -> list[dict]:
        return self._events(report_id, "DamageTaken", sourceID=source_id)

    def get_enemy_ability_names(self, report_id: str, start_time: int, end_time: int) -> dict[int, str]:
        names: dict[int, str] = {}
        for data_type in ("Casts", "DamageDone"):
            entries = self._table_entries(report_id, data_type, start_time, end_time, hostilityType="Enemies")
            for actor in entries:
                for ability in actor.get("abilities", []):
                    gid = ability.get("gameID") or ability.get("guid")
                    name = ability.get("name")
                    if gid and name:
                        names[gid] = name
        return names

    def get_enemy_cast_events(self, report_id: str, start_time: int, end_time: int) -> list[dict]:
        return self._events(report_id, "Casts", start_time, end_time, hostility="Enemies")

    def get_raid_damage_taken_events(self, report_id: str, start_time: int, end_time: int) -> list[dict]:
        return self._events(report_id, "DamageTaken", start_time, end_time)

    def get_all_actors(self, report_id: str) -> list[dict]:
        report = self._query_report(report_id, "masterData { actors { id name type subType } }")
        return (report.get("masterData") or {}).get("actors") or []

    def get_threat_data(self, report_id: str, source_id: int) -> list[dict]:
        return self._events(report_id, "Threat", hostility=None, sourceID=source_id)

    # ── Character profile queries ──

    def get_character_profile(
        self, name: str, server_slug: str, server_region: str, api_url: str | None = None
    ) -> CharacterProfile:
        """Fetch a full character profile from the WCL API."""
        original_url = self.api_url
        if api_url:
            self.api_url = api_url.rstrip("/")

        try:
            query = """
            query($name: String!, $serverSlug: String!, $serverRegion: String!) {
              characterData {
                character(name: $name, serverSlug: $serverSlug, serverRegion: $serverRegion) {
                  name
                  classID
                  level
                  faction { name }
                  guilds { name }
                  zoneRankings
                  recentReports(limit: 20) {
                    data {
                      code
                      title
                      startTime
                      zone { name }
                    }
                  }
                }
              }
            }
            """
            variables = {"name": name, "serverSlug": server_slug, "serverRegion": server_region}
            result = self.run_query(query, use_cache=False, variables=variables)
            char = result["data"]["characterData"]["character"]
            if not char:
                raise ValueError(f"Character '{name}' not found on {server_slug}-{server_region}")

            profile = CharacterProfile(
                name=char["name"],
                server=server_slug,
                region=server_region,
                class_id=char.get("classID", 0),
                level=char.get("level", 0),
                faction=char.get("faction", {}).get("name", ""),
                guild_name=char.get("guilds", [{}])[0].get("name", "") if char.get("guilds") else "",
            )

            # Parse zone rankings
            zr = char.get("zoneRankings")
            if zr and isinstance(zr, dict) and "error" not in zr:
                profile.zone_rankings = [self._parse_zone_rankings(zr)]

            # Parse recent reports
            reports_data = char.get("recentReports", {}).get("data", [])
            profile.recent_reports = [
                CharacterReportEntry(
                    code=r["code"],
                    title=r["title"],
                    start_time=r.get("startTime", 0),
                    zone_name=r.get("zone", {}).get("name", "") if r.get("zone") else "",
                )
                for r in reports_data
            ]

            # Fetch gear from CombatantInfo in the most recent report
            if profile.recent_reports:
                profile.gear_items = self._fetch_gear_from_report(profile.recent_reports[0].code, profile.name)

            return profile
        finally:
            self.api_url = original_url

    def _fetch_gear_from_report(self, report_code: str, char_name: str) -> list[GearItem]:
        """Pull equipped gear from CombatantInfo events in a report."""
        try:
            report = self._query_report(
                report_code,
                'masterData { actors(type: "Player") { id name } } fights(killType: Encounters) { id }',
            )

            actors = report.get("masterData", {}).get("actors", [])
            source_id = None
            for a in actors:
                if a.get("name", "").lower() == char_name.lower():
                    source_id = a["id"]
                    break
            if source_id is None:
                return []

            fights = report.get("fights", [])
            if not fights:
                return []
            fight_id = fights[-1]["id"]

            gear_report = self._query_report(
                report_code,
                "events(dataType: CombatantInfo, fightIDs: $fightIDs, sourceID: $sourceID, limit: $limit) { data }",
                {"fightIDs": [fight_id], "sourceID": source_id, "limit": 10},
            )
            events = (gear_report.get("events") or {}).get("data") or []
            if not events:
                return []

            gear_array = events[0].get("gear", [])
            items = []
            for i, g in enumerate(gear_array):
                if not isinstance(g, dict) or not g.get("id"):
                    continue
                slot_name = GEAR_SLOT_ORDER[i] if i < len(GEAR_SLOT_ORDER) else f"Slot {i}"
                if slot_name in GEAR_SLOTS_HIDDEN:
                    continue
                gems = [gem["id"] for gem in g.get("gems", []) if gem.get("id")]
                items.append(
                    GearItem(
                        slot=slot_name,
                        item_id=g["id"],
                        item_level=g.get("itemLevel", 0),
                        quality=g.get("quality", 0),
                        enchant_id=g.get("permanentEnchant", 0),
                        gems=gems,
                    )
                )
            return items
        except (KeyError, TypeError, IndexError):
            return []

    def get_character_zone_rankings(
        self,
        name: str,
        server_slug: str,
        server_region: str,
        zone_id: int,
        metric: str = "dps",
        api_url: str | None = None,
    ) -> ZoneRankingResult | None:
        """Fetch zone rankings for a specific zone."""
        original_url = self.api_url
        if api_url:
            self.api_url = api_url.rstrip("/")

        try:
            query = f"""
            query($name: String!, $serverSlug: String!, $serverRegion: String!, $zoneID: Int!) {{
              characterData {{
                character(name: $name, serverSlug: $serverSlug, serverRegion: $serverRegion) {{
                  zoneRankings(zoneID: $zoneID, metric: {_enum(metric, _RANKING_METRICS)})
                }}
              }}
            }}
            """
            variables = {"name": name, "serverSlug": server_slug, "serverRegion": server_region, "zoneID": zone_id}
            result = self.run_query(query, use_cache=False, variables=variables)
            char = result["data"]["characterData"]["character"]
            if not char:
                return None

            zr = char.get("zoneRankings")
            if zr and isinstance(zr, dict) and "error" not in zr:
                return self._parse_zone_rankings(zr)
            return None
        finally:
            self.api_url = original_url

    def _parse_zone_rankings(self, zr: dict) -> ZoneRankingResult:
        all_stars = []
        for s in zr.get("allStars", []):
            all_stars.append(
                AllStarRanking(
                    spec=s.get("spec", ""),
                    points=s.get("points", 0),
                    possible_points=s.get("possiblePoints", 0),
                    rank=s.get("rank", 0),
                    region_rank=s.get("regionRank", 0),
                    server_rank=s.get("serverRank", 0),
                    rank_percent=s.get("rankPercent", 0),
                    total=s.get("total", 0),
                )
            )

        rankings = []
        for r in zr.get("rankings", []):
            enc = r.get("encounter", {})
            rankings.append(
                EncounterRanking(
                    encounter_id=enc.get("id", 0),
                    encounter_name=enc.get("name", ""),
                    spec=r.get("spec", ""),
                    best_percent=r.get("rankPercent", 0),
                    median_percent=r.get("medianPercent", 0),
                    total_kills=r.get("totalKills", 0),
                    fastest_kill_ms=r.get("fastestKill", 0),
                    locked_in=r.get("lockedIn", False),
                )
            )

        return ZoneRankingResult(
            zone_id=zr.get("zone", 0),
            difficulty=zr.get("difficulty", 0),
            metric=zr.get("metric", "dps"),
            partition=zr.get("partition", 0),
            best_average=zr.get("bestPerformanceAverage", 0),
            median_average=zr.get("medianPerformanceAverage", 0),
            all_stars=all_stars,
            encounter_rankings=rankings,
        )


# ── Legacy compatibility shims ──
# These free functions are used by existing code. They delegate to client methods
# but accept the old (client, report_id, source_id) signature.


def get_healing_data(client: WarcraftLogsClient, report_id: str, source_id: int):
    data = client.get_healing_data(report_id, source_id)
    return {"data": {"reportData": {"report": {"events": {"data": data}}}}}


def get_cast_data(client: WarcraftLogsClient, report_id: str, source_id: int):
    data = client.get_cast_data(report_id, source_id)
    return {"data": {"reportData": {"report": {"events": {"data": data}}}}}


def get_cast_events_data(client: WarcraftLogsClient, report_id: str, source_id: int):
    data = client.get_cast_events_paginated(report_id, source_id)
    return {"data": {"reportData": {"report": {"events": {"data": data}}}}}


def get_aura_data(client: WarcraftLogsClient, report_id: str, source_id: int):
    data = client.get_aura_data(report_id, source_id)
    return {"data": {"reportData": {"report": {"events": {"data": data}}}}}


def get_auras_data(client: WarcraftLogsClient, report_id: str, source_id: int):
    data = client.get_auras_paginated(report_id, source_id)
    return {"data": {"reportData": {"report": {"events": {"data": data}}}}}


def get_auras_data_by_ability(client: WarcraftLogsClient, report_id: str, source_id: int, ability_id: int):
    data = client.get_aura_data_by_ability(report_id, source_id, ability_id)
    return {"data": {"reportData": {"report": {"events": {"data": data}}}}}


def get_buffs_table(client: WarcraftLogsClient, report_id: str, source_id: int):
    table = client.get_buffs_table(report_id, source_id)
    return {"data": {"reportData": {"report": {"table": table}}}}


def get_damage_done_data(client: WarcraftLogsClient, report_id: str, source_id: int) -> list[dict]:
    return client.get_damage_done_data(report_id, source_id)


def get_damage_taken_data(client: WarcraftLogsClient, report_id: str, source_id: int) -> list[dict]:
    return client.get_damage_taken_data(report_id, source_id)
