from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from torii_sumo.core.tum_style_closed_loop import (
    begin_tum_style_iteration,
    complete_tum_style_iteration,
    next_tum_style_action,
    rollback_tum_style_iteration,
    start_tum_style_closed_loop,
)


def sumo_tum_style_closed_loop(
    operation: Literal["start", "begin", "complete", "next", "rollback"],
    state_file: str | None = None,
    baseline_net_file: str | None = None,
    output_dir: str | None = None,
    source_net_file: str | None = None,
    iteration_id: str | None = None,
    after_net_file: str | None = None,
    action: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
    mcp_evidence: dict[str, Any] | None = None,
    decision: Literal["accepted", "rejected", "review_required"] | None = None,
) -> dict[str, Any]:
    """Advance one hash-bound TUM-style NetEdit/MCP correction loop."""
    if operation == "start":
        if not baseline_net_file or not output_dir:
            raise ValueError("start requires baseline_net_file and output_dir")
        return start_tum_style_closed_loop(
            baseline_net_file=Path(baseline_net_file),
            output_dir=Path(output_dir),
            source_net_file=Path(source_net_file) if source_net_file else None,
        )
    if not state_file:
        raise ValueError(f"{operation} requires state_file")
    state_path = Path(state_file)
    if operation == "begin":
        return begin_tum_style_iteration(state_file=state_path)
    if operation == "complete":
        if not iteration_id or not after_net_file or not action or not decision:
            raise ValueError("complete requires iteration_id, after_net_file, action, and decision")
        return complete_tum_style_iteration(
            state_file=state_path,
            iteration_id=iteration_id,
            after_net_file=Path(after_net_file),
            action=action,
            audit=audit or {},
            mcp_evidence=mcp_evidence or {},
            decision=decision,
        )
    if operation == "next":
        return next_tum_style_action(state_file=state_path, audit=audit)
    if operation == "rollback":
        if not iteration_id:
            raise ValueError("rollback requires iteration_id")
        return rollback_tum_style_iteration(state_file=state_path, iteration_id=iteration_id)
    raise ValueError(f"unsupported closed-loop operation: {operation}")
