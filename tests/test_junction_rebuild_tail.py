"""Contract tests for the ``junction_rebuild_tail`` compatibility extraction."""

from __future__ import annotations

import inspect
import xml.etree.ElementTree as ET

from torii_sumo.core import junction_rebuild_candidate as candidate_module
from torii_sumo.core import junction_rebuild_tail as tail_module


def test_original_module_reexports_every_tail_function() -> None:
    tail_functions = [name for name, value in inspect.getmembers(tail_module, inspect.isfunction)]
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
