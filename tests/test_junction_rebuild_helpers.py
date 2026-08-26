"""Contract tests for the ``junction_rebuild_helpers`` compatibility extraction."""

from __future__ import annotations

import inspect

from torii_sumo.core import junction_rebuild_candidate as candidate_module
from torii_sumo.core import junction_rebuild_helpers as helpers_module


def test_original_module_reexports_every_helper_function() -> None:
    helper_functions = [name for name, value in inspect.getmembers(helpers_module, inspect.isfunction)]
    missing = [name for name in helper_functions if not hasattr(candidate_module, name)]
    assert missing == [], missing

    mismatched = [
        name
        for name in helper_functions
        if getattr(candidate_module, name) is not getattr(helpers_module, name)
    ]
    assert mismatched == [], mismatched


def test_representative_leaf_helpers_keep_behavior() -> None:
    assert helpers_module._stable_digest("abc") == helpers_module._stable_digest("abc")
    assert helpers_module._edge_family_id("edgeA_1") == "edgeA_1"
    assert helpers_module._signed_edge_family_id("-edgeA_1") == "-edgeA_1"
    assert helpers_module._opposite_direction_edge_id("-edgeA_1") == "edgeA_1"
    assert helpers_module._int_count("3") == 3
    assert helpers_module._convex_hull([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]) == [
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
    ]
