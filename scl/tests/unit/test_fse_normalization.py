"""Unit tests for FSE frequency normalization

Uses pytest fixtures and parameterization for comprehensive test coverage.
"""

import pytest
from scl.compressors.fse import FSEParams
from scl.core.prob_dist import Frequencies
from tests.conftest import TEST_TABLE_LOGS


########################################
# Test Data for Parameterization
########################################

# Normalization-specific test cases
NORMALIZATION_TEST_CASES = [
    # (freq_dict, table_log, description, expected_properties)
    ({"A": 3, "B": 3, "C": 2}, 4, "balanced_3symbols", {"sum": 16, "min_freq": 1}),
    (
        {"A": 6, "B": 3, "C": 1},
        4,
        "skewed_3symbols",
        {"sum": 16, "ratios": [("A", "B"), ("B", "C")]},
    ),
    ({"A": 1, "B": 1, "C": 1}, 4, "uniform_3symbols", {"sum": 16, "min_freq": 1}),
    ({"A": 10}, 4, "single_symbol", {"sum": 16, "single_value": 16}),
    ({"A": 100, "B": 1}, 4, "very_skewed", {"sum": 16, "A_greater_B": True}),
    ({"A": 1, "B": 3}, 4, "highly_skewed", {"sum": 16, "B_greater_A": True}),
    (
        {"A": 5, "B": 5, "C": 5, "D": 5},
        5,
        "uniform_4symbols",
        {"sum": 32, "min_freq": 1},
    ),
    (
        {"A": 10, "B": 20, "C": 30, "D": 40},
        6,
        "increasing_freqs",
        {"sum": 64, "order": ["A", "B", "C", "D"]},
    ),
    (
        {"A": 1, "B": 1, "C": 1, "D": 1, "E": 1},
        4,
        "uniform_5symbols",
        {"sum": 16, "min_freq": 1},
    ),
]

EDGE_CASE_FREQUENCIES = [
    # (freq_dict, table_log, description)
    ({"A": 1, "B": 1, "C": 1}, 4, "minimal_freqs"),
    ({"A": 100, "B": 1}, 4, "extreme_ratio"),
    ({"A": 1}, 4, "single_symbol_minimal"),
    ({"A": 1000, "B": 1, "C": 1}, 4, "very_dominant_symbol"),
]


########################################
# Basic Normalization Tests
########################################


@pytest.mark.parametrize(
    "freq_dict,table_log,description,expected", NORMALIZATION_TEST_CASES
)
def test_normalize_frequencies_sum(freq_dict, table_log, description, expected):
    """Test that normalized frequencies sum to table_size"""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    table_size = 1 << table_log

    assert (
        sum(params.normalized_freqs.values()) == table_size
    ), f"{description}: Sum should be {table_size}"


@pytest.mark.parametrize(
    "freq_dict,table_log,description,expected", NORMALIZATION_TEST_CASES
)
def test_normalize_frequencies_min_freq(freq_dict, table_log, description, expected):
    """Test that all symbols have at least frequency 1 after normalization"""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)

    for s in freq.alphabet:
        assert (
            params.normalized_freqs[s] >= 1
        ), f"{description}: Symbol {s} should have freq >= 1"


@pytest.mark.parametrize(
    "freq_dict,table_log,description,expected", NORMALIZATION_TEST_CASES
)
def test_normalize_frequencies_preserves_order(
    freq_dict, table_log, description, expected
):
    """Test that normalization preserves frequency order"""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    norm = params.normalized_freqs

    # Check specific ratio properties if specified
    if "ratios" in expected:
        for sym1, sym2 in expected["ratios"]:
            assert (
                norm[sym1] >= norm[sym2]
            ), f"{description}: {sym1} should have >= freq than {sym2}"

    if "A_greater_B" in expected and expected["A_greater_B"]:
        assert (
            norm["A"] > norm["B"]
        ), f"{description}: A should have greater freq than B"

    if "B_greater_A" in expected and expected["B_greater_A"]:
        assert (
            norm["B"] > norm["A"]
        ), f"{description}: B should have greater freq than A"

    if "order" in expected:
        symbols = expected["order"]
        for i in range(len(symbols) - 1):
            assert (
                norm[symbols[i]] < norm[symbols[i + 1]]
            ), f"{description}: {symbols[i]} should have < freq than {symbols[i + 1]}"


def test_normalize_frequencies_single_symbol():
    """Test normalization with single symbol (special case)"""
    freq = Frequencies({"A": 10})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)

    assert params.normalized_freqs["A"] == 16
    assert sum(params.normalized_freqs.values()) == 16


########################################
# Table Size Tests
########################################


@pytest.mark.parametrize("table_log", TEST_TABLE_LOGS)
def test_normalize_frequencies_different_table_sizes(table_log):
    """Test normalization with different table sizes"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    table_size = 1 << table_log

    assert sum(params.normalized_freqs.values()) == table_size
    for s in freq.alphabet:
        assert params.normalized_freqs[s] >= 1


@pytest.mark.parametrize("table_log", TEST_TABLE_LOGS)
def test_normalize_frequencies_large_table_uniform(table_log):
    """Test normalization with uniform distribution across table sizes"""
    freq = Frequencies({"A": 5, "B": 5, "C": 5, "D": 5})
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    table_size = 1 << table_log

    assert sum(params.normalized_freqs.values()) == table_size
    # For uniform distribution, frequencies should be approximately equal
    norm_values = list(params.normalized_freqs.values())
    max_freq = max(norm_values)
    min_freq = min(norm_values)
    # Allow some variation due to rounding
    assert (
        max_freq - min_freq <= 1
    ), f"Uniform distribution should have similar frequencies (max={max_freq}, min={min_freq})"


########################################
# Edge Case Tests
########################################


@pytest.mark.parametrize("freq_dict,table_log,description", EDGE_CASE_FREQUENCIES)
def test_normalize_frequencies_edge_cases(freq_dict, table_log, description):
    """Test normalization with edge cases"""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    table_size = 1 << table_log

    assert (
        sum(params.normalized_freqs.values()) == table_size
    ), f"{description}: Sum should be {table_size}"
    for s in freq.alphabet:
        assert (
            params.normalized_freqs[s] >= 1
        ), f"{description}: Symbol {s} should have freq >= 1"


def test_normalize_frequencies_minimal_input():
    """Test normalization with minimal input (all frequencies = 1)"""
    freq = Frequencies({"A": 1, "B": 1, "C": 1})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)

    assert sum(params.normalized_freqs.values()) == 16
    # All should get at least 1, and the rest distributed
    for s in freq.alphabet:
        assert params.normalized_freqs[s] >= 1


def test_normalize_frequencies_extreme_ratio():
    """Test normalization with extreme frequency ratio"""
    freq = Frequencies({"A": 1000, "B": 1})
    params = FSEParams(freq, TABLE_SIZE_LOG2=4)

    assert sum(params.normalized_freqs.values()) == 16
    assert params.normalized_freqs["A"] > params.normalized_freqs["B"]
    # A should get most of the table
    assert params.normalized_freqs["A"] >= 14  # Most of 16


########################################
# Property Tests
########################################


def test_normalize_frequencies_idempotent():
    """Test that normalization is consistent (same input gives same output)"""
    freq = Frequencies({"A": 3, "B": 3, "C": 2})
    params1 = FSEParams(freq, TABLE_SIZE_LOG2=4)
    params2 = FSEParams(freq, TABLE_SIZE_LOG2=4)

    assert params1.normalized_freqs == params2.normalized_freqs


def test_normalize_frequencies_scales_proportionally():
    """Test that normalization scales frequencies proportionally"""
    freq1 = Frequencies({"A": 3, "B": 3, "C": 2})
    freq2 = Frequencies({"A": 6, "B": 6, "C": 4})  # 2x frequencies

    params1 = FSEParams(freq1, TABLE_SIZE_LOG2=4)
    params2 = FSEParams(freq2, TABLE_SIZE_LOG2=4)

    # Both should normalize to same relative frequencies
    # (though absolute values might differ slightly due to rounding)
    ratio1 = params1.normalized_freqs["A"] / params1.normalized_freqs["C"]
    ratio2 = params2.normalized_freqs["A"] / params2.normalized_freqs["C"]
    # Ratios should be approximately equal (within rounding error)
    assert abs(ratio1 - ratio2) < 0.5, f"Ratios should be similar: {ratio1} vs {ratio2}"


@pytest.mark.parametrize(
    "freq_dict,table_log,description",
    [
        ({"A": 1, "B": 1}, 4, "two_symbols_minimal"),
        (
            {"A": 1, "B": 1, "C": 1, "D": 1, "E": 1, "F": 1, "G": 1, "H": 1},
            4,
            "eight_symbols_minimal",
        ),
    ],
)
def test_normalize_frequencies_many_symbols(freq_dict, table_log, description):
    """Test normalization with many symbols (each with minimal frequency)"""
    freq = Frequencies(freq_dict)
    params = FSEParams(freq, TABLE_SIZE_LOG2=table_log)
    table_size = 1 << table_log

    assert sum(params.normalized_freqs.values()) == table_size
    # Each symbol should get at least 1, and the rest distributed
    for s in freq.alphabet:
        assert params.normalized_freqs[s] >= 1
    # With many symbols, frequencies should be relatively uniform
    norm_values = list(params.normalized_freqs.values())
    max_freq = max(norm_values)
    min_freq = min(norm_values)
    # Allow some variation
    assert (
        max_freq - min_freq <= 2
    ), f"{description}: Frequencies should be relatively uniform"
