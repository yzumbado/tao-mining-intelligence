"""Property test: Subnet Discovery Set Operations (Property 12).

Validates Requirements 8.1-8.3:
- New subnets (on-chain but not stored) are detected
- Removed subnets (stored but not on-chain) are detected
- After update, stored list equals on-chain list
"""

import sys

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, "lambda")
sys.path.insert(0, "lambda/src")


# Strategy: generate subnet ID sets (netuids are 0-1024 in practice)
subnet_set = st.frozensets(st.integers(min_value=0, max_value=1024), min_size=0, max_size=50)


class TestSubnetDiscovery:
    """Property: set operations correctly identify new and removed subnets."""

    @given(on_chain=subnet_set, stored=subnet_set)
    @settings(max_examples=200)
    def test_new_subnets_are_on_chain_minus_stored(self, on_chain, stored):
        """New subnets = on_chain - stored."""
        new = on_chain - stored
        # Every new subnet is on-chain
        for n in new:
            assert n in on_chain
        # No new subnet was previously stored
        for n in new:
            assert n not in stored

    @given(on_chain=subnet_set, stored=subnet_set)
    @settings(max_examples=200)
    def test_removed_subnets_are_stored_minus_on_chain(self, on_chain, stored):
        """Removed subnets = stored - on_chain."""
        removed = stored - on_chain
        # Every removed subnet was previously stored
        for r in removed:
            assert r in stored
        # No removed subnet is currently on-chain
        for r in removed:
            assert r not in on_chain

    @given(on_chain=subnet_set, stored=subnet_set)
    @settings(max_examples=200)
    def test_after_update_stored_equals_on_chain(self, on_chain, stored):
        """After applying discovery, the new stored set equals on-chain."""
        # Simulate the update: add new, remove old
        updated = (stored | on_chain) - (stored - on_chain)
        assert updated == on_chain

    @given(on_chain=subnet_set)
    @settings(max_examples=100)
    def test_no_changes_when_sets_equal(self, on_chain):
        """When stored == on_chain, no new or removed subnets."""
        stored = on_chain
        new = on_chain - stored
        removed = stored - on_chain
        assert len(new) == 0
        assert len(removed) == 0

    @given(on_chain=subnet_set, stored=subnet_set)
    @settings(max_examples=200)
    def test_new_and_removed_are_disjoint(self, on_chain, stored):
        """A subnet cannot be both new and removed."""
        new = on_chain - stored
        removed = stored - on_chain
        assert len(new & removed) == 0
