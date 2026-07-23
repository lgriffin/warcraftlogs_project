"""API surface snapshot tests to detect accidental breaking changes.

These tests lock down the public interface of key modules so that
renames, removals, or field changes are caught during CI.
"""

import dataclasses


class TestPublicExports:
    def test_models_exports(self):
        """Snapshot of all public model classes."""
        import warcraftlogs_client.models as models

        public = sorted(
            name
            for name in dir(models)
            if not name.startswith("_")
            and isinstance(getattr(models, name), type)
            and getattr(getattr(models, name), "__module__", "") == models.__name__
        )
        expected = [
            "AllStarRanking",
            "AuraBand",
            "AuraUptime",
            "BossEvent",
            "CancelledCastCorrelation",
            "CancelledCastDetail",
            "CancelledCastSummary",
            "CharacterHistory",
            "CharacterProfile",
            "CharacterReportEntry",
            "ConsumableUsage",
            "ConsumesAnalysisResult",
            "DPSPerformance",
            "DispelUsage",
            "EncounterPerformance",
            "EncounterRanking",
            "EncounterSummary",
            "GearItem",
            "HealerPerformance",
            "InterruptUsage",
            "NextCastInfo",
            "PlayerIdentity",
            "PotionSpike",
            "RaidAnalysis",
            "RaidComposition",
            "RaidGroup",
            "RaidMetadata",
            "ResourceUsage",
            "SpellUsage",
            "TankPerformance",
            "ZoneRankingResult",
        ]
        assert public == expected, f"Public model exports changed! Got: {public}"

    def test_raid_metadata_fields(self):
        """Snapshot of RaidMetadata dataclass fields."""
        from warcraftlogs_client.models import RaidMetadata

        fields = sorted(f.name for f in dataclasses.fields(RaidMetadata))
        expected = ["end_time", "owner", "report_id", "start_time", "title", "zone"]
        assert fields == expected, f"RaidMetadata fields changed! Got: {fields}"

    def test_healer_performance_fields(self):
        """Snapshot of HealerPerformance fields."""
        from warcraftlogs_client.models import HealerPerformance

        fields = sorted(f.name for f in dataclasses.fields(HealerPerformance))
        expected = [
            "active_time_percent",
            "dispels",
            "fear_ward_casts",
            "name",
            "overheal_percent",
            "player_class",
            "resources",
            "source_id",
            "spells",
            "total_healing",
            "total_overhealing",
        ]
        assert fields == expected, f"HealerPerformance fields changed! Got: {fields}"

    def test_tank_performance_fields(self):
        """Snapshot of TankPerformance fields."""
        from warcraftlogs_client.models import TankPerformance

        fields = sorted(f.name for f in dataclasses.fields(TankPerformance))
        expected = [
            "abilities_used",
            "active_time_percent",
            "damage_taken_breakdown",
            "mitigation_percent",
            "name",
            "player_class",
            "source_id",
            "total_damage_taken",
            "total_mitigated",
        ]
        assert fields == expected, f"TankPerformance fields changed! Got: {fields}"

    def test_raid_analysis_fields(self):
        """Snapshot of RaidAnalysis fields."""
        from warcraftlogs_client.models import RaidAnalysis

        fields = sorted(f.name for f in dataclasses.fields(RaidAnalysis))
        expected = [
            "aura_uptimes",
            "cancelled_casts",
            "composition",
            "consumables",
            "dps",
            "encounters",
            "healers",
            "interrupts",
            "metadata",
            "tanks",
            "totem_uptimes",
            "warnings",
        ]
        assert fields == expected, f"RaidAnalysis fields changed! Got: {fields}"

    def test_database_tables(self, db):
        """Snapshot of database schema tables."""
        conn = db._get_conn()
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        tables = sorted(r["name"] for r in rows if r["name"] != "sqlite_sequence")
        expected = [
            "aura_uptime",
            "cancelled_cast_spells",
            "cancelled_casts",
            "characters",
            "consumable_usage",
            "dps_abilities",
            "dps_performance",
            "encounter_performance",
            "encounters",
            "healer_performance",
            "healer_spells",
            "interrupt_usage",
            "raid_group_members",
            "raid_groups",
            "raids",
            "schema_version",
            "tank_abilities",
            "tank_damage_taken",
            "tank_performance",
            "totem_uptime",
        ]
        assert tables == expected, f"Database tables changed! Got: {tables}"

    def test_cli_subcommands(self):
        """Snapshot of CLI subcommand structure."""
        from warcraftlogs_client.cli import create_parser

        parser = create_parser()

        # Extract subcommand names from the parser
        subcommands = set()
        for action in parser._subparsers._group_actions:
            subcommands.update(action.choices.keys())

        expected = {"unified", "healer", "tank", "melee", "ranged", "consumes", "history"}
        assert subcommands == expected, f"CLI subcommands changed! Got: {subcommands}"

    def test_dps_performance_fields(self):
        """Snapshot of DPSPerformance fields."""
        from warcraftlogs_client.models import DPSPerformance

        fields = sorted(f.name for f in dataclasses.fields(DPSPerformance))
        expected = [
            "abilities",
            "active_time_percent",
            "name",
            "player_class",
            "role",
            "source_id",
            "total_damage",
        ]
        assert fields == expected, f"DPSPerformance fields changed! Got: {fields}"

    def test_character_profile_fields(self):
        """Snapshot of CharacterProfile fields."""
        from warcraftlogs_client.models import CharacterProfile

        fields = sorted(f.name for f in dataclasses.fields(CharacterProfile))
        expected = [
            "class_id",
            "faction",
            "gear_items",
            "guild_name",
            "level",
            "name",
            "recent_reports",
            "region",
            "server",
            "zone_rankings",
        ]
        assert fields == expected, f"CharacterProfile fields changed! Got: {fields}"

    def test_config_manager_public_methods(self):
        """Snapshot of ConfigManager public API."""
        from warcraftlogs_client.config import ConfigManager

        public_methods = sorted(
            name for name in dir(ConfigManager) if not name.startswith("_") and callable(getattr(ConfigManager, name))
        )
        assert "load" in public_methods
        assert "get_role_thresholds" in public_methods

    def test_performance_db_public_methods(self):
        """Snapshot of key PerformanceDB query methods."""
        from warcraftlogs_client.database import PerformanceDB

        public_methods = sorted(
            name for name in dir(PerformanceDB) if not name.startswith("_") and callable(getattr(PerformanceDB, name))
        )
        # Verify critical methods exist
        critical_methods = [
            "import_raid",
            "get_character_history",
            "get_all_characters",
            "get_healer_trend",
            "get_tank_trend",
            "get_dps_trend",
            "get_raid_list",
            "delete_raid",
            "initialize",
            "close",
        ]
        for method in critical_methods:
            assert method in public_methods, f"Critical method {method!r} missing from PerformanceDB"
