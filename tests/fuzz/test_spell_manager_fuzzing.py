"""Property-based fuzz testing of SpellManager."""

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from warcraftlogs_client.spell_manager import SpellManager


@pytest.mark.fuzz
class TestSpellManagerFuzzing:
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(spell_id=st.integers())
    def test_get_canonical_id_arbitrary(self, spell_id, tmp_path):
        """get_canonical_id should return an integer for any input."""
        manager = SpellManager(spell_data_dir=str(tmp_path))
        result = manager.get_canonical_id(spell_id)
        assert isinstance(result, int)

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(spell_id=st.integers())
    def test_get_spell_name_arbitrary(self, spell_id, tmp_path):
        """get_spell_name should return a string for any input."""
        manager = SpellManager(spell_data_dir=str(tmp_path))
        result = manager.get_spell_name(spell_id)
        assert isinstance(result, str)

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(canonical_id=st.integers())
    def test_get_variant_ids_arbitrary(self, canonical_id, tmp_path):
        """get_variant_ids should return a set for any input."""
        manager = SpellManager(spell_data_dir=str(tmp_path))
        result = manager.get_variant_ids(canonical_id)
        assert isinstance(result, set)
        assert canonical_id in result

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        events=st.lists(
            st.fixed_dictionaries(
                {
                    "abilityGameID": st.integers(),
                    "amount": st.integers(),
                }
            ),
            max_size=20,
        )
    )
    def test_process_spell_events_arbitrary(self, events, tmp_path):
        """process_spell_events should not crash on arbitrary event lists."""
        manager = SpellManager(spell_data_dir=str(tmp_path))
        result = manager.process_spell_events(events)
        assert isinstance(result, dict)
        for key, value in result.items():
            assert isinstance(key, int)
            assert isinstance(value, int)
