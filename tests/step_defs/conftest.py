"""BDD-specific fixtures for step definitions."""

import pytest


@pytest.fixture
def context():
    """Shared mutable state container for BDD scenarios."""
    return {}
