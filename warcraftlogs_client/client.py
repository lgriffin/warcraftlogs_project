"""
WarcraftLogs GraphQL API client.

All API interactions go through WarcraftLogsClient. Methods return
extracted data (not raw JSON wrappers), with consistent signatures.
"""

import time

import requests
from typing import Optional

from .cache import get_cached_response, save_response_cache
from .models import (
    RaidMetadata, CharacterProfile, ZoneRankingResult,
    EncounterRanking, AllStarRanking, CharacterReportEntry,
)


class WarcraftLogsClient:
    API_URL = "https://www.warcraftlogs.com/api/v2/client"
    MIN_REQUEST_INTERVAL = 0.25
    MAX_RETRIES = 3

    def __init__(self, token_manager, cache_enabled: bool = True):
        self.token_manager = token_manager
        self._last_request_time = 0.0
        self.cache_enabled = cache_enabled

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)

    def run_query(self, query: str, use_cache: bool = True) -> dict:
        use_cache = use_cache and self.cache_enabled
        if use_cache:
            cached = get_cached_response(query)
            if cached is not None:
                return cached

        token = self.token_manager.get_token()
        headers = {"Authorization": f"Bearer {token}"}

        for attempt in range(self.MAX_RETRIES):
            self._throttle()
            self._last_request_time = time.monotonic()

            response = requests.post(self.API_URL, headers=headers, json={"query": query})

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.MAX_RETRIES - 1:
                    backoff = 2 ** attempt
                    time.sleep(backoff)
                    continue
            response.raise_for_status()
            result = response.json()
            if use_cache:
                save_response_cache(query, result)
            return result

        response.raise_for_status()
        result = response.json()
        if use_cache:
            save_response_cache(query, result)
        return result

    # ── Report-level queries ──

    def get_report_metadata(self, report_id: str) -> RaidMetadata:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              title
              owner {{ name }}
              startTime
              endTime
            }}
          }}
        }}
        """
        result = self.run_query(query)
        report = result["data"]["reportData"]["report"]
        if report is None:
            raise ValueError(f"Report '{report_id}' not found or inaccessible")
        return RaidMetadata(
            report_id=report_id,
            title=report["title"],
            owner=report["owner"]["name"],
            start_time=report["startTime"],
            end_time=report.get("endTime"),
        )

    def get_guild_info(self, guild_id: int) -> dict:
        """Fetch guild name and server by guild ID."""
        query = f"""
        {{
          guildData {{
            guild(id: {guild_id}) {{
              name
              server {{
                name
                region {{
                  name
                }}
              }}
            }}
          }}
        }}
        """
        result = self.run_query(query)
        guild = result["data"]["guildData"]["guild"]
        if not guild:
            return {"name": "", "server": ""}
        server = guild.get("server") or {}
        return {
            "name": guild.get("name", ""),
            "server": server.get("name", ""),
        }

    def get_guild_reports(self, guild_id: int, limit: int = 50) -> list[dict]:
        """Fetch recent reports for a guild by guild ID."""
        query = f"""
        {{
          reportData {{
            reports(guildID: {guild_id}, limit: {limit}) {{
              data {{
                code
                title
                owner {{ name }}
                startTime
                endTime
                zone {{ name }}
              }}
            }}
          }}
        }}
        """
        result = self.run_query(query, use_cache=False)
        reports = result["data"]["reportData"]["reports"]["data"]
        return [
            {
                "code": r["code"],
                "title": r["title"],
                "owner": r["owner"]["name"] if r.get("owner") else "",
                "start_time": r["startTime"],
                "end_time": r.get("endTime"),
                "zone": r["zone"]["name"] if r.get("zone") else "",
            }
            for r in reports
        ]

    def get_master_data(self, report_id: str) -> list[dict]:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              masterData {{
                actors {{
                  id
                  name
                  type
                  subType
                }}
              }}
            }}
          }}
        }}
        """
        result = self.run_query(query)
        actors = result["data"]["reportData"]["report"]["masterData"]["actors"]
        return [a for a in actors if a["type"] == "Player"]

    def get_fights(self, report_id: str) -> list[dict]:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              fights {{
                id
                name
                startTime
                endTime
                kill
                encounterID
              }}
            }}
          }}
        }}
        """
        result = self.run_query(query)
        return result["data"]["reportData"]["report"]["fights"]

    # ── Player event queries ──

    def get_healing_data(self, report_id: str, source_id: int) -> list[dict]:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              events(startTime: 0, endTime: 999999999, sourceID: {source_id},
                     dataType: Healing, hostilityType: Friendlies) {{
                data
              }}
            }}
          }}
        }}
        """
        result = self.run_query(query)
        return result["data"]["reportData"]["report"]["events"]["data"]

    def get_cast_data(self, report_id: str, source_id: int) -> list[dict]:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              events(startTime: 0, endTime: 999999999, sourceID: {source_id},
                     dataType: Casts, hostilityType: Friendlies) {{
                data
              }}
            }}
          }}
        }}
        """
        result = self.run_query(query)
        return result["data"]["reportData"]["report"]["events"]["data"]

    def get_cast_events_paginated(self, report_id: str, source_id: int) -> list[dict]:
        all_data = []
        start_time = 0
        while True:
            query = f"""
            {{
              reportData {{
                report(code: "{report_id}") {{
                  events(startTime: {start_time}, endTime: 999999999, sourceID: {source_id},
                         dataType: Casts, hostilityType: Friendlies, limit: 10000) {{
                    data
                    nextPageTimestamp
                  }}
                }}
              }}
            }}
            """
            result = self.run_query(query)
            events = result["data"]["reportData"]["report"]["events"]
            all_data.extend(events.get("data", []))
            next_page = events.get("nextPageTimestamp")
            if not next_page:
                break
            start_time = next_page
        return all_data

    def get_cast_table(self, report_id: str, source_id: int) -> list[dict]:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              table(dataType: Casts, sourceID: {source_id}, startTime: 0, endTime: 999999999)
            }}
          }}
        }}
        """
        result = self.run_query(query)
        raw_table = result["data"]["reportData"]["report"]["table"]
        if isinstance(raw_table, dict):
            if "data" in raw_table and "entries" in raw_table["data"]:
                return raw_table["data"]["entries"]
            if "entries" in raw_table:
                return raw_table["entries"]
        return []

    def get_damage_taken_table(self, report_id: str, source_id: int) -> list[dict]:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              table(dataType: DamageTaken, sourceID: {source_id}, startTime: 0, endTime: 999999999,
                    hostilityType: Friendlies)
            }}
          }}
        }}
        """
        result = self.run_query(query)
        raw_table = result["data"]["reportData"]["report"]["table"]
        if isinstance(raw_table, dict):
            if "data" in raw_table and "entries" in raw_table["data"]:
                return raw_table["data"]["entries"]
            if "entries" in raw_table:
                return raw_table["entries"]
        return []

    def get_damage_done_table(self, report_id: str, source_id: int) -> list[dict]:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              table(dataType: DamageDone, sourceID: {source_id}, startTime: 0, endTime: 999999999)
            }}
          }}
        }}
        """
        result = self.run_query(query)
        raw_table = result["data"]["reportData"]["report"]["table"]
        if isinstance(raw_table, dict):
            if "data" in raw_table and "entries" in raw_table["data"]:
                return raw_table["data"]["entries"]
            if "entries" in raw_table:
                return raw_table["entries"]
        return []

    def get_aura_data(self, report_id: str, source_id: int) -> list[dict]:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              events(startTime: 0, endTime: 999999999, sourceID: {source_id},
                     dataType: Buffs, hostilityType: Friendlies) {{
                data
              }}
            }}
          }}
        }}
        """
        result = self.run_query(query)
        return result["data"]["reportData"]["report"]["events"]["data"]

    def get_auras_paginated(self, report_id: str, source_id: int) -> list[dict]:
        all_data = []
        start_time = 0
        while True:
            query = f"""
            {{
              reportData {{
                report(code: "{report_id}") {{
                  events(startTime: {start_time}, endTime: 999999999, sourceID: {source_id},
                         dataType: Buffs, hostilityType: Friendlies, limit: 10000) {{
                    data
                    nextPageTimestamp
                  }}
                }}
              }}
            }}
            """
            result = self.run_query(query)
            events = result["data"]["reportData"]["report"]["events"]
            all_data.extend(events.get("data", []))
            next_page = events.get("nextPageTimestamp")
            if not next_page:
                break
            start_time = next_page
        return all_data

    def get_aura_data_by_ability(self, report_id: str, source_id: int, ability_id: int) -> list[dict]:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              events(startTime: 0, endTime: 999999999, sourceID: {source_id},
                     dataType: Buffs, hostilityType: Friendlies, abilityID: {ability_id}) {{
                data
              }}
            }}
          }}
        }}
        """
        result = self.run_query(query)
        return result["data"]["reportData"]["report"]["events"]["data"]

    def get_buffs_table(self, report_id: str, source_id: int) -> dict:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              table(dataType: Buffs, startTime: 0, endTime: 999999999,
                    hostilityType: Friendlies, sourceID: {source_id})
            }}
          }}
        }}
        """
        result = self.run_query(query)
        return result["data"]["reportData"]["report"]["table"]

    def get_damage_done_data(self, report_id: str, source_id: int) -> list[dict]:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              events(startTime: 0, endTime: 999999999, sourceID: {source_id},
                     dataType: DamageDone, hostilityType: Friendlies) {{
                data
              }}
            }}
          }}
        }}
        """
        result = self.run_query(query)
        return result["data"]["reportData"]["report"]["events"]["data"]

    def get_damage_taken_data(self, report_id: str, source_id: int) -> list[dict]:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              events(startTime: 0, endTime: 999999999, sourceID: {source_id},
                     dataType: DamageTaken, hostilityType: Friendlies) {{
                data
              }}
            }}
          }}
        }}
        """
        result = self.run_query(query)
        return result["data"]["reportData"]["report"]["events"]["data"]

    def get_threat_data(self, report_id: str, source_id: int) -> list[dict]:
        all_data = []
        start_time = 0
        while True:
            query = f"""
            {{
              reportData {{
                report(code: "{report_id}") {{
                  events(startTime: {start_time}, endTime: 999999999,
                         sourceID: {source_id}, dataType: Threat) {{
                    data
                    nextPageTimestamp
                  }}
                }}
              }}
            }}
            """
            result = self.run_query(query)
            events = result["data"]["reportData"]["report"]["events"]
            all_data.extend(events.get("data", []))
            next_page = events.get("nextPageTimestamp")
            if not next_page:
                break
            start_time = next_page
        return all_data

    # ── Character profile queries ──

    def get_character_profile(self, name: str, server_slug: str,
                              server_region: str,
                              api_url: str = None) -> CharacterProfile:
        """Fetch a full character profile from the WCL API."""
        original_url = self.API_URL
        if api_url:
            self.API_URL = api_url

        try:
            query = f"""
            {{
              characterData {{
                character(name: "{name}", serverSlug: "{server_slug}", serverRegion: "{server_region}") {{
                  name
                  classID
                  level
                  faction {{ name }}
                  guilds {{ name }}
                  zoneRankings
                  recentReports(limit: 20) {{
                    data {{
                      code
                      title
                      startTime
                      zone {{ name }}
                    }}
                  }}
                }}
              }}
            }}
            """
            result = self.run_query(query, use_cache=False)
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

            # Fetch additional zones the character has data in
            # (the default query returns only the current zone)

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

            return profile
        finally:
            self.API_URL = original_url

    def get_character_zone_rankings(self, name: str, server_slug: str,
                                     server_region: str, zone_id: int,
                                     metric: str = "dps",
                                     api_url: str = None) -> Optional[ZoneRankingResult]:
        """Fetch zone rankings for a specific zone."""
        original_url = self.API_URL
        if api_url:
            self.API_URL = api_url

        try:
            query = f"""
            {{
              characterData {{
                character(name: "{name}", serverSlug: "{server_slug}", serverRegion: "{server_region}") {{
                  zoneRankings(zoneID: {zone_id}, metric: {metric})
                }}
              }}
            }}
            """
            result = self.run_query(query, use_cache=False)
            char = result["data"]["characterData"]["character"]
            if not char:
                return None

            zr = char.get("zoneRankings")
            if zr and isinstance(zr, dict) and "error" not in zr:
                return self._parse_zone_rankings(zr)
            return None
        finally:
            self.API_URL = original_url

    def _parse_zone_rankings(self, zr: dict) -> ZoneRankingResult:
        all_stars = []
        for s in zr.get("allStars", []):
            all_stars.append(AllStarRanking(
                spec=s.get("spec", ""),
                points=s.get("points", 0),
                possible_points=s.get("possiblePoints", 0),
                rank=s.get("rank", 0),
                region_rank=s.get("regionRank", 0),
                server_rank=s.get("serverRank", 0),
                rank_percent=s.get("rankPercent", 0),
                total=s.get("total", 0),
            ))

        rankings = []
        for r in zr.get("rankings", []):
            enc = r.get("encounter", {})
            rankings.append(EncounterRanking(
                encounter_id=enc.get("id", 0),
                encounter_name=enc.get("name", ""),
                spec=r.get("spec", ""),
                best_percent=r.get("rankPercent", 0),
                median_percent=r.get("medianPercent", 0),
                total_kills=r.get("totalKills", 0),
                fastest_kill_ms=r.get("fastestKill", 0),
                locked_in=r.get("lockedIn", False),
            ))

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
