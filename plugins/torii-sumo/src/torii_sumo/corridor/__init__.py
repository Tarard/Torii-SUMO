"""Typed contracts for the Torii corridor human-modeling research pipeline."""

from .benchmark import BenchmarkLock, BenchmarkSpecV1
from .audit_pipeline import build_exact_semantic_regression_artifacts
from .calibration import (
    ConnectionAuditCalibration,
    ConnectionAuditCalibrationPolicy,
    build_connection_mode_calibration_artifact,
    calibrate_connection_mode_audit,
)
from .canonicalizer import CanonicalEntity, CanonicalNetworkSnapshot, canonicalize_net_xml_file
from .conflict_graph import (
    IndependentSafetyReport,
    MovementConflictGraph,
    audit_independent_movement_safety,
    build_movement_conflict_graph,
)
from .candidates import CandidateGraph, CandidateVariant, Hypothesis, PatchOperation, SemanticDelta
from .enums import AutomationAction, GateStatus, TrafficSide, WorkflowStage
from .exact_diff import ExactSemanticDiffReport, build_finding, compare_canonical_snapshots
from .ids import (
    canonical_json_bytes,
    make_approach_id,
    make_boundary_port_id,
    make_controller_program_signature,
    make_internal_path_signature,
    make_lane_role_id,
    make_movement_id,
    make_physical_cell_id,
    make_signal_group_id,
    stable_id,
)
from .manifest import ArtifactManifestV1, CorridorResearchBundle
from .scope import BoundaryPort, ScopeSpec
from .synthetic_benchmark_contracts import (
    SyntheticFaultBenchmarkReport,
    SyntheticFaultBenchmarkSpec,
)
from .synthetic_benchmark_runner import run_synthetic_fault_benchmark
from .toolchain import ToolIdentity, ToolchainLock
from .workflow import NetworkQualityVectorV1, StageOutcome, WorkflowExecution

__all__ = [
    "ArtifactManifestV1",
    "AutomationAction",
    "BenchmarkLock",
    "BenchmarkSpecV1",
    "BoundaryPort",
    "CandidateGraph",
    "CandidateVariant",
    "CanonicalEntity",
    "CanonicalNetworkSnapshot",
    "ConnectionAuditCalibration",
    "ConnectionAuditCalibrationPolicy",
    "CorridorResearchBundle",
    "GateStatus",
    "Hypothesis",
    "IndependentSafetyReport",
    "NetworkQualityVectorV1",
    "MovementConflictGraph",
    "PatchOperation",
    "ScopeSpec",
    "SemanticDelta",
    "StageOutcome",
    "SyntheticFaultBenchmarkReport",
    "SyntheticFaultBenchmarkSpec",
    "ToolIdentity",
    "ToolchainLock",
    "TrafficSide",
    "WorkflowExecution",
    "WorkflowStage",
    "ExactSemanticDiffReport",
    "build_finding",
    "build_exact_semantic_regression_artifacts",
    "build_connection_mode_calibration_artifact",
    "calibrate_connection_mode_audit",
    "audit_independent_movement_safety",
    "build_movement_conflict_graph",
    "canonicalize_net_xml_file",
    "canonical_json_bytes",
    "make_approach_id",
    "make_boundary_port_id",
    "make_controller_program_signature",
    "make_internal_path_signature",
    "make_lane_role_id",
    "make_movement_id",
    "make_physical_cell_id",
    "make_signal_group_id",
    "compare_canonical_snapshots",
    "run_synthetic_fault_benchmark",
    "stable_id",
]
