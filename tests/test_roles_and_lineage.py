"""Tests for role overrides and character lineage (min / mean / max across raids)."""

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from warcraftlogs_client.analysis import apply_role_overrides
from warcraftlogs_client.models import ConsumableUsage, PlayerIdentity, RaidComposition, SpellUsage
from warcraftlogs_client.services import (
    AppContext,
    RaidService,
    RoleOverrideService,
    character_lineage,
)

CODE_A = "AAAAbbbbCCCCdddd"
CODE_B = "BBBBccccDDDDeeee"
CODE_C = "CCCCddddEEEEffff"


def _composition():
    return RaidComposition(
        tanks=[PlayerIdentity("Tanky", "Warrior", 1, "tank")],
        healers=[PlayerIdentity("Holy", "Priest", 2, "healer")],
        melee=[PlayerIdentity("Stabby", "Rogue", 3, "melee"), PlayerIdentity("Enh", "Shaman", 4, "melee")],
        ranged=[PlayerIdentity("Boom", "Druid", 5, "ranged")],
    )


class TestApplyRoleOverrides:
    def test_moves_player_between_roles(self):
        comp, notes = apply_role_overrides(_composition(), {"enh": "healer"})
        assert [p.name for p in comp.healers] == ["Holy", "Enh"]
        assert comp.get_player("Enh").role == "healer"
        assert [p.name for p in comp.melee] == ["Stabby"]
        assert notes == ["Role override: Enh analysed as healer (detected melee)"]

    def test_matching_override_is_a_no_op(self):
        comp, notes = apply_role_overrides(_composition(), {"Holy": "healer", "Stabby": "dps"})
        assert notes == []
        assert comp.get_player("Stabby").role == "melee"

    def test_dps_picks_by_class_then_classifier(self):
        classify = MagicMock(return_value="ranged")
        comp, _ = apply_role_overrides(_composition(), {"Tanky": "dps", "Holy": "dps"}, classify_dps=classify)
        assert comp.get_player("Tanky").role == "melee"  # warriors are always melee
        assert comp.get_player("Holy").role == "ranged"  # hybrid: asks the damage-profile classifier
        classify.assert_called_once()
        assert classify.call_args.args[0].name == "Holy"

    def test_unknown_role_and_absent_player_ignored(self):
        comp, notes = apply_role_overrides(_composition(), {"Holy": "bard", "Nobody": "tank"})
        assert notes == [] and len(comp.all_players) == 5


@pytest.fixture
def ctx(tmp_path):
    return AppContext(config={}, db_path=str(tmp_path / "roles.db"), _client=MagicMock())


class TestRaidServicePassesOverrides:
    def test_overrides_reach_analyze_raid(self, ctx):
        with ctx.db() as db:
            db.set_role_override("Holy", "tank")
            db.set_role_override("Enh", "ranged", CODE_B)  # another raid: not included
        with patch("warcraftlogs_client.services.raids.analyze_raid") as analyze:
            RaidService(ctx).analyze(CODE_A)
        assert analyze.call_args.kwargs["role_overrides"] == {"Holy": "tank"}

    def test_raid_specific_override_wins(self, ctx):
        with ctx.db() as db:
            db.set_role_override("Holy", "tank")
            db.set_role_override("Holy", "dps", CODE_A)
            assert db.get_role_overrides_for_report(CODE_A) == {"Holy": "dps"}
            assert db.get_role_overrides_for_report(CODE_B) == {"Holy": "tank"}

    def test_no_overrides_passes_none(self, ctx):
        with patch("warcraftlogs_client.services.raids.analyze_raid") as analyze:
            RaidService(ctx).analyze(CODE_A)
        assert analyze.call_args.kwargs["role_overrides"] is None


@pytest.mark.database
class TestRoleOverrideService:
    @pytest.fixture
    def stored(self, db, build_analysis):
        """HolyPriest stored as healer in A and B; C is a reference raid."""
        db.import_raid(build_analysis(report_id=CODE_A))
        db.import_raid(build_analysis(report_id=CODE_B))
        db.import_raid(build_analysis(report_id=CODE_C), source="reference")
        return db

    @pytest.fixture
    def as_dps(self, build_analysis):
        """Analyzer that returns HolyPriest as ranged dps (what the override asks for)."""
        calls = []

        def _analyze(code, reference=False):
            calls.append((code, reference))
            a = build_analysis(report_id=code, dps_name="HolyPriest", dps_class="Priest", dps_role="ranged")
            a.healers = []
            a.composition.healers = []
            return a

        _analyze.calls = calls
        return _analyze

    def test_set_reanalyses_only_disagreeing_raids(self, stored, as_dps):
        results = RoleOverrideService(stored, analyze=as_dps).set("holypriest", "dps")
        assert sorted(r.report_id for r in results) == [CODE_A, CODE_B, CODE_C]
        assert sorted(as_dps.calls) == [(CODE_A, False), (CODE_B, False), (CODE_C, True)]  # reference raid
        assert all(r.ok and r.old_role == "healer" for r in results)
        roles = {r["report_id"]: r["role"] for r in stored.get_character_raid_roles("HolyPriest", ("guild",))}
        assert roles == {CODE_A: "ranged", CODE_B: "ranged"}  # healer rows replaced, not merged
        assert stored.get_raid_source(CODE_C) == "reference"  # source preserved

        as_dps.calls.clear()
        assert RoleOverrideService(stored, analyze=as_dps).set("HolyPriest", "ranged") == []
        assert as_dps.calls == []

    def test_set_for_one_report(self, stored, as_dps):
        results = RoleOverrideService(stored, analyze=as_dps).set("HolyPriest", "dps", CODE_B)
        assert [r.report_id for r in results] == [CODE_B]
        assert stored.get_role_overrides("HolyPriest")[0]["report_id"] == CODE_B

    def test_reanalysis_keeps_cache(self, stored, as_dps):
        with patch("warcraftlogs_client.database.clear_response_cache") as clear:
            RoleOverrideService(stored, analyze=as_dps).set("HolyPriest", "dps", CODE_A)
        clear.assert_not_called()

    def test_no_reanalyze_only_saves(self, stored, as_dps):
        assert RoleOverrideService(stored, analyze=as_dps).set("HolyPriest", "tank", reanalyze=False) == []
        assert as_dps.calls == []
        assert stored.get_role_overrides("HolyPriest")[0]["role"] == "tank"

    def test_without_api_reports_what_needs_reanalysis(self, stored):
        results = RoleOverrideService(stored).set("HolyPriest", "tank")
        assert len(results) == 3 and not any(r.ok for r in results)

    def test_failure_leaves_raid_untouched(self, stored):
        def boom(code, reference=False):
            raise ValueError("Report not found or inaccessible")

        results = RoleOverrideService(stored, analyze=boom).set("HolyPriest", "tank", CODE_A)
        assert not results[0].ok and "inaccessible" in results[0].message
        assert stored.is_raid_imported(CODE_A)

    def test_clear_reguesses_raids_the_override_covered(self, stored, as_dps, build_analysis):
        def moved(code, reference=False):
            a = as_dps(code)
            a.role_overrides_applied = {"HolyPriest": "healer"}
            return a

        RoleOverrideService(stored, analyze=moved).set("HolyPriest", "dps")
        assert stored.get_role_override_raids("holypriest") == {CODE_A, CODE_B, CODE_C}
        detect = RoleOverrideService(stored, analyze=lambda code, reference=False: build_analysis(report_id=code))
        results = detect.clear("HolyPriest")
        assert sorted(r.report_id for r in results) == [CODE_A, CODE_B, CODE_C]
        assert stored.get_role_overrides("HolyPriest") == []
        assert stored.get_role_override_raids("HolyPriest") == set()
        assert RoleOverrideService(stored).clear("HolyPriest") == []  # nothing left to clear

    def test_clear_skips_raids_the_override_never_moved(self, stored, as_dps):
        # Saved without re-analysis and matching detection everywhere: nothing was moved.
        RoleOverrideService(stored).set("HolyPriest", "healer", reanalyze=False)
        assert RoleOverrideService(stored, analyze=as_dps).clear("HolyPriest") == []
        assert as_dps.calls == []

    def test_reanalysis_keeps_label_and_source(self, stored, as_dps):
        conn = stored._get_conn()
        conn.execute("UPDATE raids SET label = 'Kara alt run' WHERE report_id = ?", (CODE_A,))
        conn.commit()
        raid_id = conn.execute("SELECT id FROM raids WHERE report_id = ?", (CODE_A,)).fetchone()["id"]
        RoleOverrideService(stored, analyze=as_dps).set("HolyPriest", "dps", CODE_A)
        row = conn.execute("SELECT id, label, source FROM raids WHERE report_id = ?", (CODE_A,)).fetchone()
        assert (row["id"], row["label"], row["source"]) == (raid_id, "Kara alt run", "guild")

    def test_failed_import_rolls_back(self, stored, as_dps):
        before = stored.get_character_raid_roles("HolyPriest", ("guild",))
        with patch.object(stored, "_import_tank", side_effect=sqlite3.OperationalError("disk I/O error")):
            results = RoleOverrideService(stored, analyze=as_dps).set("HolyPriest", "dps", CODE_A)
        assert not results[0].ok and "disk I/O" in results[0].message
        assert stored.get_character_raid_roles("HolyPriest", ("guild",)) == before

    @pytest.mark.parametrize("role,report", [("bard", None), ("healer", "not-a-code")])
    def test_rejects_bad_input(self, stored, role, report):
        with pytest.raises(ValueError):
            RoleOverrideService(stored).set("HolyPriest", role, report)


@pytest.mark.database
class TestLineage:
    @pytest.fixture
    def history(self, db, build_analysis):
        """Three raids: HolyPriest heals in two (40 and 60 Greater Heals), plays ranged dps in one."""
        for code, casts, healing, pots in ((CODE_A, 40, 1000, 2), (CODE_B, 60, 3000, 0)):
            a = build_analysis(report_id=code, healer_healing=healing)
            a.healers[0].spells = [SpellUsage(spell_id=2060, spell_name="Greater Heal", casts=casts)]
            if pots:
                a.consumables = [ConsumableUsage("HolyPriest", "healer", code, "Super Mana Potion", pots)]
            db.import_raid(a)
        c = build_analysis(
            report_id=CODE_C, dps_name="HolyPriest", dps_class="Priest", dps_role="ranged", dps_damage=500
        )
        c.healers, c.composition.healers = [], []
        c.dps[0].abilities = [SpellUsage(spell_id=589, spell_name="Shadow Word: Pain", casts=12)]
        c.consumables = [ConsumableUsage("HolyPriest", "ranged", CODE_C, "Super Mana Potion", 4)]
        db.import_raid(c)
        return db

    def test_headline_and_role_counts(self, history):
        lineage = character_lineage(history, "holypriest")
        assert lineage.raids == 3
        assert lineage.role_counts == {"healer": 2, "ranged": 1}
        healing = next(m for m in lineage.metrics if m.name == "Healing")
        assert (healing.min, healing.mean, healing.max, healing.raids) == (1000, 2000, 3000, 2)
        damage = next(m for m in lineage.metrics if m.name == "Damage")
        assert (damage.role, damage.raids, damage.mean) == ("ranged", 1, 500)

    def test_casts_are_averaged_within_their_role(self, history):
        casts = {c.name: c for c in character_lineage(history, "HolyPriest").casts}
        gh = casts["Greater Heal"]
        assert (gh.role, gh.min, gh.mean, gh.max, gh.raids) == ("healer", 40, 50, 60, 2)
        swp = casts["Shadow Word: Pain"]
        assert (swp.role, swp.raids, swp.mean) == ("ranged", 1, 12)
        total = next(m for m in character_lineage(history, "HolyPriest").metrics if m.name == "Total casts")
        assert (total.min, total.max, total.raids) == (12, 60, 3)

    def test_consumables_count_zero_raids(self, history):
        pots = character_lineage(history, "HolyPriest").consumables[0]
        assert pots.name == "Super Mana Potion"
        assert (pots.min, pots.mean, pots.max, pots.raids, pots.raids_used) == (0, 2, 4, 3, 2)

    def test_sources_filter_and_unknown_character(self, history):
        assert character_lineage(history, "Nobody") is None
        assert character_lineage(history, "HolyPriest", sources=("reference",)) is None

    def test_json_round_trip(self, history):
        payload = json.loads(json.dumps(character_lineage(history, "HolyPriest").to_dict()))
        assert payload["casts"][0]["name"] == "Greater Heal"


class TestPlayerCliRoleAndLineage:
    @pytest.fixture
    def run_cli(self, tmp_path, capsys, build_analysis):
        from warcraftlogs_client import cli

        ctx = AppContext(config={"default_server": "s", "default_region": "eu"}, db_path=str(tmp_path / "c.db"))
        with ctx.db() as db:
            db.import_raid(build_analysis(report_id=CODE_A))

        def _run(*argv):
            with (
                patch("sys.argv", ["warcraftlogs", *argv]),
                patch("warcraftlogs_client.services.AppContext.from_config_file", return_value=ctx),
            ):
                code = cli.main()
            return code, capsys.readouterr().out

        return _run

    def test_role_set_list_clear_without_reanalysis(self, run_cli):
        code, out = run_cli("player", "role", "HolyPriest", "tank", "--no-reanalyze")
        assert code == 0 and "tank for every raid" in out
        code, out = run_cli("player", "role", "HolyPriest", "--json")
        assert json.loads(out)[0]["role"] == "tank"
        code, out = run_cli("player", "role", "HolyPriest", "--clear", "--no-reanalyze")
        assert code == 0 and "override cleared" in out
        code, out = run_cli("player", "role", "HolyPriest")
        assert "No role override" in out

    def test_role_rejects_bad_report(self, run_cli):
        code, out = run_cli("player", "role", "HolyPriest", "tank", "--report", "nope")
        assert code == 1 and "Not a report" in out

    def test_lineage_table_and_json(self, run_cli):
        code, out = run_cli("player", "lineage", "HolyPriest")
        assert code == 0 and "Greater Heal" in out and "1 raids (1 healer)" in out
        code, out = run_cli("player", "lineage", "HolyPriest", "--json")
        assert json.loads(out)["raids"] == 1
        code, out = run_cli("player", "lineage", "Nobody")
        assert code == 1
