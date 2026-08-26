"""Contract tests for the ``junction_rebuild_tail`` compatibility extraction."""

from __future__ import annotations

import inspect
import xml.etree.ElementTree as ET

from torii_sumo.core import junction_rebuild_candidate as candidate_module
from torii_sumo.core import junction_rebuild_tail as tail_module


def _defined_functions(module: object) -> list[str]:
    """Function names whose definitions live in ``module`` (not re-imports)."""
    return [
        name
        for name, value in inspect.getmembers(module, inspect.isfunction)
        if getattr(value, "__module__", None) == module.__name__
    ]


def test_original_module_reexports_every_tail_function() -> None:
    tail_functions = _defined_functions(tail_module)
    missing = [name for name in tail_functions if not hasattr(candidate_module, name)]
    assert missing == [], missing

    mismatched = [
        name
        for name in tail_functions
        if getattr(candidate_module, name) is not getattr(tail_module, name)
    ]
    assert mismatched == [], mismatched


def test_tail_leaf_helpers_keep_behavior() -> None:
    assert tail_module._split("  a   b ") == ["a", "b"]
    assert tail_module._format_xy(1.0) == "1.00"
    assert tail_module._approaches(
        {"approaches": {"in": [{"edge_id": "e1"}, 1]}},
        "in",
    ) == [{"edge_id": "e1"}]

    connection = ET.Element(
        "connection",
        {"from": "a", "to": "b", "fromLane": "1", "toLane": "2"},
    )
    assert tail_module._connection_key(connection) == ("a", "b", "1", "2")
    assert tail_module._connection_key_record(("a", "b", "1", "2")) == {
        "from": "a",
        "to": "b",
        "fromLane": "1",
        "toLane": "2",
    }
    assert tail_module._controlled_link_signature_group(["s", "s", "t"]) == "2x s || 1x t"
    assert tail_module._failure("boom") == {
        "status": "fail",
        "claim_status": "construction-invalid",
        "error": "boom",
    }


def test_third_slice_shape_helpers_keep_behavior() -> None:
    # the module attribute resolves to the last definition, as in the baseline
    assert tail_module._shape_points("0,0 1,1") == [(0.0, 0.0), (1.0, 1.0)]
    assert tail_module._shape_endpoints("0,0 1,1 2,2") == ((0.0, 0.0), (2.0, 2.0))
    assert tail_module._shape_endpoints("") is None
    assert tail_module._join_shape_text("0,0 1,1", "1,1 2,2") == "0,0 1,1 2,2"
    assert tail_module._join_shape_text("0,0 1,1", "") == "0,0 1,1"
    # the moved duplicate keeps the baseline shadowing semantics in the facade
    assert candidate_module._shape_points is tail_module._shape_points
