"""Shared pytest fixtures and test data for FSE tests

This file is automatically discovered by pytest and makes fixtures available
to all test files in the tests/ directory.
"""

import pytest
from scl.compressors.fse import (
    FSEParams,
    build_spread_table,
    build_decode_table,
    build_encode_table,
)
from scl.core.prob_dist import Frequencies


########################################
# Common Fixtures
########################################


@pytest.fixture
def basic_freq():
    """Basic frequency distribution for testing"""
    return Frequencies({"A": 3, "B": 3, "C": 2})


@pytest.fixture
def basic_params(basic_freq):
    """Basic FSE params with small table for fast tests"""
    return FSEParams(basic_freq, TABLE_SIZE_LOG2=4)


@pytest.fixture
def basic_encoder(basic_params):
    """Basic FSE encoder"""
    from scl.compressors.fse import FSEEncoder

    return FSEEncoder(basic_params)


@pytest.fixture
def basic_decoder(basic_params):
    """Basic FSE decoder"""
    from scl.compressors.fse import FSEDecoder

    return FSEDecoder(basic_params)


@pytest.fixture
def basic_tables(basic_params):
    """Build all tables for basic test case"""
    norm_freq = basic_params.normalized_freqs
    table_log = basic_params.TABLE_SIZE_LOG2
    spread = build_spread_table(norm_freq, table_log)
    DTable = build_decode_table(spread, norm_freq, table_log)
    tableU16, symbolTT = build_encode_table(spread, norm_freq, table_log)
    return {
        "spread": spread,
        "DTable": DTable,
        "tableU16": tableU16,
        "symbolTT": symbolTT,
        "norm_freq": norm_freq,
        "table_log": table_log,
        "table_size": 1 << table_log,
    }


########################################
# Shared Test Data for Parameterization
########################################

# Test frequencies for comprehensive coverage
TEST_FREQUENCIES = [
    # (freq_dict, table_log, description)
    ({"A": 3, "B": 3, "C": 2}, 4, "balanced_3symbols"),
    ({"A": 1, "B": 1, "C": 2}, 4, "skewed_3symbols"),
    ({"A": 8, "B": 8}, 4, "uniform_2symbols"),
    ({"A": 1, "B": 3}, 4, "highly_skewed"),
    ({"A": 5, "B": 5, "C": 5, "D": 5}, 5, "uniform_4symbols"),
    ({"A": 10, "B": 20, "C": 30, "D": 40}, 6, "increasing_freqs"),
    ({"A": 1, "B": 1, "C": 1, "D": 1, "E": 1}, 4, "uniform_5symbols"),
    ({"A": 100, "B": 1}, 4, "very_skewed"),
    ({"A": 1}, 4, "single_symbol"),
]

# Table sizes to test
TEST_TABLE_LOGS = [4, 5, 6, 8, 12]
