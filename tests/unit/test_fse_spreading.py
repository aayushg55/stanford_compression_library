"""Unit tests for FSE symbol spreading

Uses pytest fixtures and parameterization for comprehensive test coverage.
"""

import pytest
from scl.compressors.fse import FSEParams, build_spread_table
from scl.core.prob_dist import Frequencies
from tests.conftest import TEST_FREQUENCIES, TEST_TABLE_LOGS


########################################
# Test Data for Parameterization
########################################

# Spreading-specific test cases
SPREADING_TEST_CASES = [
    # (freq_dict, table_log, description)
    ({"A": 3, "B": 3, "C": 2}, 4, "balanced_3symbols"),
    ({"A": 8, "B": 8}, 4, "uniform_2symbols"),
    ({"A": 5, "B": 5, "C": 5, "D": 5}, 5, "uniform_4symbols"),
    ({"A": 1, "B": 1, "C": 2}, 4, "skewed_3symbols"),
    ({"A": 1, "B": 3}, 4, "highly_skewed"),
    ({"A": 1}, 4, "single_symbol"),
    ({"A": 10, "B": 20, "C": 30, "D": 40}, 6, "increasing_freqs"),
    ({"A": 1, "B": 1, "C": 1, "D": 1, "E": 1}, 4, "uniform_5symbols"),
]


########################################
# Basic Spreading Tests
########################################


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_spread_table_size(freq_dict, table_log, description):
    """Test that spread table has correct size for various distributions"""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)

    table_size = 1 << table_log
    assert (
        len(spread) == table_size
    ), f"{description}: Spread table should have size {table_size}"
    assert all(
        x is not None for x in spread
    ), f"{description}: All positions should be filled"


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_spread_table_counts(freq_dict, table_log, description):
    """Test that spread table has correct symbol counts for various distributions"""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)

    # Count occurrences - should match normalized frequencies
    counts = {}
    for s in spread:
        counts[s] = counts.get(s, 0) + 1

    # Counts should match normalized frequencies (not original frequencies)
    for s in norm_freq:
        assert (
            counts[s] == norm_freq[s]
        ), f"{description}: Symbol {s}: expected {norm_freq[s]}, got {counts.get(s, 0)}"
    assert sum(counts.values()) == len(
        spread
    ), f"{description}: Total counts should equal table size"


@pytest.mark.parametrize("freq_dict,table_log,description", SPREADING_TEST_CASES)
def test_spread_table_distribution(freq_dict, table_log, description):
    """Test that spread table distributes symbols (not all clustered)"""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)

    # Check that all symbols appear in spread
    for s in norm_freq:
        assert s in spread, f"{description}: Symbol {s} should appear in spread table"

    # For multi-symbol distributions, check that symbols are distributed
    if len(norm_freq) > 1:
        # Count transitions (adjacent positions with different symbols)
        transitions = sum(
            1 for i in range(len(spread) - 1) if spread[i] != spread[i + 1]
        )
        assert (
            transitions > 0
        ), f"{description}: Symbols should be distributed (found {transitions} transitions)"


########################################
# Table Size Tests
########################################


@pytest.mark.parametrize("table_log", TEST_TABLE_LOGS)
def test_spread_table_different_table_sizes(table_log):
    """Test spreading with different table sizes"""
    freq = Frequencies({"A": 5, "B": 5, "C": 5, "D": 5})
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)

    table_size = 1 << table_log
    assert len(spread) == table_size
    assert all(x is not None for x in spread)

    # Verify counts match normalized frequencies
    counts = {}
    for s in spread:
        counts[s] = counts.get(s, 0) + 1
    for s in norm_freq:
        assert (
            counts[s] == norm_freq[s]
        ), f"Table log {table_log}: Symbol {s} count mismatch"


@pytest.mark.parametrize("table_log", TEST_TABLE_LOGS)
def test_spread_table_all_sizes_uniform(table_log):
    """Test spreading with uniform distribution across all table sizes"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)

    table_size = 1 << table_log
    assert len(spread) == table_size
    assert all(x is not None for x in spread)

    # Verify all symbols appear
    for s in norm_freq:
        assert s in spread


########################################
# Edge Case Tests
########################################


def test_spread_table_single_symbol():
    """Test spreading with single symbol (edge case)"""
    freq = Frequencies({"A": 10})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, 4)

    assert len(spread) == 16
    assert all(x == "A" for x in spread), "All positions should be 'A'"


def test_spread_table_minimal_frequencies():
    """Test spreading with minimal frequencies (all = 1)"""
    freq = Frequencies({"A": 1, "B": 1, "C": 1, "D": 1})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, 4)

    assert len(spread) == 16
    assert all(x is not None for x in spread)

    # Each symbol should appear at least once
    for s in norm_freq:
        assert s in spread


def test_spread_table_extreme_skew():
    """Test spreading with extreme frequency skew"""
    freq = Frequencies({"A": 100, "B": 1})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, 4)

    assert len(spread) == 16
    assert all(x is not None for x in spread)

    # Both symbols should appear
    assert "A" in spread
    assert "B" in spread

    # A should appear much more frequently
    counts = {}
    for s in spread:
        counts[s] = counts.get(s, 0) + 1
    assert counts["A"] > counts["B"]


########################################
# Property Tests
########################################


@pytest.mark.parametrize("freq_dict,table_log,description", TEST_FREQUENCIES)
def test_spread_table_deterministic(freq_dict, table_log, description):
    """Test that spreading is deterministic (same input gives same output)"""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs

    spread1 = build_spread_table(norm_freq, table_log)
    spread2 = build_spread_table(norm_freq, table_log)

    assert spread1 == spread2, f"{description}: Spreading should be deterministic"


def test_spread_table_no_gaps():
    """Test that spread table has no gaps (all positions filled)"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, 4)

    # Check no None values
    assert None not in spread, "Spread table should have no gaps"

    # Check all positions are filled
    assert len([x for x in spread if x is not None]) == len(spread)


@pytest.mark.parametrize(
    "freq_dict,table_log,description",
    [
        ({"A": 1, "B": 1}, 4, "two_symbols"),
        (
            {"A": 1, "B": 1, "C": 1, "D": 1, "E": 1, "F": 1, "G": 1, "H": 1},
            4,
            "eight_symbols",
        ),
    ],
)
def test_spread_table_many_symbols(freq_dict, table_log, description):
    """Test spreading with many symbols"""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, table_log)

    table_size = 1 << table_log
    assert len(spread) == table_size
    assert all(x is not None for x in spread)

    # All symbols should appear
    for s in norm_freq:
        assert s in spread, f"{description}: Symbol {s} should appear"


def test_spread_table_step_property():
    """Test that FSE step algorithm produces good distribution"""
    freq = Frequencies({"A": 8, "B": 8})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)
    norm_freq = params.normalized_freqs
    spread = build_spread_table(norm_freq, 4)

    # With uniform distribution, symbols should be well-mixed
    # Check that we don't have long runs of the same symbol
    max_run_length = 1
    current_run = 1
    for i in range(1, len(spread)):
        if spread[i] == spread[i - 1]:
            current_run += 1
            max_run_length = max(max_run_length, current_run)
        else:
            current_run = 1

    # For uniform 2-symbol distribution in 16 positions, max run should be reasonable
    # (not all 8 of one symbol together)
    assert (
        max_run_length < len(spread) // 2
    ), f"Symbols should be well-distributed (max run: {max_run_length})"
