"""Property-based fuzz testing of data model constructors."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from warcraftlogs_client.models import (
    DPSPerformance,
    HealerPerformance,
    RaidMetadata,
    TankPerformance,
)


@pytest.mark.fuzz
class TestModelFuzzing:
    @settings(max_examples=50)
    @given(st.text(), st.text(), st.text(), st.integers(), st.integers())
    def test_raid_metadata_arbitrary(self, report_id, title, owner, start, end):
        """RaidMetadata should accept any values without crashing the constructor."""
        meta = RaidMetadata(
            report_id=report_id,
            title=title,
            owner=owner,
            start_time=start,
            end_time=end,
        )
        assert meta.report_id == report_id
        assert meta.title == title
        assert meta.owner == owner
        assert meta.start_time == start
        assert meta.end_time == end

    @settings(max_examples=50)
    @given(st.text(), st.text(), st.integers(), st.integers(), st.integers())
    def test_healer_performance_arbitrary(self, name, player_class, source_id, healing, overhealing):
        """HealerPerformance constructor should not crash."""
        hp = HealerPerformance(
            name=name,
            player_class=player_class,
            source_id=source_id,
            total_healing=healing,
            total_overhealing=overhealing,
        )
        assert hp.name == name
        assert hp.player_class == player_class
        assert hp.source_id == source_id
        # __post_init__ computes overheal_percent safely
        assert isinstance(hp.overheal_percent, float)

    @settings(max_examples=50)
    @given(st.text(), st.text(), st.integers(), st.integers(), st.integers())
    def test_tank_performance_arbitrary(self, name, player_class, source_id, taken, mitigated):
        """TankPerformance constructor should not crash."""
        tp = TankPerformance(
            name=name,
            player_class=player_class,
            source_id=source_id,
            total_damage_taken=taken,
            total_mitigated=mitigated,
        )
        assert tp.name == name
        assert tp.player_class == player_class
        assert tp.source_id == source_id
        # __post_init__ computes mitigation_percent safely
        assert isinstance(tp.mitigation_percent, float)

    @settings(max_examples=50)
    @given(st.text(), st.text(), st.integers(), st.sampled_from(["melee", "ranged"]), st.integers())
    def test_dps_performance_arbitrary(self, name, player_class, source_id, role, damage):
        """DPSPerformance constructor should not crash."""
        dp = DPSPerformance(
            name=name,
            player_class=player_class,
            source_id=source_id,
            role=role,
            total_damage=damage,
        )
        assert dp.name == name
        assert dp.role in ("melee", "ranged")
        assert dp.total_damage == damage
