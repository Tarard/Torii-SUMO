from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from torii_sumo.core.artifact_io import write_json_atomic
from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.core.connection_mode_audit import audit_network_connection_mode

from .audit_adapter import (
    build_scope_from_junction_ids,
    canonicalize_connection_mode_findings,
)
from .canonicalizer import canonicalize_net_xml_file
from .conflict_graph import audit_independent_movement_safety
from .enums import FindingSeverity, GateStatus
from .exact_diff import compare_canonical_snapshots
from .synthetic_benchmark_contracts import (
    GoldObservation,
    ObservationMatch,
    SyntheticFaultBenchmarkReport,
    SyntheticFaultBenchmarkSpec,
    SyntheticFaultCaseResult,
)
from .synthetic_networks import FIXTURES, apply_synthetic_mutation, build_synthetic_fixture


def run_synthetic_fault_benchmark(
    spec_file: Path,
    *,
    parent_benchmark_file: Path,
    output_dir: Path,
    prefix: str = "synthetic_fault_benchmark",
) -> dict[str, Any]:
    """Execute immutable gold fixtures against all declared fault mutations."""

    spec_path = spec_file.resolve()
    parent_path = parent_benchmark_file.resolve()
    destination = output_dir.resolve()
    spec = SyntheticFaultBenchmarkSpec.model_validate_json(
        spec_path.read_text(encoding="utf-8")
    )
    if file_sha256(parent_path) != spec.parent_benchmark_sha256:
        raise ValueError("Synthetic benchmark is not bound to this parent benchmark hash.")
    destination.mkdir(parents=True, exist_ok=True)
    fixture_dir = destination / "fixtures"
    case_dir = destination / "cases"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    case_dir.mkdir(parents=True, exist_ok=True)

    fixture_cache: dict[tuple[str, str], dict[str, Any]] = {}
    clean_fixture_statuses: dict[str, GateStatus] = {}
    global_blockers: list[str] = []
    results: list[SyntheticFaultCaseResult] = []
    artifact_paths: set[Path] = {spec_path, parent_path}

    for case in spec.cases:
        fixture_key = (case.fixture_id, case.traffic_side.value)
        fixture = fixture_cache.get(fixture_key)
        if fixture is None:
            fixture = _materialize_clean_fixture(
                fixture_id=case.fixture_id,
                traffic_side=case.traffic_side,
                fixture_dir=fixture_dir,
            )
            fixture_cache[fixture_key] = fixture
            clean_key = f"{case.fixture_id}:{case.traffic_side.value}"
            clean_fixture_statuses[clean_key] = fixture["status"]
            expected = FIXTURES[case.fixture_id].expected_clean_status
            if fixture["status"] is not expected:
                global_blockers.append(
                    f"clean_fixture_status_mismatch:{clean_key}:"
                    f"expected_{expected.value}:observed_{fixture['status'].value}"
                )
            artifact_paths.update(fixture["artifact_paths"])

        result, case_artifacts = _run_case(
            case=case,
            clean_fixture=fixture,
            case_dir=case_dir,
        )
        results.append(result)
        artifact_paths.update(case_artifacts)

    passed = sum(result.status is GateStatus.PASS for result in results)
    failed = len(results) - passed
    must_detect = [
        result for result in results if result.certification_expectation == "must-detect"
    ]
    must_abstain = [
        result for result in results if result.certification_expectation == "must-abstain"
    ]
    if failed:
        global_blockers.append(f"benchmark_case_failures:{failed}")
    report = SyntheticFaultBenchmarkReport(
        benchmark_id=spec.benchmark_id,
        benchmark_spec_sha256=file_sha256(spec_path),
        status=GateStatus.FAIL if global_blockers else GateStatus.PASS,
        total_case_count=len(results),
        passed_case_count=passed,
        failed_case_count=failed,
        must_detect_case_count=len(must_detect),
        must_detect_passed_count=sum(
            result.status is GateStatus.PASS for result in must_detect
        ),
        must_abstain_case_count=len(must_abstain),
        must_abstain_passed_count=sum(
            result.status is GateStatus.PASS for result in must_abstain
        ),
        clean_fixture_statuses=clean_fixture_statuses,
        cases=tuple(results),
        blockers=tuple(dict.fromkeys(global_blockers)),
    )
    report_path = destination / f"{prefix}.report.json"
    write_json_atomic(
        report_path,
        report.model_dump(mode="json", by_alias=True),
        sort_keys=True,
    )
    artifact_paths.add(report_path)
    manifest_path = destination / f"{prefix}.manifest.json"
    manifest = {
        "schema": "torii.corridor.synthetic-fault-benchmark-manifest/v1",
        "benchmark_id": spec.benchmark_id,
        "benchmark_spec": {
            "path": str(spec_path),
            "sha256": file_sha256(spec_path),
        },
        "parent_benchmark": {
            "path": str(parent_path),
            "sha256": file_sha256(parent_path),
        },
        "source_fixtures_immutable": all(
            result.source_immutable for result in results
        ),
        "status": report.status.value,
        "artifacts": [
            {
                "path": str(path),
                "sha256": file_sha256(path),
            }
            for path in sorted(artifact_paths, key=lambda item: item.as_posix())
        ],
    }
    write_json_atomic(manifest_path, manifest, sort_keys=True)
    return {
        **report.model_dump(mode="json", by_alias=True),
        "report_file": str(report_path),
        "manifest_file": str(manifest_path),
    }


def _materialize_clean_fixture(
    *,
    fixture_id: str,
    traffic_side: Any,
    fixture_dir: Path,
) -> dict[str, Any]:
    root = build_synthetic_fixture(fixture_id, traffic_side=traffic_side)
    path = fixture_dir / f"{fixture_id}.{traffic_side.value}.clean.net.xml"
    _write_xml(path, root)
    source_sha256 = file_sha256(path)
    audit = audit_network_connection_mode(
        ET.parse(path).getroot(),
        traffic_side=traffic_side.value,
        endpoint_tolerance_m=0.01,
    )
    snapshot = canonicalize_net_xml_file(path, traffic_side=traffic_side)
    safety = audit_independent_movement_safety(snapshot)
    connection_path = fixture_dir / f"{fixture_id}.{traffic_side.value}.connection-mode.json"
    safety_path = fixture_dir / f"{fixture_id}.{traffic_side.value}.independent-safety.json"
    write_json_atomic(connection_path, audit, sort_keys=True)
    write_json_atomic(
        safety_path,
        safety.model_dump(mode="json", by_alias=True),
        sort_keys=True,
    )
    return {
        "path": path,
        "sha256": source_sha256,
        "audit": audit,
        "snapshot": snapshot,
        "safety": safety,
        "status": _combined_status(audit, safety.status),
        "artifact_paths": {path, connection_path, safety_path},
    }


def _run_case(
    *,
    case: Any,
    clean_fixture: dict[str, Any],
    case_dir: Path,
) -> tuple[SyntheticFaultCaseResult, set[Path]]:
    source_path: Path = clean_fixture["path"]
    source_sha256 = clean_fixture["sha256"]
    source_root = ET.parse(source_path).getroot()
    mutant_root = apply_synthetic_mutation(source_root, case.mutation_id)
    mutant_path = case_dir / f"{case.case_id}.mutant.net.xml"
    _write_xml(mutant_path, mutant_root)
    mutant_sha256 = file_sha256(mutant_path)
    candidate_audit = audit_network_connection_mode(
        ET.parse(mutant_path).getroot(),
        traffic_side=case.traffic_side.value,
        endpoint_tolerance_m=0.01,
    )
    candidate_snapshot = canonicalize_net_xml_file(
        mutant_path,
        traffic_side=case.traffic_side,
    )
    candidate_safety = audit_independent_movement_safety(candidate_snapshot)
    source_snapshot = clean_fixture["snapshot"]
    source_audit = clean_fixture["audit"]
    source_safety = clean_fixture["safety"]
    scope = build_scope_from_junction_ids(
        source_snapshot,
        candidate_snapshot,
        target_source_junction_ids=("J0",),
        target_candidate_junction_ids=("J0",),
    )
    source_connection_findings = canonicalize_connection_mode_findings(
        source_audit,
        source_snapshot,
    )
    candidate_connection_findings = canonicalize_connection_mode_findings(
        candidate_audit,
        candidate_snapshot,
    )
    exact_diff = compare_canonical_snapshots(
        source_snapshot,
        candidate_snapshot,
        scope=scope,
        source_findings=(*source_connection_findings, *source_safety.findings),
        candidate_findings=(
            *candidate_connection_findings,
            *candidate_safety.findings,
        ),
    )
    observed = _observations(
        connection_findings=candidate_connection_findings,
        safety_findings=candidate_safety.findings,
        exact_diff=exact_diff,
    )
    matches = tuple(
        _match_observation(expectation, observed)
        for expectation in case.expected_observations
    )
    source_immutable = file_sha256(source_path) == source_sha256
    exact_delta_count = len(exact_diff.entity_deltas)
    abstention_proven = bool(
        candidate_audit.get("automatic_promotion_gate") == "blocked"
        or candidate_safety.automatic_promotion_gate is GateStatus.BLOCKED
        or exact_delta_count
    )
    blockers: list[str] = []
    if not source_immutable:
        blockers.append("source_fixture_mutated")
    if source_sha256 == mutant_sha256:
        blockers.append("mutation_did_not_change_fixture")
    for match in matches:
        if not match.matched:
            blockers.append(
                f"gold_observation_missing:{match.channel}:{match.value}:"
                f"{match.observed_count}/{match.expected_minimum_count}"
            )
    if not abstention_proven:
        blockers.append("fault_not_blocked_or_exposed_as_exact_delta")
    status = GateStatus.FAIL if blockers else GateStatus.PASS
    connection_path = case_dir / f"{case.case_id}.connection-mode.json"
    safety_path = case_dir / f"{case.case_id}.independent-safety.json"
    diff_path = case_dir / f"{case.case_id}.exact-diff.json"
    result_path = case_dir / f"{case.case_id}.result.json"
    write_json_atomic(connection_path, candidate_audit, sort_keys=True)
    write_json_atomic(
        safety_path,
        candidate_safety.model_dump(mode="json", by_alias=True),
        sort_keys=True,
    )
    write_json_atomic(
        diff_path,
        exact_diff.model_dump(mode="json", by_alias=True),
        sort_keys=True,
    )
    result = SyntheticFaultCaseResult(
        case_id=case.case_id,
        fault_family=case.fault_family,
        certification_expectation=case.certification_expectation,
        status=status,
        source_sha256=source_sha256,
        mutant_sha256=mutant_sha256,
        source_immutable=source_immutable,
        connection_status=str(candidate_audit.get("status", "unknown")),
        independent_safety_status=candidate_safety.status,
        exact_delta_count=exact_delta_count,
        observation_matches=matches,
        observed=observed,
        abstention_proven=abstention_proven,
        blockers=tuple(blockers),
        source_net_path=str(source_path),
        mutant_net_path=str(mutant_path),
    )
    write_json_atomic(
        result_path,
        result.model_dump(mode="json", by_alias=True),
        sort_keys=True,
    )
    return result, {mutant_path, connection_path, safety_path, diff_path, result_path}


def _observations(
    *,
    connection_findings: tuple[Any, ...],
    safety_findings: tuple[Any, ...],
    exact_diff: Any,
) -> dict[str, dict[str, int]]:
    channels: dict[str, Counter[str]] = {
        "connection-structural": Counter(),
        "connection-review": Counter(),
        "independent-safety": Counter(),
        "independent-review": Counter(),
        "exact-delta": Counter(),
    }
    for finding in connection_findings:
        channel = (
            "connection-structural"
            if finding.severity is FindingSeverity.STRUCTURAL
            else "connection-review"
        )
        channels[channel][finding.category] += 1
    for finding in safety_findings:
        channel = (
            "independent-safety"
            if finding.severity is FindingSeverity.SAFETY
            else "independent-review"
        )
        channels[channel][finding.category] += 1
    for delta in exact_diff.entity_deltas:
        channels["exact-delta"][f"{delta.entity_kind}:{delta.action.value}"] += 1
    return {
        channel: dict(sorted(counts.items()))
        for channel, counts in channels.items()
    }


def _match_observation(
    expectation: GoldObservation,
    observed: dict[str, dict[str, int]],
) -> ObservationMatch:
    count = observed.get(expectation.channel, {}).get(expectation.value, 0)
    return ObservationMatch(
        channel=expectation.channel,
        value=expectation.value,
        expected_minimum_count=expectation.minimum_count,
        observed_count=count,
        matched=count >= expectation.minimum_count,
    )


def _combined_status(audit: dict[str, Any], safety_status: GateStatus) -> GateStatus:
    connection_status = str(audit.get("status", "fail"))
    if connection_status == "fail" or safety_status in {GateStatus.FAIL, GateStatus.BLOCKED}:
        return GateStatus.BLOCKED
    if connection_status == "review_required" or safety_status is GateStatus.REVIEW:
        return GateStatus.REVIEW
    return GateStatus.PASS


def _write_xml(path: Path, root: ET.Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = deepcopy(root)
    ET.indent(serializable, space="    ")
    ET.ElementTree(serializable).write(path, encoding="utf-8", xml_declaration=True)
