"""Contract tests for the ``osm_workflow_tail`` compatibility extraction."""

from __future__ import annotations

import inspect

from torii_sumo.core import osm_workflow as facade
from torii_sumo.core import osm_workflow_tail as tail_module


def _defined_functions(module: object) -> list[str]:
    """Function names whose definitions live in ``module`` (not re-imports)."""
    return [
        name
        for name, value in inspect.getmembers(module, inspect.isfunction)
        if getattr(value, "__module__", None) == module.__name__
    ]


def test_facade_reexports_every_tail_function() -> None:
    tail_functions = _defined_functions(tail_module)
    missing = [name for name in tail_functions if not hasattr(facade, name)]
    assert missing == [], missing

    mismatched = [
        name
        for name in tail_functions
        if getattr(facade, name) is not getattr(tail_module, name)
    ]
    assert mismatched == [], mismatched


def test_facade_keeps_monkeypatch_pinned_functions_local() -> None:
    # tests monkeypatch these through the facade namespace, so the definitions
    # must resolve their callees via facade globals, not tail globals
    assert not hasattr(tail_module, "_run_direct_local_teacher_replay")
    assert not hasattr(tail_module, "run_scoped_teacher_tls_cell_batch")
    replay = getattr(facade, "_run_direct_local_teacher_replay")
    batch = getattr(facade, "run_scoped_teacher_tls_cell_batch")
    assert replay.__module__ == facade.__name__
    assert batch.__module__ == facade.__name__


def test_representative_tail_helpers_keep_behavior() -> None:
    assert tail_module._reference_scope_gate(None) == "skipped"
    assert tail_module._reference_scope_gate({"status": "pass"}) == "pass"
    assert tail_module._reference_scope_gate({"status": "blocked"}) == "blocked"
    assert tail_module._teacher_guided_queue_has_replay_candidates(None) is False
    assert tail_module._teacher_guided_queue_has_replay_candidates(
        {"ready_candidate_count": 2}
    ) is True
    assert tail_module._teacher_guided_queue_has_replay_candidates(
        {"expanded_scope_candidate_count": 1}
    ) is True
    assert tail_module._teacher_guided_queue_has_replay_candidates({}) is False
    assert tail_module._tls_semantic_delta_score(None) == 0
    assert tail_module._tls_semantic_delta_score(
        {"network_structural_missing_counts": {"tls_controlled_connection_count": 3}}
    ) == 3
    assert tail_module._movement_rebuild_mismatch_score(None) == 0
    assert tail_module._movement_rebuild_mismatch_score(
        {"junction_pattern_mismatch_count": 4}
    ) == 4
