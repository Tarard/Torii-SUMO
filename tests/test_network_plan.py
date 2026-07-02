from pathlib import Path
import xml.etree.ElementTree as ET

from torii_sumo.core.network_permissions import apply_service_passenger_permissions
from torii_sumo.core.network_plan import derive_network_plan
from torii_sumo.core.osm_workflow import (
    _junction_semantic_gate,
    _low_vehicle_control_candidate_limits,
    _movement_rebuild_reference_delta_promotion_decision,
    _reference_delta_promotion_decision,
    _followup_reference_delta_structural_only,
    _teacher_guided_seed_candidate,
    _reference_join_audit_can_seed_teacher_guided_queue,
    _restore_followup_internal_regressions,
    _sumo_load_net,
    _filter_teacher_guided_queue_to_mismatch_fields,
    _teacher_guided_junction_parity_gate,
    _teacher_guided_application_stats,
    _teacher_guided_best_variant_file,
    _teacher_guided_direct_replay_needed,
    _teacher_guided_equivalent_approach_edge_map,
    _safe_path_part,
    _tls_connection_repair_promotion_decision,
    export_plain_net_for_teacher_guided_repair,
    run_osm_cleanup_workflow,
)
from torii_sumo.core.reference_bbox import derive_reference_net_bbox


def test_junction_semantic_gate_uses_comparison_evidence_when_case_counts_are_zero() -> None:
    report = {
        "status": "pass",
        "matched_case_count": 0,
        "junction_pattern_mismatch_count": 0,
        "junction_pattern_mismatch_field_counts": {},
        "junction_pattern_comparisons": [{"junction_id": "89129103", "status": "pass", "mismatch_fields": []}],
    }

    assert _junction_semantic_gate(report, {"movement_signature_counts"}) == "pass"


def test_followup_reference_delta_inherits_structural_only_baseline() -> None:
    assert _followup_reference_delta_structural_only({"audit_mode": "structural_only"}, default=False) is True
    assert _followup_reference_delta_structural_only({"audit_mode": "full"}, default=False) is False
    assert _followup_reference_delta_structural_only({"audit_mode": "full"}, default=True) is True


def test_direct_replay_path_part_is_short_and_stable_for_windows() -> None:
    long_junction_id = "cluster_267395411_270697844_915689881_915690365"

    path_part = _safe_path_part(long_junction_id)

    assert len(path_part) <= 16
    assert path_part == _safe_path_part(long_junction_id)
    assert path_part != _safe_path_part(long_junction_id + "_different")


def test_sumo_load_retries_netconvert_normalized_net_after_direct_failure(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sumo_binary = bin_dir / "sumo.exe"
    netconvert_binary = bin_dir / "netconvert.exe"
    sumo_binary.write_text("", encoding="utf-8")
    netconvert_binary.write_text("", encoding="utf-8")
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    calls = []

    def command_runner(command, *, cwd, timeout_seconds):
        calls.append(command)
        if Path(command[0]).name == "netconvert.exe":
            output_file = Path(cwd) / command[command.index("--output-file") + 1]
            output_file.write_text("<net/>", encoding="utf-8")
            return {"returncode": 0, "stdout": "", "stderr": ""}
        sumo_call_count = sum(1 for call in calls if Path(call[0]).name == "sumo.exe")
        if sumo_call_count == 1:
            return {"returncode": 1, "stdout": "", "stderr": "direct load failed"}
        return {"returncode": 0, "stdout": "", "stderr": ""}

    report = _sumo_load_net(
        net_file,
        output_dir=tmp_path / "sumo_load",
        sumo_binary=str(sumo_binary),
        timeout_seconds=10,
        command_runner=command_runner,
    )

    assert report["status"] == "pass"
    assert [Path(call[0]).name for call in calls] == ["sumo.exe", "netconvert.exe", "sumo.exe"]
    assert report["direct_sumo_load"]["status"] == "fail"
    assert report["normalization_netconvert"]["status"] == "pass"
    assert report["load_net_file"].endswith("sumo_load_candidate_normalized.net.xml")


def test_teacher_guided_junction_parity_gate_uses_final_semantic_parity() -> None:
    final_semantic_report = {
        "status": "pass",
        "matched_case_count": 1,
        "junction_pattern_mismatch_count": 0,
        "junction_pattern_mismatch_field_counts": {},
        "junction_pattern_comparisons": [{"junction_id": "267517510", "status": "pass", "mismatch_fields": []}],
    }
    early_teacher_run = {
        "status": "fail",
        "parity_gate_status": "fail",
        "repair_candidate_count": 132,
    }

    assert _teacher_guided_junction_parity_gate(early_teacher_run, final_semantic_report) == "pass"


def test_restore_followup_internal_regressions_restores_only_new_internal_failures(tmp_path: Path) -> None:
    baseline_net = tmp_path / "baseline.net.xml"
    baseline_net.write_text(
        """<net>
    <edge id="in" from="a" to="j"><lane id="in_0" index="0" shape="0,0 10,0"/></edge>
    <edge id="out" from="j" to="b"><lane id="out_0" index="0" shape="10,0 20,0"/></edge>
    <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="10,0 11,0"/></edge>
    <junction id="j" type="priority" x="10" y="0" incLanes="in_0" intLanes=":j_0_0"/>
    <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" dir="s"/>
    <connection from=":j_0" to="out" fromLane="0" toLane="0" dir="s"/>
</net>""",
        encoding="utf-8",
    )
    followup_net = tmp_path / "followup.net.xml"
    followup_net.write_text(
        """<net>
    <edge id="in" from="a" to="j"><lane id="in_0" index="0" shape="0,0 10,0"/></edge>
    <edge id="out" from="j" to="b"><lane id="out_0" index="0" shape="10,0 20,0"/></edge>
    <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0" shape="10,0 11,0"/></edge>
    <edge id=":j_1" function="internal"><lane id=":j_1_0" index="0" shape="11,0 12,0"/></edge>
    <junction id="j" type="priority" x="10" y="0" incLanes="in_0" intLanes=":j_1_0"/>
    <connection from="in" to="out" fromLane="0" toLane="0" via=":j_0_0" dir="s"/>
    <connection from=":j_0" to="out" fromLane="0" toLane="0" via=":j_1_0" dir="s"/>
</net>""",
        encoding="utf-8",
    )

    report = _restore_followup_internal_regressions(
        baseline_delta_report={"junction_pattern_comparisons": []},
        followup_delta_report={
            "junction_pattern_comparisons": [
                {"junction_id": "j", "mismatch_fields": ["internal_function_counts"]},
                {"junction_id": "k", "mismatch_fields": ["approach_edge_ids"]},
            ]
        },
        baseline_net_file=baseline_net,
        followup_net_file=followup_net,
        output_dir=tmp_path / "restore",
        prefix="probe",
    )

    root = ET.parse(report["restored_net_file"]).getroot()
    assert report["status"] == "pass"
    assert report["restored_junction_ids"] == ["j"]
    assert root.find("edge[@id=':j_1']") is None
    assert root.find("junction[@id='j']").attrib["intLanes"] == ":j_0_0"


def _write_reference_net(path: Path) -> None:
    path.write_text(
        """<net>
    <edge id="primary_a" type="highway.primary">
        <lane id="primary_a_0" index="0" allow="passenger bus" speed="13.9" length="25.0"/>
    </edge>
    <edge id="residential_a" type="highway.residential">
        <lane id="residential_a_0" index="0" speed="13.9" length="25.0"/>
    </edge>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="delivery passenger pedestrian" speed="5.0" length="25.0"/>
    </edge>
    <edge id="service_b" type="highway.service">
        <lane id="service_b_0" index="0" allow="delivery passenger" speed="5.0" length="25.0"/>
    </edge>
    <edge id="cycle_a" type="highway.cycleway">
        <lane id="cycle_a_0" index="0" allow="bicycle" speed="5.0" length="25.0"/>
    </edge>
    <edge id="foot_a" type="highway.footway">
        <lane id="foot_a_0" index="0" allow="pedestrian" speed="5.0" length="25.0"/>
    </edge>
    <edge id="path_rare" type="highway.path">
        <lane id="path_rare_0" index="0" allow="passenger pedestrian" speed="5.0" length="25.0"/>
    </edge>
</net>""",
        encoding="utf-8",
    )


def _write_osm_highways(path: Path, highways: list[str]) -> None:
    nodes = "\n".join(
        f'    <node id="{index}" lat="48.{index:06d}" lon="11.{index:06d}"/>'
        for index in range(1, len(highways) * 2 + 1)
    )
    ways = []
    for index, highway in enumerate(highways, start=1):
        start = index * 2 - 1
        end = index * 2
        ways.append(
            f"""    <way id="{1000 + index}">
        <nd ref="{start}"/>
        <nd ref="{end}"/>
        <tag k="highway" v="{highway}"/>
    </way>"""
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<osm>\n{nodes}\n{chr(10).join(ways)}\n</osm>", encoding="utf-8")


def test_teacher_guided_application_stats_reports_single_variant_scope(tmp_path: Path) -> None:
    best_net = tmp_path / "candidate_001_teacher_guided.net.xml"
    best_net.write_text("<net/>", encoding="utf-8")

    stats = _teacher_guided_application_stats(
        {
            "status": "pass",
            "parity_gate_status": "pass",
            "pass_candidate_count": 3,
        },
        best_net,
    )

    assert stats == {
        "teacher_guided_repair_application_scope": "single_best_variant",
        "teacher_guided_repair_applied_candidate_count": 1,
        "teacher_guided_repair_unapplied_pass_candidate_count": 2,
    }


def test_teacher_guided_application_stats_reports_sequential_composite_scope(tmp_path: Path) -> None:
    composite_net = tmp_path / "composite_teacher_guided.net.xml"
    composite_net.write_text("<net/>", encoding="utf-8")

    stats = _teacher_guided_application_stats(
        {
            "status": "pass",
            "parity_gate_status": "pass",
            "pass_candidate_count": 5,
            "composite_applied_candidate_count": 3,
            "composite_net_file": str(composite_net),
        },
        composite_net,
    )

    assert stats == {
        "teacher_guided_repair_application_scope": "sequential_composite",
        "teacher_guided_repair_applied_candidate_count": 3,
        "teacher_guided_repair_unapplied_pass_candidate_count": 2,
    }


def test_teacher_guided_best_variant_file_prefers_composite_net(tmp_path: Path) -> None:
    first_variant = tmp_path / "candidate_001_teacher_guided.net.xml"
    composite_net = tmp_path / "candidate_002_teacher_guided.net.xml"
    first_variant.write_text("<net/>", encoding="utf-8")
    composite_net.write_text("<net/>", encoding="utf-8")

    best = _teacher_guided_best_variant_file(
        {
            "status": "pass",
            "parity_gate_status": "pass",
            "composite_net_file": str(composite_net),
            "variant_reports": [
                {
                    "status": "pass",
                    "parity_gate_status": "pass",
                    "final_net_file": str(first_variant),
                }
            ],
        }
    )

    assert best == composite_net


def test_teacher_guided_best_variant_file_uses_partial_sequential_composite(tmp_path: Path) -> None:
    composite_net = tmp_path / "partial_composite_teacher_guided.net.xml"
    composite_net.write_text("<net/>", encoding="utf-8")

    best = _teacher_guided_best_variant_file(
        {
            "status": "fail",
            "parity_gate_status": "fail",
            "pass_candidate_count": 33,
            "parity_pass_candidate_count": 26,
            "composite_applied_candidate_count": 26,
            "composite_net_file": str(composite_net),
        }
    )

    assert best == composite_net


def test_teacher_guided_equivalent_approach_edge_map_collects_passed_replay_maps() -> None:
    edge_map = _teacher_guided_equivalent_approach_edge_map(
        {
            "variant_reports": [
                {
                    "status": "fail",
                    "parity_gate_status": "pass",
                    "target_internal_replay": {"effective_edge_map": {"ignored": "ignored_candidate"}},
                },
                {
                    "status": "pass",
                    "parity_gate_status": "pass",
                    "target_internal_replay": {"effective_edge_map": {"teacher_west": "candidate_west"}},
                },
            ]
        }
    )

    assert edge_map == {"teacher_west": "candidate_west"}


def test_filter_teacher_guided_queue_to_movement_mismatches(tmp_path: Path) -> None:
    queue_report = {
        "status": "pass",
        "queue_file": str(tmp_path / "all_queue.json"),
        "repair_candidate_count": 4,
        "ready_candidate_count": 2,
        "expanded_scope_candidate_count": 2,
        "blocked_candidate_count": 0,
        "repair_candidates": [
            {"reference_id": "cluster_keep", "candidate_status": "ready_for_teacher_guided_variant"},
            {"reference_id": "cluster_drop", "candidate_status": "ready_for_teacher_guided_variant"},
            {"junction_id": "cluster_approach", "candidate_status": "needs_expanded_rebuild_scope"},
            {
                "reference_id": "same_id_tls",
                "candidate_status": "needs_expanded_rebuild_scope",
                "learned_rule": "tum_like_same_id_tls_candidate",
            },
        ],
    }
    audit_report = {
        "junction_pattern_comparisons": [
            {"junction_id": "cluster_keep", "mismatch_fields": ["movement_signature_counts"]},
            {"junction_id": "cluster_drop", "mismatch_fields": ["approach_edge_ids"]},
            {"junction_id": "cluster_missing", "mismatch_fields": ["internal_function_counts"]},
        ]
    }

    filtered = _filter_teacher_guided_queue_to_mismatch_fields(
        queue_report,
        audit_report,
        {"movement_signature_counts", "internal_function_counts"},
        output_dir=tmp_path / "filtered",
        prefix="final_movement",
    )

    assert filtered["repair_candidate_count"] == 2
    assert filtered["ready_candidate_count"] == 1
    assert filtered["expanded_scope_candidate_count"] == 1
    assert filtered["queue_filter_target_junction_ids"] == ["cluster_keep", "cluster_missing"]
    assert filtered["queue_filter_original_repair_candidate_count"] == 4
    assert filtered["repair_candidates"] == [
        {"reference_id": "cluster_keep", "candidate_status": "ready_for_teacher_guided_variant"},
        {
            "reference_id": "same_id_tls",
            "candidate_status": "needs_expanded_rebuild_scope",
            "learned_rule": "tum_like_same_id_tls_candidate",
        },
    ]
    assert Path(str(filtered["queue_file"])).exists()


def test_filter_teacher_guided_queue_keeps_topology_fragmented_tls_candidate(tmp_path: Path) -> None:
    queue_report = {
        "status": "pass",
        "queue_file": str(tmp_path / "all_queue.json"),
        "repair_candidates": [
            {"reference_id": "cluster_keep", "candidate_status": "ready_for_teacher_guided_variant"},
            {
                "reference_id": "teacher_tls",
                "candidate_status": "needs_expanded_rebuild_scope",
                "learned_rule": "tum_like_topology_fragmented_tls_candidate",
            },
        ],
    }
    audit_report = {
        "junction_pattern_comparisons": [
            {"junction_id": "cluster_keep", "mismatch_fields": ["movement_signature_counts"]},
        ]
    }

    filtered = _filter_teacher_guided_queue_to_mismatch_fields(
        queue_report,
        audit_report,
        {"movement_signature_counts", "internal_function_counts"},
        output_dir=tmp_path / "filtered",
        prefix="final_movement",
    )

    assert [candidate["reference_id"] for candidate in filtered["repair_candidates"]] == [
        "cluster_keep",
        "teacher_tls",
    ]
    assert filtered["expanded_scope_candidate_count"] == 1


def test_full_reference_join_audit_without_movement_delta_does_not_seed_teacher_guided_queue() -> None:
    assert not _reference_join_audit_can_seed_teacher_guided_queue(
        {
            "audit_mode": "full",
            "matched_case_count": 132,
            "junction_pattern_mismatch_count": 0,
            "junction_pattern_mismatch_field_counts": {},
            "junction_pattern_comparisons": [],
        },
        structural_only=False,
    )
    assert _reference_join_audit_can_seed_teacher_guided_queue(
        {
            "audit_mode": "full",
            "junction_pattern_mismatch_count": 1,
            "junction_pattern_mismatch_field_counts": {"movement_signature_counts": 1},
        },
        structural_only=False,
    )


def test_teacher_guided_seed_candidate_uses_structural_delta_fallback() -> None:
    primary = {
        "audit_mode": "full",
        "junction_pattern_mismatch_count": 0,
        "junction_pattern_mismatch_field_counts": {},
        "junction_pattern_comparisons": [],
    }
    structural = {
        "audit_mode": "structural_only",
        "junction_pattern_comparisons": [{"junction_id": "1611608462", "status": "fail"}],
    }

    report, structural_only, requires_promotion, source = _teacher_guided_seed_candidate(
        primary,
        primary_structural_only=False,
        fallback_reports=[("reference_visual_detail_delta", structural)],
    )

    assert report is structural
    assert structural_only is True
    assert requires_promotion is True
    assert source == "reference_visual_detail_delta"


def test_teacher_guided_seed_candidate_keeps_primary_movement_delta() -> None:
    primary = {
        "audit_mode": "full",
        "junction_pattern_mismatch_count": 1,
        "junction_pattern_mismatch_field_counts": {"movement_signature_counts": 1},
    }
    structural = {
        "audit_mode": "structural_only",
        "junction_pattern_comparisons": [{"junction_id": "1611608462", "status": "fail"}],
    }

    report, structural_only, requires_promotion, source = _teacher_guided_seed_candidate(
        primary,
        primary_structural_only=False,
        fallback_reports=[("reference_visual_detail_delta", structural)],
    )

    assert report is primary
    assert structural_only is False
    assert requires_promotion is False
    assert source == "reference_join_audit"


def test_reference_matched_workflow_uses_teacher_guided_composite_for_review(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-composite_filtered.osm.xml.gz"
    composite_net = tmp_path / "teacher_guided_composite.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        calls.setdefault("reference_join_candidate_net_files", []).append(kwargs["candidate_net_file"])
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "full",
            "reference_case_count": 1,
            "matched_case_count": 1,
            "unmatched_case_count": 0,
            "junction_pattern_index": [{"junction_id": "cluster_a_b"}],
            "junction_pattern_mismatch_count": 1,
            "junction_pattern_mismatch_field_counts": {"movement_signature_counts": 1},
            "junction_pattern_comparisons": [
                {"junction_id": "cluster_a_b", "status": "fail", "mismatch_fields": ["movement_signature_counts"]}
            ],
            "summary_file": str(tmp_path / "reference_join_audit.json"),
            "warnings": [],
        }

    def fake_teacher_guided_queue(**kwargs):
        calls["teacher_guided_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "repair_candidate_count": 4,
            "ready_candidate_count": 0,
            "expanded_scope_candidate_count": 4,
            "queue_file": str(tmp_path / "teacher_guided_queue.json"),
            "repair_candidates": [
                {"reference_id": "cluster_a_b", "candidate_status": "needs_expanded_rebuild_scope"}
            ],
            "warnings": [],
        }

    def fake_teacher_guided_plain_export(**kwargs):
        calls["teacher_guided_plain_net_file"] = kwargs["net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "raw_node_file": str(tmp_path / "plain.nod.xml"),
            "raw_edge_file": str(tmp_path / "plain.edg.xml"),
            "raw_connection_file": str(tmp_path / "plain.con.xml"),
            "warnings": [],
        }

    def fake_teacher_guided_run(**kwargs):
        calls["teacher_guided_run_sequential_accept_passed_variants"] = kwargs["sequential_accept_passed_variants"]
        composite_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "parity_gate_status": "pass",
            "attempted_candidate_count": 4,
            "pass_candidate_count": 4,
            "composite_applied_candidate_count": 4,
            "composite_net_file": str(composite_net),
            "run_report_file": str(tmp_path / "teacher_guided_run.json"),
            "promotion_gate_status": "pass",
            "promotion_gate_file": str(tmp_path / "teacher_guided_promotion_gate.json"),
            "warnings": [],
        }

    def fake_review_html(**kwargs):
        calls["workflow_review_net_file"] = kwargs["net_file"]
        return {
            "status": "pass",
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "review.html"),
            "workflow_review_net_file": str(kwargs["net_file"]),
            "workflow_report_file": str(tmp_path / "workflow_report.json"),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-composite",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        run_tls_aggregation_after_build=False,
        run_routeability_audit_after_build=False,
        run_reference_join_aggregation_after_build=False,
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {"status": "pass", "tls_candidate_count": 0, "warnings": []},
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "passenger_edge_count": 1},
        topology_audit_func=lambda **_kwargs: {"status": "pass", "topology_fragmentation_status": "pass", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "skipped", "warnings": []},
        sumo_gui_func=lambda _path, **_kwargs: {"status": "blocked", "sumo_gui_status": "skipped", "warnings": []},
        reference_join_audit_func=fake_reference_join_audit,
        teacher_guided_repair_queue_func=fake_teacher_guided_queue,
        teacher_guided_plain_export_func=fake_teacher_guided_plain_export,
        teacher_guided_repair_run_func=fake_teacher_guided_run,
        review_html_func=fake_review_html,
    )

    assert calls["teacher_guided_run_sequential_accept_passed_variants"] is True
    assert calls["workflow_review_net_file"] == composite_net
    assert report["reference_visual_detail_comparison_net_file"] == str(composite_net)
    assert report["teacher_guided_repair_best_variant_file"] == str(composite_net)
    assert report["teacher_guided_repair_application_scope"] == "sequential_composite"
    assert report["teacher_guided_repair_applied_candidate_count"] == 4
    assert report["teacher_guided_repair_unapplied_pass_candidate_count"] == 0
    assert report["teacher_guided_repair_promotion_gate_status"] == "pass"
    assert report["teacher_guided_repair_promotion_gate_file"] == str(tmp_path / "teacher_guided_promotion_gate.json")
    assert calls["reference_join_candidate_net_files"][-1] == composite_net


def test_reference_matched_workflow_promotes_direct_teacher_replay_when_plain_replay_regresses(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-direct-replay_filtered.osm.xml.gz"
    visual_tls_net = tmp_path / "visual_tls_aggregation.net.xml"
    repaired_tls_net = tmp_path / "visual_tls_connection_repaired.net.xml"
    heavy_net = tmp_path / "heavy_teacher_replay.net.xml"
    direct_net_1 = tmp_path / "direct_teacher_replay_1.net.xml"
    direct_net_2 = tmp_path / "direct_teacher_replay_2.net.xml"
    calls: dict[str, object] = {
        "reference_join_candidate_net_files": [],
        "teacher_guided_plain_net_files": [],
        "direct_replay_source_net_files": [],
        "initial_direct_replay_candidate_ids": [],
    }

    def write_net(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<net/>", encoding="utf-8")
        return path

    def fake_build(**kwargs):
        net_file = write_net(tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml")
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def delta(
        *,
        connection_extra: int,
        extra_tls_junctions: int,
        missing_tls_controlled_connections: int,
        mismatch: int,
        summary: str,
    ) -> dict[str, object]:
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "structural_only",
            "summary_file": str(tmp_path / summary),
            "reference_case_count": 1,
            "matched_case_count": 1,
            "unmatched_case_count": 0,
            "junction_pattern_index": [{"junction_id": "j1"}, {"junction_id": "j2"}],
            "junction_pattern_mismatch_count": mismatch,
            "junction_pattern_mismatch_field_counts": (
                {"movement_signature_counts": mismatch} if mismatch else {}
            ),
            "junction_pattern_comparisons": [
                {"junction_id": "j1", "status": "fail", "mismatch_fields": ["movement_signature_counts"]},
                {"junction_id": "j2", "status": "fail", "mismatch_fields": ["movement_signature_counts"]},
            ]
            if mismatch
            else [],
            "network_structural_missing_counts": {
                "crossing_edge_count": 145,
                "tls_controlled_connection_count": missing_tls_controlled_connections,
            },
            "network_structural_extra_counts": {
                "connection_count": connection_extra,
                "traffic_light_junction_count": extra_tls_junctions,
            },
            "tls_control_review_queue": [],
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        candidate = kwargs["candidate_net_file"]
        output_dir = str(kwargs["output_dir"])
        calls["reference_join_candidate_net_files"].append(candidate)
        if "reference_visual_detail_raw_reference_delta" in output_dir:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "summary_file": str(tmp_path / "raw_visual_delta.json"),
                "reference_case_count": 0,
                "matched_case_count": 0,
                "unmatched_case_count": 0,
                "junction_pattern_mismatch_count": 0,
                "junction_pattern_comparisons": [],
                "network_structural_missing_counts": {"tls_controlled_connection_count": 10},
                "network_structural_extra_counts": {"traffic_light_junction_count": 5},
                "warnings": [],
            }
        if candidate == visual_tls_net:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "summary_file": str(tmp_path / "visual_tls_delta.json"),
                "reference_case_count": 0,
                "matched_case_count": 0,
                "unmatched_case_count": 0,
                "junction_pattern_mismatch_count": 0,
                "junction_pattern_comparisons": [],
                "network_structural_missing_counts": {"tls_controlled_connection_count": 337},
                "network_structural_extra_counts": {"tl_logic_count": 12, "traffic_light_junction_count": 41},
                "warnings": [],
            }
        if candidate == repaired_tls_net and "reference_visual_detail_tls_connection_repair_reference_delta" in output_dir:
            return delta(
                connection_extra=1812,
                extra_tls_junctions=16,
                missing_tls_controlled_connections=50,
                mismatch=30,
                summary="repaired_tls_seed_delta.json",
            )
        if candidate == repaired_tls_net:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "summary_file": str(tmp_path / "primary_reference_join_delta.json"),
                "reference_case_count": 0,
                "matched_case_count": 0,
                "unmatched_case_count": 0,
                "junction_pattern_mismatch_count": 0,
                "junction_pattern_comparisons": [],
                "network_structural_missing_counts": {},
                "network_structural_extra_counts": {},
                "warnings": [],
            }
        if candidate == heavy_net:
            return delta(
                connection_extra=4100,
                extra_tls_junctions=30,
                missing_tls_controlled_connections=90,
                mismatch=28,
                summary="heavy_delta.json",
            )
        if candidate == direct_net_1:
            return delta(
                connection_extra=1900,
                extra_tls_junctions=20,
                missing_tls_controlled_connections=90,
                mismatch=31,
                summary="direct_delta_1.json",
            )
        if candidate == direct_net_2:
            return delta(
                connection_extra=1651,
                extra_tls_junctions=14,
                missing_tls_controlled_connections=80,
                mismatch=27,
                summary="direct_delta_2.json",
            )
        return delta(
            connection_extra=1812,
            extra_tls_junctions=16,
            missing_tls_controlled_connections=50,
            mismatch=30,
            summary="seed_delta.json",
        )

    def fake_teacher_guided_queue(**kwargs):
        calls["teacher_guided_queue_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "repair_candidate_count": 2,
            "ready_candidate_count": 2,
            "expanded_scope_candidate_count": 0,
            "queue_file": str(tmp_path / "teacher_guided_queue.json"),
            "repair_candidates": [
                {
                    "junction_id": "j1",
                    "reference_id": "teacher_j1",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_edge": "candidate_edge"},
                },
                {
                    "junction_id": "j2",
                    "reference_id": "teacher_j2",
                    "candidate_status": "ready_for_teacher_guided_variant",
                    "edge_map": {"teacher_edge": "candidate_edge"},
                },
            ],
            "warnings": [],
        }

    def fake_tls(**_kwargs):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_cluster_count": 1,
            "tls_candidate_count": 1,
            "warnings": [],
        }

    def fake_tls_aggregation(**kwargs):
        variant = visual_tls_net if "reference_visual_detail" in kwargs["prefix"] else tmp_path / "raw_tls.net.xml"
        write_net(variant)
        representatives = tmp_path / f"{kwargs['prefix']}_representatives.csv"
        representatives.write_text(
            "cluster_id,representative_node_id,tls_ids,tls_count,google_maps_url\n"
            "c1,agg_tls,raw_tls;agg_tls,2,\n",
            encoding="utf-8",
        )
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_aggregation_variant_file": str(variant),
            "tls_aggregation_representatives_file": str(representatives),
            "tls_controlled_connection_preservation_status": "fail",
            "warnings": [],
        }

    def fake_tls_connection_repair(**kwargs):
        calls["tls_connection_repair_tls_id_map"] = kwargs["tls_id_map"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "variant_file": str(write_net(repaired_tls_net)),
            "candidate_tls_controlled_connection_count_before": 1,
            "candidate_tls_controlled_connection_count_after": 1,
            "updated_connection_count": 1,
            "skipped_invalid_mapped_linkindex_connection_count": 0,
            "warnings": [],
        }

    def fake_teacher_guided_plain_export(**kwargs):
        calls["teacher_guided_plain_net_file"] = kwargs["net_file"]
        calls["teacher_guided_plain_net_files"].append(kwargs["net_file"])
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "raw_node_file": str(tmp_path / "plain.nod.xml"),
            "raw_edge_file": str(tmp_path / "plain.edg.xml"),
            "raw_connection_file": str(tmp_path / "plain.con.xml"),
            "warnings": [],
        }

    def fake_teacher_guided_run(**_kwargs):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "parity_gate_status": "pass",
            "attempted_candidate_count": 1,
            "pass_candidate_count": 1,
            "composite_applied_candidate_count": 1,
            "composite_net_file": str(write_net(heavy_net)),
            "run_report_file": str(tmp_path / "teacher_guided_run.json"),
            "warnings": [],
        }

    def fake_direct_replay(**kwargs):
        calls["direct_replay_source_net_file"] = kwargs["source_net_file"]
        calls["direct_replay_source_net_files"].append(kwargs["source_net_file"])
        candidate_ids = [
            str(candidate.get("junction_id", ""))
            for candidate in kwargs["queue_report"].get("repair_candidates", [])
        ]
        if not kwargs["prefix"].endswith("_final_movement_rebuild_direct_replay"):
            calls["initial_direct_replay_candidate_ids"].append(candidate_ids)
        direct_net = direct_net_2 if candidate_ids == ["j2"] else direct_net_1
        write_net(direct_net)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "variant_file": str(direct_net),
            "candidate_index": 2 if direct_net == direct_net_2 else 1,
            "junction_id": candidate_ids[0] if candidate_ids else "",
            "sumo_load": {"status": "pass"},
            "variant_reports": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-direct-replay",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        run_routeability_audit_after_build=False,
        run_reference_join_aggregation_after_build=False,
        run_reference_hierarchy_audit_after_build=False,
        run_reference_scope_audit_after_build=False,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        tls_connection_repair_func=fake_tls_connection_repair,
        tls_low_vehicle_control_func=lambda **_kwargs: {"status": "skipped"},
        tls_signal_grouping_func=lambda **_kwargs: {"status": "skipped"},
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "passenger_edge_count": 1},
        topology_audit_func=lambda **_kwargs: {"status": "pass", "topology_fragmentation_status": "pass", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "skipped", "warnings": []},
        sumo_gui_func=lambda _path, **_kwargs: {"status": "blocked", "sumo_gui_status": "skipped", "warnings": []},
        reference_join_audit_func=fake_reference_join_audit,
        teacher_guided_repair_queue_func=fake_teacher_guided_queue,
        teacher_guided_plain_export_func=fake_teacher_guided_plain_export,
        teacher_guided_repair_run_func=fake_teacher_guided_run,
        teacher_guided_direct_replay_func=fake_direct_replay,
        command_runner=lambda command, **_kwargs: {"status": "pass", "returncode": 0, "stdout": "", "stderr": ""},
        review_html_func=lambda **kwargs: {
            "status": "pass",
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "review.html"),
            "workflow_review_net_file": str(kwargs["net_file"]),
            "workflow_report_file": str(tmp_path / "workflow_report.json"),
            "warnings": [],
        },
    )

    assert calls["direct_replay_source_net_files"][0] == calls["teacher_guided_plain_net_files"][0]
    assert calls["direct_replay_source_net_files"][0] == repaired_tls_net
    assert calls["tls_connection_repair_tls_id_map"] == {"raw_tls": "agg_tls", "agg_tls": "agg_tls"}
    assert calls["initial_direct_replay_candidate_ids"] == [["j1"], ["j2"]]
    assert direct_net_1 in calls["reference_join_candidate_net_files"]
    assert direct_net_2 in calls["reference_join_candidate_net_files"]
    assert report["teacher_guided_repair_reference_promotion_status"] == "blocked"
    assert report["teacher_guided_direct_replay_status"] == "pass"
    assert report["teacher_guided_direct_replay_reference_promotion_status"] == "pass"
    assert report["teacher_guided_direct_replay_reference_promotion_reason"] == (
        "direct_local_teacher_replay_promoted_by_reference_delta"
    )
    assert report["reference_visual_detail_comparison_net_file"] == str(direct_net_2)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "direct_local_teacher_replay_promoted_by_reference_delta"
    )


def test_teacher_guided_direct_replay_needed_when_composite_run_parity_fails() -> None:
    assert _teacher_guided_direct_replay_needed(
        repair_promotion_report={"status": "pass"},
        repair_run_report={"status": "fail", "parity_gate_status": "fail"},
    )
    assert not _teacher_guided_direct_replay_needed(
        repair_promotion_report={"status": "pass"},
        repair_run_report={"status": "pass", "parity_gate_status": "pass"},
    )


def test_reference_matched_workflow_uses_direct_replay_when_final_movement_heavy_replay_fails_sumo_load(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "filtered.osm.xml.gz"
    first_heavy_net = tmp_path / "first_heavy.net.xml"
    first_direct_net = tmp_path / "first_direct.net.xml"
    final_heavy_net = tmp_path / "final_heavy.net.xml"
    final_direct_no_gain_net = tmp_path / "final_direct_no_gain.net.xml"
    final_direct_net = tmp_path / "final_direct.net.xml"
    second_stagnant_net = tmp_path / "second_stagnant.net.xml"
    second_direct_net = tmp_path / "second_direct.net.xml"
    third_direct_net = tmp_path / "third_direct.net.xml"
    calls: dict[str, object] = {"direct_sources": [], "reference_join_candidate_net_files": []}

    def write_net(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<net/>", encoding="utf-8")
        return path

    def fake_build(**kwargs):
        net_file = write_net(tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml")
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def delta(*, mismatch: int, connection_extra: int, summary: str) -> dict[str, object]:
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "structural_only",
            "summary_file": str(tmp_path / summary),
            "reference_case_count": 1,
            "matched_case_count": 1,
            "unmatched_case_count": 0,
            "junction_pattern_index": [{"junction_id": "j1"}],
            "junction_pattern_mismatch_count": mismatch,
            "junction_pattern_mismatch_field_counts": {"movement_signature_counts": mismatch} if mismatch else {},
            "junction_pattern_comparisons": [
                {"junction_id": "j1", "status": "fail", "mismatch_fields": ["movement_signature_counts"]}
            ]
            if mismatch
            else [],
            "network_structural_missing_counts": {},
            "network_structural_extra_counts": {"connection_count": connection_extra},
            "tls_control_review_queue": [],
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        candidate = kwargs["candidate_net_file"]
        calls["reference_join_candidate_net_files"].append(candidate)
        if candidate == first_heavy_net:
            return delta(mismatch=2, connection_extra=120, summary="first_heavy_delta.json")
        if candidate == first_direct_net:
            return delta(mismatch=2, connection_extra=90, summary="first_direct_delta.json")
        if candidate == final_heavy_net:
            return delta(mismatch=1, connection_extra=300, summary="final_heavy_delta.json")
        if candidate == final_direct_no_gain_net:
            return delta(mismatch=2, connection_extra=110, summary="final_direct_no_gain_delta.json")
        if candidate == final_direct_net:
            return delta(mismatch=1, connection_extra=95, summary="final_direct_delta.json")
        if candidate == second_stagnant_net:
            return delta(mismatch=2, connection_extra=94, summary="second_stagnant_delta.json")
        if candidate == second_direct_net:
            return delta(mismatch=1, connection_extra=93, summary="second_direct_delta.json")
        if candidate == third_direct_net:
            return delta(mismatch=0, connection_extra=99, summary="third_direct_delta.json")
        return delta(mismatch=2, connection_extra=100, summary="initial_delta.json")

    def fake_teacher_guided_queue(**kwargs):
        is_second_iteration = kwargs["candidate_net_file"] == final_direct_net
        is_third_iteration = kwargs["candidate_net_file"] == second_direct_net
        is_final = kwargs["prefix"].endswith("_final_movement_rebuild")
        repair_candidates = [
            {
                "junction_id": "no_gain" if is_final else "stagnant" if is_second_iteration else "third_gain" if is_third_iteration else "j1",
                "reference_id": "j1",
                "candidate_status": "ready_for_teacher_guided_variant",
                "edge_map": {"teacher_edge": "candidate_edge"},
            },
            *(
                [
                    {
                        "junction_id": "gain",
                        "reference_id": "j1",
                        "candidate_status": "ready_for_teacher_guided_variant",
                        "edge_map": {"teacher_edge": "candidate_edge"},
                    }
                ]
                if is_final
                else []
            ),
            *(
                [
                    {
                        "junction_id": "second_gain",
                        "reference_id": "j1",
                        "candidate_status": "ready_for_teacher_guided_variant",
                        "edge_map": {"teacher_edge": "candidate_edge"},
                    }
                ]
                if is_second_iteration
                else []
            ),
            *(
                [
                    {
                        "junction_id": "third_expanded",
                        "reference_id": "j1",
                        "candidate_status": "needs_expanded_rebuild_scope",
                        "vehicle_movement_matrix_missing_count": 4,
                    }
                ]
                if is_third_iteration
                else []
            ),
        ]
        ready_count = sum(
            1 for candidate in repair_candidates if candidate["candidate_status"] == "ready_for_teacher_guided_variant"
        )
        expanded_scope_count = sum(
            1 for candidate in repair_candidates if candidate["candidate_status"] == "needs_expanded_rebuild_scope"
        )
        return {
            "status": "pass",
            "repair_candidate_count": len(repair_candidates),
            "ready_candidate_count": ready_count,
            "expanded_scope_candidate_count": expanded_scope_count,
            "queue_file": str(
                tmp_path
                / (
                    "third_teacher_queue.json"
                    if is_third_iteration
                    else
                    "second_teacher_queue.json"
                    if is_second_iteration
                    else
                    "final_teacher_queue.json"
                    if is_final
                    else "teacher_queue.json"
                )
            ),
            "repair_candidates": repair_candidates,
        }

    def fake_plain_export(**kwargs):
        return {
            "status": "pass",
            "raw_node_file": str(tmp_path / f"{kwargs['prefix']}.nod.xml"),
            "raw_edge_file": str(tmp_path / f"{kwargs['prefix']}.edg.xml"),
            "raw_connection_file": str(tmp_path / f"{kwargs['prefix']}.con.xml"),
            "raw_type_file": str(tmp_path / f"{kwargs['prefix']}.typ.xml"),
        }

    def fake_repair_run(**kwargs):
        is_final = kwargs["queue_report"]["queue_file"].endswith("final_teacher_queue.json")
        return {
            "status": "fail" if not is_final else "pass",
            "parity_gate_status": "fail" if not is_final else "pass",
            "composite_applied_candidate_count": 1,
            "composite_net_file": str(write_net(final_heavy_net if is_final else first_heavy_net)),
            "run_report_file": str(tmp_path / "teacher_run.json"),
        }

    def fake_direct_replay(**kwargs):
        calls["direct_sources"].append(kwargs["source_net_file"])
        is_final = kwargs["prefix"].endswith("_final_movement_rebuild_direct_replay")
        is_second_iteration = kwargs["source_net_file"] == final_direct_net
        is_third_iteration = kwargs["source_net_file"] == second_direct_net
        first_candidate = (kwargs["queue_report"].get("repair_candidates") or [{}])[0]
        variant = (
            third_direct_net
            if is_third_iteration
            else second_stagnant_net
            if is_second_iteration and first_candidate.get("junction_id") == "stagnant"
            else second_direct_net
            if is_second_iteration
            else
            final_direct_no_gain_net
            if is_final and first_candidate.get("junction_id") == "no_gain"
            else final_direct_net
            if is_final
            else first_direct_net
        )
        return {
            "status": "pass",
            "variant_file": str(write_net(variant)),
            "candidate_index": 1,
            "junction_id": "j1",
            "sumo_load": {"status": "pass"},
            "variant_reports": [],
        }

    def fake_command_runner(_command, **kwargs):
        if Path(str(kwargs.get("cwd", ""))).name == "final_movement_rebuild_sumo_load":
            return {"status": "fail", "returncode": 1, "stdout": "", "stderr": "invalid final heavy net"}
        return {"status": "pass", "returncode": 0, "stdout": "", "stderr": ""}

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-final-direct",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        run_tls_aggregation_after_build=False,
        run_routeability_audit_after_build=False,
        run_reference_join_aggregation_after_build=False,
        run_reference_hierarchy_audit_after_build=False,
        run_reference_scope_audit_after_build=False,
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {"status": "pass", "tls_candidate_count": 0, "warnings": []},
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "passenger_edge_count": 1},
        topology_audit_func=lambda **_kwargs: {"status": "pass", "topology_fragmentation_status": "pass", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "skipped", "warnings": []},
        sumo_gui_func=lambda _path, **_kwargs: {"status": "blocked", "sumo_gui_status": "skipped", "warnings": []},
        reference_join_audit_func=fake_reference_join_audit,
        teacher_guided_repair_queue_func=fake_teacher_guided_queue,
        teacher_guided_plain_export_func=fake_plain_export,
        teacher_guided_repair_run_func=fake_repair_run,
        teacher_guided_direct_replay_func=fake_direct_replay,
        command_runner=fake_command_runner,
        review_html_func=lambda **kwargs: {
            "status": "pass",
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "review.html"),
            "workflow_review_net_file": str(kwargs["net_file"]),
            "workflow_report_file": str(tmp_path / "workflow_report.json"),
            "warnings": [],
        },
    )

    assert calls["direct_sources"] == [
        calls["reference_join_candidate_net_files"][0],
        first_direct_net,
        first_direct_net,
        final_direct_net,
        final_direct_net,
        second_direct_net,
    ]
    assert final_direct_no_gain_net in calls["reference_join_candidate_net_files"]
    assert final_direct_net in calls["reference_join_candidate_net_files"]
    assert second_stagnant_net in calls["reference_join_candidate_net_files"]
    assert second_direct_net in calls["reference_join_candidate_net_files"]
    assert third_direct_net in calls["reference_join_candidate_net_files"]
    assert report["final_movement_direct_replay_status"] == "pass"
    assert report["final_movement_direct_replay_reference_promotion_status"] == "pass"
    assert report["reference_visual_detail_comparison_net_file"] == str(third_direct_net)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "final_direct_local_teacher_replay_promoted_by_reference_delta"
    )
    assert report["reference_join_post_teacher_junction_pattern_mismatch_count"] == 0
    assert report["final_movement_rebuild_junction_pattern_mismatch_count"] == 0
    assert report["final_movement_rebuild_junction_pattern_mismatch_field_counts"] == {}
    assert report["final_movement_rebuild_top_junction_pattern_mismatches"] == []
    assert report["final_movement_direct_replay_last_queue_status"] == "pass"
    assert report["final_movement_direct_replay_last_queue_candidate_count"] == 2
    assert report["final_movement_direct_replay_last_queue_ready_candidate_count"] == 1
    assert report["final_movement_direct_replay_last_queue_expanded_scope_candidate_count"] == 1
    assert report["final_movement_direct_replay_last_queue_max_vehicle_movement_matrix_missing_count"] == 4
    assert str(report["final_movement_direct_replay_last_queue_file"]).endswith(
        "reference-final-direct_final_movement_rebuild_iteration_003_movement_mismatches_filtered_queue.json"
    )


def test_tls_connection_repair_promotion_blocks_reference_delta_regression(tmp_path: Path) -> None:
    variant_file = tmp_path / "repaired.net.xml"
    variant_file.write_text("<net/>", encoding="utf-8")

    decision = _tls_connection_repair_promotion_decision(
        repair_report={
            "status": "pass",
            "variant_file": str(variant_file),
            "skipped_invalid_mapped_linkindex_connection_count": 0,
        },
        sumo_load_report={"status": "pass"},
        rejected_delta_report={
            "network_structural_missing_counts": {"tls_controlled_connection_count": 10},
            "network_structural_extra_counts": {},
        },
        repair_delta_report={
            "status": "pass",
            "network_structural_missing_counts": {"tls_controlled_connection_count": 20},
            "network_structural_extra_counts": {},
        },
    )

    assert decision["status"] == "blocked"
    assert decision["reason"] == "reference_tls_semantic_delta_regressed"


def test_tls_connection_repair_promotion_blocks_incompatible_tllogic_warning(tmp_path: Path) -> None:
    variant_file = tmp_path / "repaired.net.xml"
    variant_file.write_text("<net/>", encoding="utf-8")

    decision = _tls_connection_repair_promotion_decision(
        repair_report={
            "status": "pass",
            "variant_file": str(variant_file),
            "skipped_invalid_mapped_linkindex_connection_count": 0,
        },
        sumo_load_report={
            "status": "pass",
            "stderr": (
                "Warning: Program '0' at tlLogic 'joinedS_10176312934_7881057697' "
                "is incompatible with logic at junction '7881057697'."
            ),
        },
        rejected_delta_report={
            "network_structural_missing_counts": {"tls_controlled_connection_count": 10},
            "network_structural_extra_counts": {},
        },
        repair_delta_report={
            "status": "pass",
            "network_structural_missing_counts": {},
            "network_structural_extra_counts": {},
        },
    )

    assert decision["status"] == "blocked"
    assert decision["reason"] == "sumo_load_tls_incompatible"


def test_movement_rebuild_promotion_blocks_large_structural_regression() -> None:
    decision = _movement_rebuild_reference_delta_promotion_decision(
        baseline_delta_report={
            "status": "pass",
            "junction_pattern_mismatch_field_counts": {
                "movement_signature_counts": 7,
                "internal_function_counts": 6,
            },
            "network_structural_missing_counts": {"crossing_edge_count": 145},
            "network_structural_extra_counts": {"connection_count": 570},
        },
        candidate_delta_report={
            "status": "pass",
            "junction_pattern_mismatch_field_counts": {},
            "junction_pattern_mismatch_count": 0,
            "network_structural_missing_counts": {"crossing_edge_count": 147},
            "network_structural_extra_counts": {"connection_count": 2649},
        },
        reason="final_movement_rebuild_promoted_by_reference_delta",
    )

    assert decision["status"] == "blocked"
    assert decision["reason"] == "reference_structural_delta_regressed"


def test_movement_rebuild_promotion_blocks_no_benefit_structural_regression() -> None:
    decision = _movement_rebuild_reference_delta_promotion_decision(
        baseline_delta_report={
            "status": "pass",
            "junction_pattern_mismatch_field_counts": {"movement_signature_counts": 13},
            "network_structural_missing_counts": {"crossing_edge_count": 100},
            "network_structural_extra_counts": {"connection_count": 1861},
        },
        candidate_delta_report={
            "status": "pass",
            "junction_pattern_mismatch_field_counts": {"movement_signature_counts": 13},
            "network_structural_missing_counts": {"crossing_edge_count": 100},
            "network_structural_extra_counts": {"connection_count": 1872},
        },
        reason="iterative_direct_local_teacher_replay_promoted_by_reference_delta",
    )

    assert decision["status"] == "blocked"
    assert decision["reason"] == "movement_rebuild_no_reference_delta_improvement"


def test_movement_rebuild_promotion_uses_structural_guard_baseline() -> None:
    decision = _movement_rebuild_reference_delta_promotion_decision(
        baseline_delta_report={
            "status": "pass",
            "junction_pattern_mismatch_field_counts": {
                "movement_signature_counts": 13,
            },
            "network_structural_missing_counts": {"crossing_edge_count": 127},
            "network_structural_extra_counts": {"connection_count": 2664},
        },
        candidate_delta_report={
            "status": "pass",
            "junction_pattern_mismatch_field_counts": {},
            "junction_pattern_mismatch_count": 0,
            "network_structural_missing_counts": {"crossing_edge_count": 147},
            "network_structural_extra_counts": {"connection_count": 2649},
        },
        structural_guard_delta_report={
            "status": "pass",
            "junction_pattern_mismatch_field_counts": {
                "movement_signature_counts": 30,
            },
            "network_structural_missing_counts": {"crossing_edge_count": 145},
            "network_structural_extra_counts": {"connection_count": 570},
        },
        reason="final_movement_rebuild_promoted_by_reference_delta",
    )

    assert decision["status"] == "blocked"
    assert decision["reason"] == "reference_structural_delta_regressed"
    assert decision["guard_total_structural_delta_score"] == 715


def test_reference_delta_promotion_prefers_candidate_with_lower_tls_semantic_score() -> None:
    decision = _reference_delta_promotion_decision(
        candidate_delta_report={
            "status": "pass",
            "network_structural_missing_counts": {"tls_controlled_connection_count": 165},
            "network_structural_extra_counts": {"traffic_light_junction_count": 46},
        },
        baseline_delta_report={
            "status": "pass",
            "network_structural_missing_counts": {"tls_shared_linkindex_group_count": 40},
            "network_structural_extra_counts": {"traffic_light_junction_count": 354},
        },
        reason="tls_aggregation_promoted_by_reference_delta",
    )

    assert decision["status"] == "pass"
    assert decision["reason"] == "tls_aggregation_promoted_by_reference_delta"
    assert decision["candidate_tls_semantic_delta_score"] == 211
    assert decision["baseline_tls_semantic_delta_score"] == 394


def test_low_vehicle_control_candidate_limits_include_tls_count_fallback() -> None:
    limits = _low_vehicle_control_candidate_limits(
        {
            "network_structural_extra_counts": {
                "tl_logic_count": 41,
                "traffic_light_junction_count": 46,
            },
            "tls_control_review_queue": [
                {
                    "review_type": "downgrade_low_vehicle_approach_tls",
                    "tl_id": str(index),
                }
                for index in range(60)
            ],
        }
    )

    assert limits == [
        {
            "label": "tls10",
            "max_removed_controlled_connections": None,
            "max_selected_tllogic_count": 10,
        },
        {
            "label": "tls20",
            "max_removed_controlled_connections": None,
            "max_selected_tllogic_count": 20,
        },
        {
            "label": "tls41",
            "max_removed_controlled_connections": None,
            "max_selected_tllogic_count": 41,
        },
    ]


def test_network_plan_blocks_when_layers_and_reference_are_missing() -> None:
    plan = derive_network_plan()

    assert plan["status"] == "blocked"
    assert plan["network_plan_status"] == "needs_user_confirmation"
    assert plan["missing_blockers"] == ["network_plan"]
    assert "traffic layers" in plan["next_question"]
    assert "reference_matched" in plan["network_detail_options"]


def test_network_plan_blocks_named_reference_without_reference_artifact() -> None:
    plan = derive_network_plan(
        user_request="Generate a city-center SUMO network matching a manually cleaned reference network",
    )

    assert plan["status"] == "blocked"
    assert plan["network_plan_status"] == "needs_reference_artifact"
    assert plan["network_detail_target"] == "reference_matched"
    assert plan["reference_target"] == "manually cleaned reference network"
    assert plan["missing_blockers"] == ["reference_network_or_policy"]
    assert "reference SUMO .net.xml" in plan["next_question"]


def test_network_plan_derives_reference_policy_from_reference_net(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "manual-reference.net.xml"
    _write_reference_net(reference_net_file)

    plan = derive_network_plan(
        user_request="Generate an OSM network that matches a manually cleaned reference network",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
    )

    assert plan["status"] == "pass"
    assert plan["network_plan_status"] == "inferred_from_reference_policy"
    assert plan["network_profile"] == "reference_matched"
    assert plan["reference_net_file"] == str(reference_net_file)
    assert plan["network_detail_target"] == "reference_matched"
    assert plan["primary_network_layer"] == "passenger_vehicle"
    assert plan["default_routeability_layer"] == "vehicle_core"
    assert plan["default_netedit_comparison_layer"] == "reference_visual_detail"
    assert plan["vehicle_core_highway_classes"] == plan["highway_classes"]
    assert "service" not in plan["highway_classes"]
    assert "service" in plan["reference_visual_detail_highway_classes"]
    assert "service" in plan["reference_visual_detail_only_highway_classes"]
    assert "primary" in plan["highway_classes"]
    assert "residential" in plan["highway_classes"]
    assert "cycleway" not in plan["highway_classes"]
    assert "footway" not in plan["highway_classes"]
    assert "path" not in plan["highway_classes"]
    assert {"cycleway", "footway", "path"} <= set(plan["reference_visual_detail_highway_classes"])
    assert {"cycleway", "footway", "path"} <= set(plan["reference_visual_detail_only_highway_classes"])
    assert {"passenger", "bicycle", "pedestrian", "bus"} <= set(plan["movement_layers"])
    assert set(plan["auxiliary_modal_layers"]) == {"bicycle", "pedestrian", "bus"}
    assert plan["reference_policy"]["reference_policy_status"] == "analyzed"
    assert plan["reference_policy"]["passenger_edge_type_counts"]["highway.service"] == 2
    assert plan["reference_policy"]["visual_detail_edge_type_counts"]["highway.footway"] == 1
    assert plan["service_passenger_policy"] == "reference_match"
    assert "routeability_audit" in plan["validation_gates"]
    assert "scope_matched_reference_comparison" in plan["validation_gates"]
    assert "reference_join_audit" in plan["validation_gates"]
    assert "junction_pattern_index" in plan["validation_gates"]
    assert "road_connectivity_parity" in plan["validation_gates"]
    assert "connection_semantics_parity" in plan["validation_gates"]
    assert "tls_semantics_parity" in plan["validation_gates"]
    assert "internal_junction_parity" in plan["validation_gates"]
    assert "netedit_connection_mode_review" in plan["validation_gates"]
    assert "teacher_guided_junction_parity" in plan["validation_gates"]


def test_network_plan_derives_reference_source_way_ids_from_osm_edge_ids(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "manual-reference.net.xml"
    reference_net_file.write_text(
        """<net>
    <edge id="12345#0" type="highway.primary">
        <lane id="12345#0_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
    <edge id="-67890#2" type="highway.service">
        <lane id="-67890#2_0" index="0" allow="passenger pedestrian" speed="5.0" length="25.0"/>
    </edge>
    <edge id="synthetic_edge" type="highway.footway">
        <lane id="synthetic_edge_0" index="0" allow="pedestrian" speed="5.0" length="25.0"/>
    </edge>
</net>""",
        encoding="utf-8",
    )

    plan = derive_network_plan(
        user_request="Generate an OSM network that matches a manually cleaned reference network",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
    )

    assert plan["reference_source_way_ids"] == ["12345", "67890"]
    assert plan["reference_policy"]["reference_source_way_id_count"] == 2


def test_reference_matched_plan_keeps_service_out_of_vehicle_core(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "manual-reference.net.xml"
    _write_reference_net(reference_net_file)

    plan = derive_network_plan(
        user_request="Generate an OSM network that mimics a manually cleaned TUM reference network",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
    )

    assert plan["status"] == "pass"
    assert "service" not in plan["highway_classes"]
    assert "service" not in plan["vehicle_core_highway_classes"]
    assert "service" in plan["reference_visual_detail_highway_classes"]
    assert "service" in plan["reference_visual_detail_only_highway_classes"]
    assert plan["service_passenger_policy"] == "reference_match"


def test_reference_bbox_uses_reference_geometry_not_stale_orig_boundary(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "clipped-reference.net.xml"
    reference_net_file.write_text(
        """<net>
    <location netOffset="0.00,0.00" convBoundary="100.00,300.00,200.00,400.00" origBoundary="0.000000,0.000000,99.000000,99.000000"/>
    <junction id="left" type="priority" x="100.00" y="300.00"/>
    <junction id="right" type="priority" x="200.00" y="400.00"/>
    <edge id="e0" from="left" to="right" type="highway.primary">
        <lane id="e0_0" index="0" speed="13.9" length="141.0" shape="100.00,300.00 200.00,400.00"/>
    </edge>
</net>""",
        encoding="utf-8",
    )

    report = derive_reference_net_bbox(
        reference_net_file,
        padding_m=0.0,
        xy_to_latlon_func=lambda x, y: (y / 100.0, x / 100.0),
    )

    assert report["status"] == "pass"
    assert report["reference_bbox_status"] == "derived_from_reference_geometry"
    assert report["reference_bbox"] == "1.0000000,3.0000000,2.0000000,4.0000000"
    assert report["reference_bbox_source"] == "junction_and_lane_geometry"
    assert report["reference_orig_boundary"] == "0.000000,0.000000,99.000000,99.000000"


def test_apply_service_passenger_permissions_adds_passenger_to_service_lanes(tmp_path: Path) -> None:
    net_file = tmp_path / "network.net.xml"
    net_file.write_text(
        """<net>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="bicycle delivery pedestrian" speed="5.0" length="25.0"/>
    </edge>
    <edge id="residential_b" type="highway.residential">
        <lane id="residential_b_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
</net>""",
        encoding="utf-8",
    )

    report = apply_service_passenger_permissions(net_file, policy="allow_vehicle_service")

    root = ET.parse(net_file).getroot()
    service_lane = root.find("./edge[@id='service_a']/lane")
    residential_lane = root.find("./edge[@id='residential_b']/lane")
    assert report["status"] == "pass"
    assert report["service_passenger_permission_status"] == "applied"
    assert report["service_edge_count"] == 1
    assert report["changed_lane_count"] == 1
    assert "passenger" in service_lane.attrib["allow"].split()
    assert residential_lane.attrib["allow"] == "passenger"


def test_export_plain_net_for_teacher_guided_repair_resolves_relative_output_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    calls: dict[str, object] = {}

    def fake_command(command, **kwargs):
        calls["command"] = command
        calls["cwd"] = kwargs["cwd"]
        plain_prefix = Path(command[-1])
        for suffix in (".nod.xml", ".edg.xml", ".con.xml"):
            Path(f"{plain_prefix}{suffix}").write_text("<xml/>", encoding="utf-8")
        return {"status": "pass", "returncode": 0}

    report = export_plain_net_for_teacher_guided_repair(
        net_file=Path("candidate.net.xml"),
        output_dir=Path("plain"),
        prefix="demo",
        command_runner=fake_command,
    )

    expected_prefix = tmp_path / "plain" / "demo"
    assert report["status"] == "pass"
    assert calls["command"][-1] == str(expected_prefix)
    assert calls["cwd"] == tmp_path / "plain"
    assert report["raw_node_file"] == str(expected_prefix) + ".nod.xml"


def test_export_plain_net_for_teacher_guided_repair_uses_short_source_copy(
    tmp_path: Path,
) -> None:
    long_dir = tmp_path / ("source_" + "x" * 120)
    net_file = long_dir / ("candidate_" + "y" * 120 + ".net.xml")
    net_file.parent.mkdir(parents=True)
    net_file.write_text("<net/>", encoding="utf-8")
    calls: dict[str, object] = {}

    def fake_command(command, **kwargs):
        calls["command"] = command
        source_arg = Path(command[2])
        assert len(str(source_arg)) < 120
        assert source_arg.name == "plain_source.net.xml"
        assert (kwargs["cwd"] / source_arg).exists()
        plain_prefix = Path(command[-1])
        for suffix in (".nod.xml", ".edg.xml", ".con.xml"):
            Path(f"{plain_prefix}{suffix}").write_text("<xml/>", encoding="utf-8")
        return {"status": "pass", "returncode": 0}

    report = export_plain_net_for_teacher_guided_repair(
        net_file=net_file,
        output_dir=tmp_path / "plain",
        prefix="demo",
        command_runner=fake_command,
    )

    assert report["status"] == "pass"
    assert calls["command"][2] == "plain_source.net.xml"


def test_export_plain_net_for_teacher_guided_repair_synthesizes_missing_used_edge_types(
    tmp_path: Path,
) -> None:
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    def fake_command(command, **_kwargs):
        plain_prefix = Path(command[-1])
        Path(f"{plain_prefix}.nod.xml").write_text("<nodes/>", encoding="utf-8")
        Path(f"{plain_prefix}.con.xml").write_text("<connections/>", encoding="utf-8")
        Path(f"{plain_prefix}.typ.xml").write_text(
            '<types><type id="highway.residential" priority="3" numLanes="1" speed="13.89"/></types>',
            encoding="utf-8",
        )
        Path(f"{plain_prefix}.edg.xml").write_text(
            """<edges>
    <edge id="753083363" from="a" to="b" type="cycleway.lane|highway.unclassified"
          priority="4" numLanes="4" speed="8.33">
        <lane index="0" allow="pedestrian" width="2.00"/>
        <lane index="1" allow="bicycle" width="1.00"/>
    </edge>
</edges>""",
            encoding="utf-8",
        )
        return {"status": "pass", "returncode": 0}

    report = export_plain_net_for_teacher_guided_repair(
        net_file=net_file,
        output_dir=tmp_path / "plain",
        prefix="demo",
        command_runner=fake_command,
    )

    type_root = ET.parse(report["raw_type_file"]).getroot()
    synthesized = type_root.find("./type[@id='cycleway.lane|highway.unclassified']")
    assert report["status"] == "pass"
    assert report["synthesized_edge_type_count"] == 1
    assert report["synthesized_edge_type_ids"] == ["cycleway.lane|highway.unclassified"]
    assert synthesized is not None
    assert synthesized.attrib["priority"] == "4"
    assert synthesized.attrib["numLanes"] == "4"
    assert synthesized.attrib["speed"] == "8.33"


def test_export_plain_net_for_teacher_guided_repair_restores_false_tls_plain_nodes(
    tmp_path: Path,
) -> None:
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text(
        """<net>
    <junction id="j_false" type="priority"/>
    <junction id="j_real" type="traffic_light"/>
    <tlLogic id="j_real" type="static" programID="0" offset="0"/>
</net>""",
        encoding="utf-8",
    )

    def fake_command(command, **_kwargs):
        plain_prefix = Path(command[-1])
        Path(f"{plain_prefix}.nod.xml").write_text(
            """<nodes>
    <node id="j_false" type="traffic_light" x="0" y="0"/>
    <node id="j_real" type="traffic_light" x="1" y="0"/>
</nodes>""",
            encoding="utf-8",
        )
        Path(f"{plain_prefix}.edg.xml").write_text("<edges/>", encoding="utf-8")
        Path(f"{plain_prefix}.con.xml").write_text("<connections/>", encoding="utf-8")
        Path(f"{plain_prefix}.tll.xml").write_text(
            '<tlLogics><tlLogic id="j_real" type="static" programID="0" offset="0"/></tlLogics>',
            encoding="utf-8",
        )
        return {"status": "pass", "returncode": 0}

    report = export_plain_net_for_teacher_guided_repair(
        net_file=net_file,
        output_dir=tmp_path / "plain",
        prefix="demo",
        command_runner=fake_command,
    )

    node_root = ET.parse(report["raw_node_file"]).getroot()
    assert report["restored_false_traffic_light_plain_node_count"] == 1
    assert report["restored_false_traffic_light_plain_node_ids"] == ["j_false"]
    assert node_root.find("./node[@id='j_false']").attrib["type"] == "priority"
    assert node_root.find("./node[@id='j_real']").attrib["type"] == "traffic_light"


def test_export_plain_net_for_teacher_guided_repair_prunes_stale_plain_tllogics(
    tmp_path: Path,
) -> None:
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text(
        """<net>
    <junction id="old_tls" type="priority"/>
    <junction id="cluster_tls" type="traffic_light" tl="cluster_tls"/>
    <tlLogic id="cluster_tls" type="static" programID="0" offset="0"/>
</net>""",
        encoding="utf-8",
    )

    def fake_command(command, **_kwargs):
        plain_prefix = Path(command[-1])
        Path(f"{plain_prefix}.nod.xml").write_text(
            """<nodes>
    <node id="old_tls" type="traffic_light" x="0" y="0"/>
    <node id="cluster_tls" type="traffic_light" tl="cluster_tls" x="1" y="0"/>
</nodes>""",
            encoding="utf-8",
        )
        Path(f"{plain_prefix}.edg.xml").write_text("<edges/>", encoding="utf-8")
        Path(f"{plain_prefix}.con.xml").write_text("<connections/>", encoding="utf-8")
        Path(f"{plain_prefix}.tll.xml").write_text(
            """<tlLogics>
    <tlLogic id="old_tls" type="static" programID="0" offset="0"/>
    <tlLogic id="cluster_tls" type="static" programID="0" offset="0"/>
    <connection from="a" to="b" fromLane="0" toLane="0" tl="old_tls" linkIndex="0"/>
    <connection from="c" to="d" fromLane="0" toLane="0" tl="cluster_tls" linkIndex="0"/>
</tlLogics>""",
            encoding="utf-8",
        )
        return {"status": "pass", "returncode": 0}

    report = export_plain_net_for_teacher_guided_repair(
        net_file=net_file,
        output_dir=tmp_path / "plain",
        prefix="demo",
        command_runner=fake_command,
    )

    tllogic_root = ET.parse(report["raw_tllogic_file"]).getroot()
    assert report["status"] == "pass"
    assert report["restored_false_traffic_light_plain_node_ids"] == ["old_tls"]
    assert report["removed_stale_plain_tllogic_ids"] == ["old_tls"]
    assert report["removed_stale_plain_tllogic_count"] == 1
    assert report["removed_stale_plain_tllogic_connection_count"] == 1
    assert tllogic_root.find("./tlLogic[@id='old_tls']") is None
    assert tllogic_root.find("./tlLogic[@id='cluster_tls']") is not None
    assert tllogic_root.find("./connection[@tl='old_tls']") is None
    assert tllogic_root.find("./connection[@tl='cluster_tls']") is not None


def test_export_plain_net_for_teacher_guided_repair_shortens_long_plain_prefix(
    tmp_path: Path,
) -> None:
    net_file = tmp_path / "candidate.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    long_prefix = "sumo_osm_cleanup_post_teacher_tls_connection_repair_movement_rebuild_" + ("x" * 160)

    def fake_command(command, **_kwargs):
        plain_prefix = Path(command[-1])
        assert len(str(plain_prefix.resolve())) + len(".nod.xml") < 240
        for suffix in (".nod.xml", ".edg.xml", ".con.xml"):
            Path(f"{plain_prefix}{suffix}").write_text("<xml/>", encoding="utf-8")
        return {"status": "pass", "returncode": 0}

    report = export_plain_net_for_teacher_guided_repair(
        net_file=net_file,
        output_dir=tmp_path / "plain",
        prefix=long_prefix,
        command_runner=fake_command,
    )

    assert report["status"] == "pass"
    assert report["plain_output_prefix_shortened"] is True
    assert Path(report["plain_output_prefix"]).name.endswith("_" + report["plain_output_prefix_digest"])


def test_osm_cleanup_workflow_uses_reference_net_policy_and_service_policy(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    net_file = tmp_path / "sumo" / "reference-matched.net.xml"
    raw_osm = tmp_path / "osm" / "reference-matched_bbox.osm.xml"
    filtered_osm = tmp_path / "osm" / "reference-matched_filtered.osm.xml"
    build_calls: list[dict[str, object]] = []

    def fake_build(**kwargs):
        build_calls.append(
            {
                "prefix": kwargs["prefix"],
                "allowed_highways": set(kwargs["allowed_highways"]),
                "source_osm_path": kwargs.get("source_osm_path"),
                "netconvert_profile": kwargs.get("netconvert_profile"),
            }
        )
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        if "service" in kwargs["allowed_highways"]:
            net_xml = """<net>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="bicycle delivery pedestrian" speed="5.0" length="25.0"/>
    </edge>
</net>"""
        else:
            net_xml = """<net>
    <edge id="primary_a" type="highway.primary">
        <lane id="primary_a_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
</net>"""
        current_net_file.write_text(net_xml, encoding="utf-8")
        _write_osm_highways(raw_osm, ["primary", "residential", "service", "cycleway", "footway", "path"])
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(raw_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-matched",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        },
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 1,
            "passenger_component_count": 1,
            "largest_component_edge_count": 1,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
    )

    visual_detail_net_file = tmp_path / "sumo" / "reference-matched_reference_visual_detail.net.xml"
    service_lane = ET.parse(net_file).getroot().find("./edge[@id='service_a']/lane")
    visual_service_lane = ET.parse(visual_detail_net_file).getroot().find("./edge[@id='service_a']/lane")
    assert report["status"] == "pass"
    assert report["network_profile"] == "reference_matched"
    assert report["network_plan_status"] == "inferred_from_reference_policy"
    assert report["reference_net_file"] == str(reference_net_file)
    assert report["service_passenger_policy"] == "reference_match"
    assert len(build_calls) == 2
    assert build_calls[0]["prefix"] == "reference-matched"
    assert build_calls[1]["prefix"] == "reference-matched_reference_visual_detail"
    assert build_calls[0]["netconvert_profile"] == "vehicle_core"
    assert build_calls[1]["netconvert_profile"] == "reference_visual_detail"
    assert "service" not in build_calls[0]["allowed_highways"]
    assert "service" in build_calls[1]["allowed_highways"]
    assert "cycleway" not in build_calls[0]["allowed_highways"]
    assert "footway" not in build_calls[0]["allowed_highways"]
    assert "path" not in build_calls[0]["allowed_highways"]
    assert {"cycleway", "footway", "path"} <= build_calls[1]["allowed_highways"]
    assert build_calls[1]["source_osm_path"] == raw_osm
    assert service_lane is None
    assert "passenger" in visual_service_lane.attrib["allow"].split()
    assert report["service_passenger_permissions"]["changed_lane_count"] == 0
    assert report["reference_visual_detail_service_passenger_permissions"]["changed_lane_count"] == 1
    assert report["reference_visual_detail_status"] == "built"
    assert report["reference_visual_detail_net_file"] == str(visual_detail_net_file)
    assert report["reference_visual_detail_build"]["road_classes"] == sorted(build_calls[1]["allowed_highways"])


def test_reference_matched_workflow_passes_reference_source_way_scope_to_build(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    reference_net_file.write_text(
        """<net>
    <edge id="101#0" type="highway.primary">
        <lane id="101#0_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
    <edge id="-202#1" type="highway.service">
        <lane id="-202#1_0" index="0" allow="passenger pedestrian" speed="5.0" length="25.0"/>
    </edge>
    <edge id="303" type="highway.footway">
        <lane id="303_0" index="0" allow="pedestrian" speed="5.0" length="25.0"/>
    </edge>
</net>""",
        encoding="utf-8",
    )
    source_osm = tmp_path / "source.osm.xml"
    source_osm.write_text("<osm/>", encoding="utf-8")
    build_calls: list[dict[str, object]] = []

    def fake_build(**kwargs):
        build_calls.append(
            {
                "prefix": kwargs["prefix"],
                "allowed_way_ids": set(kwargs["allowed_way_ids"]),
            }
        )
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text(
            """<net>
    <edge id="101#0" type="highway.primary">
        <lane id="101#0_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
</net>""",
            encoding="utf-8",
        )
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(source_osm),
            "source_osm_file": str(source_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-scope",
        source_osm_path=source_osm,
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        },
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 1,
            "passenger_component_count": 1,
            "largest_component_edge_count": 1,
            "warnings": [],
        },
        run_tls_aggregation_after_build=False,
        run_topology_audit_after_build=False,
        run_routeability_audit_after_build=False,
        run_reference_join_audit_after_build=False,
        run_reference_hierarchy_audit_after_build=False,
        run_reference_scope_audit_after_build=False,
        launch_netedit_after_build=False,
        launch_sumo_gui_after_build=False,
    )

    assert report["status"] == "pass"
    assert len(build_calls) == 2
    assert build_calls[0]["allowed_way_ids"] == {"101", "202", "303"}
    assert build_calls[1]["allowed_way_ids"] == {"101", "202", "303"}
    assert report["reference_source_way_id_count"] == 3


def test_reference_visual_detail_redownloads_when_vehicle_core_source_lacks_visual_classes(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    vehicle_only_source = tmp_path / "osm" / "vehicle_core_filtered.osm.xml"
    _write_osm_highways(vehicle_only_source, ["primary", "residential"])
    build_calls: list[dict[str, object]] = []

    def fake_build(**kwargs):
        build_calls.append(
            {
                "prefix": kwargs["prefix"],
                "source_osm_path": kwargs.get("source_osm_path"),
                "allowed_highways": set(kwargs["allowed_highways"]),
            }
        )
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        if "service" in kwargs["allowed_highways"]:
            current_net_file.write_text(
                """<net>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="passenger pedestrian" speed="5.0" length="25.0"/>
    </edge>
</net>""",
                encoding="utf-8",
            )
        else:
            current_net_file.write_text(
                """<net>
    <edge id="primary_a" type="highway.primary">
        <lane id="primary_a_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
</net>""",
                encoding="utf-8",
            )
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(vehicle_only_source),
            "source_osm_file": str(kwargs.get("source_osm_path") or vehicle_only_source),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-matched",
        source_osm_path=vehicle_only_source,
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        },
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 1,
            "passenger_component_count": 1,
            "largest_component_edge_count": 1,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
    )

    assert report["status"] == "pass"
    assert len(build_calls) == 2
    assert build_calls[0]["source_osm_path"] == vehicle_only_source
    assert {"service", "footway", "path"} <= build_calls[1]["allowed_highways"]
    assert build_calls[1]["source_osm_path"] is None


def test_reference_matched_workflow_audits_reference_join_on_visual_detail_layer(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-join_filtered.osm.xml.gz"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text(
            """<net>
    <edge id="service_a" type="highway.service">
        <lane id="service_a_0" index="0" allow="passenger" speed="5.0" length="25.0"/>
    </edge>
</net>""",
            encoding="utf-8",
        )
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
        calls["reference_join_structural_only"] = kwargs["structural_only"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "reference_case_count": 3,
            "matched_case_count": 2,
            "unmatched_case_count": 1,
            "junction_pattern_index": [{"junction_id": "cluster_a_b"}],
            "summary_file": str(tmp_path / "reference_join_audit.json"),
            "cases_file": str(tmp_path / "reference_join_cases.csv"),
            "junction_teacher_delta_file": str(tmp_path / "junction_teacher_delta.json"),
            "junction_pattern_comparisons_file": str(tmp_path / "junction_pattern_comparisons.csv"),
            "junction_pattern_templates_file": str(tmp_path / "junction_pattern_templates.json"),
            "junction_pattern_comparison_status": "fail",
            "junction_pattern_mismatch_count": 2,
            "junction_pattern_mismatch_field_counts": {"internal_function_counts": 2},
            "junction_pattern_comparisons": [
                {"junction_id": "j1", "status": "fail"},
                {"junction_id": "j2", "status": "pass"},
            ],
            "junction_structural_signature_status": "fail",
            "junction_structural_signature_missing_counts": {"tls_pattern_count": 1},
            "reference_structural_signature_summary": {
                "pattern_count": 2,
                "tls_pattern_count": 1,
            },
            "candidate_structural_signature_summary": {
                "pattern_count": 2,
                "tls_pattern_count": 0,
            },
            "network_structural_delta_status": "fail",
            "network_structural_missing_counts": {"crossing_edge_count": 620, "walkingarea_edge_count": 1648},
            "network_structural_extra_counts": {"tl_logic_count": 35, "traffic_light_junction_count": 41},
            "network_structural_junction_type_missing_counts": {"traffic_light": 1},
            "network_structural_junction_type_extra_counts": {"priority": 22},
            "reference_network_structural_summary": {
                "crossing_edge_count": 620,
                "walkingarea_edge_count": 1648,
            },
            "candidate_network_structural_summary": {
                "crossing_edge_count": 0,
                "walkingarea_edge_count": 0,
            },
            "tls_control_review_status": "needs_review",
            "tls_control_review_queue_count": 2,
            "tls_control_review_queue": [
                {"repair_category": "tls_controller_cardinality_repair", "review_type": "split_multi_junction_tls"},
                {"repair_category": "tls_linkindex_phase_repair", "review_type": "restore_shared_linkindex_groups"},
            ],
            "warnings": [],
        }

    def fake_reference_join_aggregation(**kwargs):
        calls["aggregation_candidate_net_file"] = kwargs["net_file"]
        calls["aggregation_audit_report"] = kwargs["reference_join_audit_report"]
        aggregated_net = tmp_path / "aggregated.net.xml"
        aggregated_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "junction_aggregation_status": "variant_created_for_review",
            "junction_aggregation_variant_file": str(aggregated_net),
            "junction_aggregation_plan_file": str(tmp_path / "aggregation_plan.json"),
            "junction_aggregation_candidate_count": 2,
            "junction_aggregation_preservation_status": "review",
            "junction_aggregation_preservation_audit_file": str(tmp_path / "aggregation_preservation.json"),
            "junction_aggregation_removed_normal_edge_count": 5,
            "junction_aggregation_removed_normal_edge_type_counts": {"highway.service": 3, "highway.primary": 2},
            "junction_aggregation_removed_normal_edge_mode_counts": {"passenger": 4, "bicycle": 1},
            "junction_aggregation_lost_shared_connection_count": 2,
            "junction_aggregation_new_dangling_shared_normal_edge_count": 1,
            "warnings": ["junction aggregation variant requires Google Maps review before adoption"],
        }

    def fake_teacher_guided_repair_queue(**kwargs):
        calls["teacher_guided_candidate_net_file"] = kwargs["candidate_net_file"]
        calls["teacher_guided_queue_max_ready_candidates"] = kwargs["max_ready_candidates"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "repair_candidate_count": 2,
            "ready_candidate_count": 0,
            "expanded_scope_candidate_count": 1,
            "queue_file": str(tmp_path / "teacher_guided_queue.json"),
            "queue_csv_file": str(tmp_path / "teacher_guided_queue.csv"),
            "tls_repair_candidate_count": 2,
            "tls_repair_category_counts": {
                "tls_controller_cardinality_repair": 1,
                "tls_linkindex_phase_repair": 1,
            },
            "repair_candidates": [
                {
                    "reference_id": "cluster_a_b",
                    "candidate_status": "needs_expanded_rebuild_scope",
                    "vehicle_movement_matrix_missing_count": 12,
                    "missing_teacher_movement_plan_count": 2,
                    "missing_teacher_movement_plan": [
                        {
                            "from_edge_id": "cand_in",
                            "to_edge_id": "cand_out",
                            "fromLane": "0",
                            "toLane": "0",
                            "dir": "s",
                            "tl": "tlsA",
                            "linkIndex": "3",
                        },
                        {
                            "from_edge_id": "cand_in",
                            "to_edge_id": "cand_left",
                            "fromLane": "1",
                            "toLane": "0",
                            "dir": "l",
                            "tl": "tlsA",
                            "linkIndex": "4",
                        },
                    ],
                    "netedit_review_actions": ["rebuild_vehicle_movement_matrix"],
                    "slot_edge_map": {"slot_0": "cand_in", "slot_1": "cand_out"},
                    "movement_exemplar": {
                        "movement_signatures": [
                            {"from_slot": "slot_0", "to_slot": "slot_1"},
                            {"from_slot": "slot_0", "to_slot": "slot_2"},
                        ]
                    },
                },
                {
                    "reference_id": "cluster_c_d",
                    "candidate_status": "blocked_pending_junction_rebuild",
                    "netedit_review_actions": ["audit_owner_road_continuity"],
                }
            ],
            "warnings": [],
        }

    def fake_teacher_guided_plain_export(**kwargs):
        calls["teacher_guided_plain_net_file"] = kwargs["net_file"]
        calls["teacher_guided_plain_netconvert_binary"] = kwargs["netconvert_binary"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "raw_node_file": str(tmp_path / "plain.nod.xml"),
            "raw_edge_file": str(tmp_path / "plain.edg.xml"),
            "raw_connection_file": str(tmp_path / "plain.con.xml"),
            "raw_type_file": str(tmp_path / "plain.typ.xml"),
            "warnings": [],
        }

    def fake_teacher_guided_repair_run(**kwargs):
        calls["teacher_guided_run_queue_report"] = kwargs["queue_report"]
        calls["teacher_guided_run_raw_node_file"] = kwargs["raw_node_file"]
        calls["teacher_guided_run_replay_target_internal_subgraph"] = kwargs["replay_target_internal_subgraph"]
        calls["teacher_guided_run_netconvert_binary"] = kwargs["netconvert_binary"]
        calls["teacher_guided_run_sumo_binary"] = kwargs["sumo_binary"]
        calls["teacher_guided_run_max_ready_candidates"] = kwargs["max_ready_candidates"]
        calls["teacher_guided_run_sequential_accept_passed_variants"] = kwargs["sequential_accept_passed_variants"]
        calls["teacher_guided_run_plain_exporter"] = kwargs["plain_exporter"]
        best_expanded = tmp_path / "expanded_scope.net.xml"
        best_expanded.write_text("<net/>", encoding="utf-8")
        return {
            "status": "blocked",
            "claim_status": "blocked",
            "parity_gate_status": "blocked",
            "attempted_candidate_count": 0,
            "pass_candidate_count": 0,
            "expanded_scope_candidate_count": 1,
            "expanded_scope_pass_candidate_count": 1,
            "best_expanded_scope_net_file": str(best_expanded),
            "semantic_failure_counts": {},
            "approach_integrity_status": "blocked",
            "approach_integrity_failure_counts": {},
            "teacher_pattern_contexts": [
                {
                    "teacher_pattern_key": "three_way|control=right_before_left",
                    "teacher_pattern_family": "three_way",
                    "teacher_pattern_template_count": 127,
                    "teacher_pattern_template_examples": ["cluster_template_1"],
                }
            ],
            "variant_reports": [],
            "run_report_file": str(tmp_path / "teacher_guided_run.json"),
            "semantic_layer_gate_counts": {
                "movement_tls": {"pass": 1, "fail": 0, "failure_count": 0},
                "pedestrian_bike": {"pass": 0, "fail": 1, "failure_count": 2},
            },
            "warnings": [],
        }

    def fake_road_connectivity_replay(**kwargs):
        calls["road_connectivity_teacher_net_file"] = kwargs["teacher_net_file"]
        calls["road_connectivity_candidate_net_file"] = kwargs["candidate_net_file"]
        calls.setdefault("road_connectivity_candidate_net_files", []).append(kwargs["candidate_net_file"])
        calls.setdefault("road_connectivity_owner_ids", []).append(kwargs["owner_id"])
        output_net = tmp_path / f"road_connectivity_best_{kwargs['owner_id']}.net.xml"
        run_report = tmp_path / f"road_connectivity_run_{kwargs['owner_id']}.json"
        output_net.write_text("<net/>", encoding="utf-8")
        run_report.write_text('{"status": "pass"}', encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "output_file": str(output_net),
            "run_report_file": str(run_report),
            "sumo_load_status": "pass",
            "owner_road_connectivity_audit": {
                "status": "pass",
                "gate": {
                    "lane_delta_count": 0,
                    "missing_non_turnaround_outgoing_count": 0,
                },
            },
        }

    def fake_review_html(**kwargs):
        calls["workflow_review_net_file"] = kwargs["net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "review.html"),
            "workflow_review_net_file": str(kwargs["net_file"]),
            "workflow_report_file": str(tmp_path / "workflow_report.json"),
            "review_manifest_file": str(tmp_path / "review_manifest.json"),
            "netedit_review_sumocfg_file": str(tmp_path / "review.sumocfg"),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-join",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        netconvert_binary="netconvert-test",
        sumo_binary="sumo-test",
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        },
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=fake_reference_join_aggregation,
        teacher_guided_repair_queue_func=fake_teacher_guided_repair_queue,
        teacher_guided_plain_export_func=fake_teacher_guided_plain_export,
        teacher_guided_repair_run_func=fake_teacher_guided_repair_run,
        road_connectivity_replay_func=fake_road_connectivity_replay,
        review_html_func=fake_review_html,
    )

    visual_detail_net_file = tmp_path / "sumo" / "reference-join_reference_visual_detail.net.xml"
    assert calls["reference_join_candidate_net_file"] == visual_detail_net_file
    assert calls["reference_join_structural_only"] is True
    assert calls["aggregation_candidate_net_file"] == visual_detail_net_file
    assert calls["teacher_guided_candidate_net_file"] == tmp_path / "aggregated.net.xml"
    assert calls["teacher_guided_queue_max_ready_candidates"] == 80
    assert calls["teacher_guided_plain_net_file"] == tmp_path / "aggregated.net.xml"
    assert calls["teacher_guided_plain_netconvert_binary"] == "netconvert-test"
    assert calls["teacher_guided_run_queue_report"]["ready_candidate_count"] == 0
    assert calls["teacher_guided_run_queue_report"]["expanded_scope_candidate_count"] == 1
    assert calls["teacher_guided_run_raw_node_file"] == tmp_path / "plain.nod.xml"
    assert calls["teacher_guided_run_replay_target_internal_subgraph"] is True
    assert calls["teacher_guided_run_netconvert_binary"] == "netconvert-test"
    assert calls["teacher_guided_run_sumo_binary"] == "sumo-test"
    assert calls["teacher_guided_run_max_ready_candidates"] == 80
    assert calls["teacher_guided_run_sequential_accept_passed_variants"] is True
    assert calls["teacher_guided_run_plain_exporter"] is fake_teacher_guided_plain_export
    assert calls["road_connectivity_teacher_net_file"] == reference_net_file
    assert calls["road_connectivity_candidate_net_files"] == [
        tmp_path / "aggregated.net.xml",
        tmp_path / "road_connectivity_best_cluster_a_b.net.xml",
    ]
    assert calls["road_connectivity_owner_ids"] == ["cluster_a_b", "cluster_c_d"]
    assert Path(calls["workflow_review_net_file"]) == tmp_path / "aggregated.net.xml"
    assert calls["aggregation_audit_report"]["matched_case_count"] == 2
    assert report["reference_join_audit_candidate_layer"] == "reference_visual_detail"
    assert report["reference_join_audit_mode"] == "full"
    assert report["reference_join_audit_candidate_net_file"] == str(visual_detail_net_file)
    assert report["reference_join_audit"]["junction_pattern_index"] == [{"junction_id": "cluster_a_b"}]
    assert report["reference_join_junction_teacher_delta_file"] == str(tmp_path / "junction_teacher_delta.json")
    assert report["reference_join_junction_pattern_comparisons_file"] == str(tmp_path / "junction_pattern_comparisons.csv")
    assert report["reference_join_junction_pattern_templates_file"] == str(tmp_path / "junction_pattern_templates.json")
    assert report["reference_join_junction_pattern_comparison_status"] == "fail"
    assert report["reference_join_junction_pattern_mismatch_count"] == 2
    assert report["reference_join_junction_pattern_comparison_sample_count"] == 2
    assert report["reference_join_junction_pattern_mismatch_field_counts"] == {"internal_function_counts": 2}
    assert report["reference_join_structural_signature_status"] == "fail"
    assert report["reference_join_structural_signature_missing_counts"] == {"tls_pattern_count": 1}
    assert report["reference_join_reference_structural_signature_summary"] == {
        "pattern_count": 2,
        "tls_pattern_count": 1,
    }
    assert report["reference_join_candidate_structural_signature_summary"] == {
        "pattern_count": 2,
        "tls_pattern_count": 0,
    }
    assert report["reference_join_network_structural_delta_status"] == "fail"
    assert report["reference_join_network_structural_missing_counts"] == {
        "crossing_edge_count": 620,
        "walkingarea_edge_count": 1648,
    }
    assert report["reference_join_network_structural_extra_counts"] == {
        "tl_logic_count": 35,
        "traffic_light_junction_count": 41,
    }
    assert report["reference_join_network_structural_junction_type_missing_counts"] == {"traffic_light": 1}
    assert report["reference_join_network_structural_junction_type_extra_counts"] == {"priority": 22}
    assert report["reference_join_reference_network_structural_summary"] == {
        "crossing_edge_count": 620,
        "walkingarea_edge_count": 1648,
    }
    assert report["reference_join_candidate_network_structural_summary"] == {
        "crossing_edge_count": 0,
        "walkingarea_edge_count": 0,
    }
    assert report["reference_join_tls_control_review_status"] == "needs_review"
    assert report["reference_join_tls_control_review_queue_count"] == 2
    assert report["reference_join_tls_control_review_category_counts"] == {
        "tls_controller_cardinality_repair": 1,
        "tls_linkindex_phase_repair": 1,
    }
    assert report["reference_join_matched_case_count"] == 2
    assert report["reference_join_unmatched_case_count"] == 1
    assert report["reference_join_aggregation_status"] == "variant_created_for_review"
    assert report["reference_join_aggregation_variant_file"] == str(tmp_path / "aggregated.net.xml")
    assert report["reference_join_aggregation_preservation_status"] == "review"
    assert report["reference_join_aggregation_removed_normal_edge_count"] == 5
    assert report["reference_join_aggregation_removed_normal_edge_type_counts"] == {
        "highway.service": 3,
        "highway.primary": 2,
    }
    assert report["reference_join_aggregation_removed_normal_edge_mode_counts"] == {
        "passenger": 4,
        "bicycle": 1,
    }
    assert report["reference_join_aggregation_lost_shared_connection_count"] == 2
    assert report["reference_join_aggregation_new_dangling_shared_normal_edge_count"] == 1
    assert report["reference_join_aggregation_preservation_audit_file"] == str(tmp_path / "aggregation_preservation.json")
    assert report["teacher_guided_repair_best_variant_file"] == ""
    assert report["teacher_guided_repair_best_expanded_scope_net_file"] == str(tmp_path / "expanded_scope.net.xml")
    assert report["reference_visual_detail_comparison_net_file"] == str(tmp_path / "aggregated.net.xml")
    assert report["teacher_guided_repair_queue_status"] == "pass"
    assert report["teacher_guided_repair_tls_candidate_count"] == 2
    assert report["teacher_guided_repair_tls_category_counts"] == {
        "tls_controller_cardinality_repair": 1,
        "tls_linkindex_phase_repair": 1,
    }
    assert report["teacher_guided_repair_ready_candidate_count"] == 0
    assert report["teacher_guided_repair_expanded_scope_candidate_count"] == 1
    assert report["teacher_guided_repair_expanded_scope_pass_candidate_count"] == 1
    assert report["teacher_guided_repair_exemplar_ready_candidate_count"] == 0
    assert report["teacher_guided_repair_exemplar_movement_signature_count"] == 0
    assert report["teacher_guided_repair_movement_gap_candidate_count"] == 1
    assert report["teacher_guided_repair_max_vehicle_movement_matrix_missing_count"] == 12
    assert report["teacher_guided_repair_missing_movement_plan_count"] == 2
    assert report["teacher_guided_repair_top_movement_gaps"] == [
        {
            "reference_id": "cluster_a_b",
            "junction_id": "",
            "candidate_status": "needs_expanded_rebuild_scope",
            "vehicle_movement_matrix_missing_count": 12,
            "missing_teacher_movement_plan_count": 2,
            "first_missing_teacher_movement": {
                "from_edge_id": "cand_in",
                "to_edge_id": "cand_out",
                "fromLane": "0",
                "toLane": "0",
                "dir": "s",
                "tl": "tlsA",
                "linkIndex": "3",
            },
            "netedit_review_actions": ["rebuild_vehicle_movement_matrix"],
        }
    ]
    assert report["teacher_guided_repair_queue_file"] == str(tmp_path / "teacher_guided_queue.json")
    assert report["teacher_guided_repair_plain_export_status"] == "pass"
    assert report["teacher_guided_repair_raw_node_file"] == str(tmp_path / "plain.nod.xml")
    assert report["teacher_guided_repair_run_status"] == "blocked"
    assert report["teacher_guided_repair_parity_gate_status"] == "blocked"
    assert report["teacher_guided_repair_application_scope"] == "none"
    assert report["teacher_guided_repair_applied_candidate_count"] == 0
    assert report["teacher_guided_repair_unapplied_pass_candidate_count"] == 0
    assert report["teacher_guided_repair_semantic_failure_counts"] == {}
    assert report["teacher_guided_repair_semantic_layer_gate_counts"] == {
        "movement_tls": {"pass": 1, "fail": 0, "failure_count": 0},
        "pedestrian_bike": {"pass": 0, "fail": 1, "failure_count": 2},
    }
    assert report["teacher_guided_repair_approach_integrity_status"] == "blocked"
    assert report["teacher_guided_repair_approach_integrity_failure_counts"] == {}
    assert report["teacher_guided_repair_template_contexts"] == [
        {
            "teacher_pattern_key": "three_way|control=right_before_left",
            "teacher_pattern_family": "three_way",
            "teacher_pattern_template_count": 127,
            "teacher_pattern_template_examples": ["cluster_template_1"],
        }
    ]
    assert report["teacher_guided_repair_run_report_file"] == str(tmp_path / "teacher_guided_run.json")
    assert report["road_connectivity_replay_status"] == "pass"
    assert report["road_connectivity_replay_gate_status"] == "pass"
    assert report["road_connectivity_replay_sumo_load_status"] == "pass"
    assert report["road_connectivity_replay_best_variant_file"] == str(
        tmp_path / "road_connectivity_best_cluster_c_d.net.xml"
    )
    assert report["road_connectivity_replay_run_report_file"]
    assert report["road_connectivity_replay_gate_counts"] == {
        "owner_road_connectivity": {"pass": 2, "fail": 0, "failure_count": 0}
    }
    assert report["workflow_review_net_file"] == str(tmp_path / "aggregated.net.xml")
    assert report["gate_status"]["junction_pattern_index"] == "pass"
    assert report["gate_status"]["road_connectivity_parity"] == "pass"
    assert report["gate_status"]["connection_semantics_parity"] == "pass"
    assert report["gate_status"]["tls_semantics_parity"] == "pass"
    assert report["gate_status"]["internal_junction_parity"] == "blocked"
    assert report["gate_status"]["netedit_connection_mode_review"] == "blocked"
    assert report["gate_status"]["teacher_guided_junction_parity"] == "blocked"


def test_reference_matched_workflow_audits_post_teacher_comparison_net(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-post-teacher_filtered.osm.xml.gz"
    low_vehicle_net = tmp_path / "post_teacher_tls_low_vehicle" / "tls_low_vehicle_control_review.net.xml"
    signal_grouped_net = tmp_path / "post_teacher_tls_signal_grouping" / "tls_signal_grouped.net.xml"
    tls_connection_repaired_net = tmp_path / "post_teacher_tls_connection_repair" / "repaired.net.xml"
    post_repair_movement_composite_net = tmp_path / "post_repair_movement_composite.net.xml"
    hierarchy_type_repaired_net = tmp_path / "reference_hierarchy_type_repair" / "type_repaired.net.xml"
    calls: dict[str, object] = {
        "reference_join_candidate_net_files": [],
        "reference_hierarchy_candidate_net_files": [],
        "reference_hierarchy_type_repair_candidate_net_files": [],
        "teacher_guided_queue_calls": [],
        "teacher_guided_queue_reports": [],
        "teacher_guided_run_calls": [],
        "topology_net_files": [],
    }

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        calls["reference_join_candidate_net_files"].append(kwargs["candidate_net_file"])
        base = {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "full",
            "reference_case_count": 3,
            "matched_case_count": 2,
            "unmatched_case_count": 1,
            "junction_pattern_index": [{"junction_id": "cluster_a_b"}],
            "summary_file": str(tmp_path / "reference_join_audit.json"),
            "cases_file": str(tmp_path / "reference_join_cases.csv"),
            "junction_pattern_comparison_status": "fail",
            "junction_pattern_mismatch_count": 2,
            "junction_pattern_mismatch_field_counts": {"movement_signature_counts": 2},
            "junction_pattern_comparisons": [{"junction_id": "j1", "status": "fail"}],
            "network_structural_delta_status": "fail",
            "network_structural_missing_counts": {"connection_count": 10, "crossing_edge_count": 2},
            "network_structural_extra_counts": {"walkingarea_edge_count": 1},
            "warnings": [],
        }
        if kwargs["prefix"].endswith("_post_teacher_reference_join_audit"):
            return {
                **base,
                "summary_file": str(tmp_path / "post_teacher_reference_join_audit.json"),
                "junction_pattern_mismatch_count": 1,
                "junction_pattern_mismatch_field_counts": {"movement_signature_counts": 1},
                "network_structural_missing_counts": {"connection_count": 4, "crossing_edge_count": 3},
                "network_structural_extra_counts": {
                    "tl_logic_count": 6,
                    "tls_controlled_connection_count": 10,
                    "traffic_light_junction_count": 9,
                    "walkingarea_edge_count": 5,
                },
                "tls_control_review_queue": [
                    {
                        "repair_category": "tls_reality_review",
                        "review_type": "downgrade_low_vehicle_approach_tls",
                        "tl_id": "low_tls",
                        "controlled_connection_count": 10,
                        "controlled_passenger_from_edge_count": 1,
                    }
                ],
            }
        if kwargs["candidate_net_file"] == low_vehicle_net:
            return {
                **base,
                "summary_file": str(tmp_path / "post_teacher_tls_low_vehicle_delta.json"),
                "network_structural_missing_counts": {
                    "connection_count": 4,
                    "crossing_edge_count": 3,
                    "tls_shared_linkindex_group_count": 2,
                    "tls_controlled_connection_count": 6,
                },
                "network_structural_extra_counts": {"walkingarea_edge_count": 5},
            }
        if kwargs["candidate_net_file"] == signal_grouped_net:
            return {
                **base,
                "summary_file": str(tmp_path / "post_teacher_tls_signal_grouping_delta.json"),
                "network_structural_missing_counts": {
                    "connection_count": 4,
                    "crossing_edge_count": 3,
                    "tls_controlled_connection_count": 5,
                },
                "network_structural_extra_counts": {"walkingarea_edge_count": 5},
            }
        if kwargs["candidate_net_file"] == tls_connection_repaired_net:
            return {
                **base,
                "summary_file": str(tmp_path / "post_teacher_tls_connection_repair_delta.json"),
                "junction_pattern_mismatch_count": 2,
                "junction_pattern_mismatch_field_counts": {
                    "control_type": 1,
                    "internal_function_counts": 2,
                    "movement_signature_counts": 2,
                },
                "junction_pattern_comparisons": [
                    {
                        "junction_id": "tls_repair_j1",
                        "status": "fail",
                        "mismatch_fields": ["internal_function_counts", "movement_signature_counts"],
                        "teacher": {
                            "control_type": "traffic_light",
                            "has_tls": True,
                            "internal_function_counts": {
                                "crossing": 2,
                                "internal": 8,
                                "walkingarea": 2,
                            },
                        },
                        "candidate": {
                            "control_type": "traffic_light",
                            "has_tls": True,
                            "internal_function_counts": {
                                "crossing": 0,
                                "internal": 5,
                                "walkingarea": 1,
                            },
                        },
                    },
                    {
                        "junction_id": "tls_repair_j2",
                        "status": "fail",
                        "mismatch_fields": [
                            "control_type",
                            "internal_function_counts",
                            "movement_signature_counts",
                        ],
                        "teacher": {
                            "control_type": "traffic_light",
                            "has_tls": True,
                            "internal_function_counts": {
                                "crossing": 3,
                                "internal": 7,
                                "walkingarea": 2,
                            },
                        },
                        "candidate": {
                            "control_type": "priority",
                            "has_tls": True,
                            "internal_function_counts": {
                                "crossing": 2,
                                "internal": 4,
                                "walkingarea": 1,
                            },
                        },
                    },
                ],
                "network_structural_missing_counts": {"connection_count": 4, "crossing_edge_count": 3},
                "network_structural_extra_counts": {"walkingarea_edge_count": 5},
            }
        if kwargs["candidate_net_file"] == post_repair_movement_composite_net:
            calls["post_repair_movement_equivalent_approach_edge_map"] = kwargs.get("equivalent_approach_edge_map")
            return {
                **base,
                "summary_file": str(tmp_path / "post_repair_movement_delta.json"),
                "junction_pattern_mismatch_count": 0,
                "junction_pattern_mismatch_field_counts": {},
                "junction_pattern_comparisons": [],
                "network_structural_missing_counts": {"connection_count": 2, "crossing_edge_count": 1},
                "network_structural_extra_counts": {"walkingarea_edge_count": 2},
            }
        return base

    def fake_teacher_guided_repair_queue(**kwargs):
        calls["teacher_guided_queue_calls"].append(kwargs)
        if kwargs["prefix"].endswith("_post_teacher_tls_connection_repair_movement_rebuild"):
            report = {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "repair_candidate_count": 2,
                "ready_candidate_count": 1,
                "expanded_scope_candidate_count": 1,
                "queue_file": str(tmp_path / "post_repair_movement_queue.json"),
                "queue_csv_file": str(tmp_path / "post_repair_movement_queue.csv"),
                "repair_candidates": [
                    {
                        "reference_id": "tls_repair_j1",
                        "junction_id": "tls_repair_j1",
                        "candidate_status": "ready_for_teacher_guided_variant",
                        "vehicle_movement_matrix_missing_count": 3,
                        "missing_teacher_movement_plan_count": 2,
                        "netedit_review_actions": ["rebuild_vehicle_movement_matrix"],
                    }
                ],
                "warnings": [],
            }
        else:
            report = {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "repair_candidate_count": 1,
                "ready_candidate_count": 1,
                "expanded_scope_candidate_count": 0,
                "queue_file": str(tmp_path / "teacher_guided_queue.json"),
                "repair_candidates": [],
                "warnings": [],
            }
        calls["teacher_guided_queue_reports"].append(report)
        return report

    def fake_teacher_guided_plain_export(**_kwargs):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "raw_node_file": str(tmp_path / "plain.nod.xml"),
            "raw_edge_file": str(tmp_path / "plain.edg.xml"),
            "raw_connection_file": str(tmp_path / "plain.con.xml"),
            "raw_type_file": str(tmp_path / "plain.typ.xml"),
            "warnings": [],
        }

    def fake_teacher_guided_repair_run(**kwargs):
        calls["teacher_guided_run_calls"].append(kwargs)
        is_post_repair_movement = kwargs["prefix"].endswith("_post_teacher_tls_connection_repair_movement_rebuild")
        composite_net = post_repair_movement_composite_net if is_post_repair_movement else tmp_path / "teacher_guided_composite.net.xml"
        composite_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "parity_gate_status": "pass",
            "attempted_candidate_count": 2,
            "pass_candidate_count": 2,
            "composite_applied_candidate_count": 2,
            "composite_net_file": str(composite_net),
            "variant_reports": [
                {
                    "status": "pass",
                    "parity_gate_status": "pass",
                    "target_internal_replay": {
                        "effective_edge_map": {"teacher_west": "candidate_west"}
                    },
                }
            ],
            "run_report_file": str(tmp_path / "teacher_guided_run.json"),
            "warnings": [],
        }

    def fake_topology_audit(**kwargs):
        calls["topology_net_files"].append(kwargs["net_file"])
        if kwargs["net_file"] == reference_net_file:
            return {
                "status": "blocked",
                "topology_fragmentation_status": "needs_review",
                "suspicious_cluster_count": 10,
                "junction_aggregation_candidate_count": 8,
                "physical_intersection_candidate_count": 4,
                "clusters_file": str(tmp_path / "reference_topology_clusters.csv"),
                "warnings": [],
            }
        if kwargs["net_file"] == post_repair_movement_composite_net:
            return {
                "status": "blocked",
                "topology_fragmentation_status": "needs_review",
                "suspicious_cluster_count": 5,
                "junction_aggregation_candidate_count": 3,
                "physical_intersection_candidate_count": 2,
                "clusters_file": str(tmp_path / "candidate_topology_clusters.csv"),
                "warnings": [],
            }
        if kwargs["net_file"] == hierarchy_type_repaired_net:
            return {
                "status": "blocked",
                "topology_fragmentation_status": "needs_review",
                "suspicious_cluster_count": 4,
                "junction_aggregation_candidate_count": 2,
                "physical_intersection_candidate_count": 1,
                "clusters_file": str(tmp_path / "type_repaired_topology_clusters.csv"),
                "warnings": [],
            }
        return {"status": "pass", "topology_fragmentation_status": "pass", "warnings": []}

    def fake_reference_hierarchy_audit(**kwargs):
        calls["reference_hierarchy_candidate_net_files"].append(kwargs["candidate_net_file"])
        if kwargs["candidate_net_file"] == post_repair_movement_composite_net:
            return {
                "status": "blocked",
                "reference_hierarchy_status": "needs_review",
                "high_hierarchy_issue_count": 2,
                "candidate_cases": [
                    {
                        "candidate_edge_id": "cand_primary",
                        "candidate_edge_name": "Ringstrasse",
                        "candidate_edge_type": "highway.primary",
                        "hierarchy_decision": "type_hierarchy_mismatch",
                        "same_name_match_status": "matched_by_name",
                        "same_name_reference_edge_type": "highway.secondary",
                        "same_name_reference_distance_m": 2.0,
                    }
                ],
                "warnings": [],
            }
        return {
            "status": "pass",
            "reference_hierarchy_status": "pass",
            "high_hierarchy_issue_count": 0,
            "warnings": [],
        }

    def fake_reference_hierarchy_type_repair(**kwargs):
        calls["reference_hierarchy_type_repair_candidate_net_files"].append(kwargs["candidate_net_file"])
        hierarchy_type_repaired_net.parent.mkdir(parents=True, exist_ok=True)
        hierarchy_type_repaired_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "reference_hierarchy_type_repair_status": "variant_created_for_review",
            "reference_hierarchy_type_repair_count": 1,
            "reference_hierarchy_type_repair_variant_file": str(hierarchy_type_repaired_net),
            "reference_hierarchy_type_repair_plan_file": str(tmp_path / "hierarchy_type_repair_plan.json"),
            "reference_hierarchy_type_repair_repairs_file": str(tmp_path / "hierarchy_type_repair_repairs.csv"),
            "warnings": [],
        }

    def fake_low_vehicle_control(**kwargs):
        calls["post_teacher_low_vehicle_source_net_file"] = kwargs["source_net_file"]
        calls["post_teacher_low_vehicle_queue_count"] = len(kwargs["tls_control_review_queue"])
        low_vehicle_net.parent.mkdir(parents=True, exist_ok=True)
        low_vehicle_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_low_vehicle_control_status": "variant_created_for_review",
            "tls_low_vehicle_control_variant_file": str(low_vehicle_net),
            "tls_low_vehicle_control_selected_tllogic_count": 1,
            "tls_low_vehicle_control_removed_connection_count": 10,
            "warnings": [],
        }

    def fake_signal_grouping(**kwargs):
        calls["post_teacher_signal_grouping_source_net_file"] = kwargs["source_net_file"]
        calls["post_teacher_signal_grouping_max_shared_groups"] = kwargs["max_shared_linkindex_groups"]
        signal_grouped_net.parent.mkdir(parents=True, exist_ok=True)
        signal_grouped_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_signal_grouping_status": "variant_created_for_review",
            "tls_signal_grouping_variant_file": str(signal_grouped_net),
            "tls_signal_grouping_merged_group_count": 2,
            "tls_signal_grouping_remapped_connection_count": 4,
            "warnings": [],
        }

    def fake_tls_connection_repair(**kwargs):
        calls["post_teacher_tls_connection_repair_source_net_file"] = kwargs["source_net_file"]
        calls["post_teacher_tls_connection_repair_candidate_net_file"] = kwargs["candidate_net_file"]
        calls["post_teacher_tls_connection_repair_copy_unmapped_tls"] = kwargs["copy_unmapped_tls"]
        tls_connection_repaired_net.parent.mkdir(parents=True, exist_ok=True)
        tls_connection_repaired_net.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "variant_file": str(tls_connection_repaired_net),
            "candidate_tls_controlled_connection_count_before": 10,
            "candidate_tls_controlled_connection_count_after": 15,
            "updated_connection_count": 5,
            "skipped_invalid_mapped_linkindex_connection_count": 0,
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-post-teacher",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {"status": "pass", "tls_candidate_count": 0, "warnings": []},
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "passenger_edge_count": 1},
        topology_audit_func=fake_topology_audit,
        routeability_audit_func=lambda **_kwargs: {"status": "pass", "routeability_status": "pass", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "skipped", "warnings": []},
        sumo_gui_func=lambda _path, **_kwargs: {"status": "blocked", "sumo_gui_status": "skipped", "warnings": []},
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=lambda **_kwargs: {"status": "blocked", "warnings": []},
        reference_hierarchy_audit_func=fake_reference_hierarchy_audit,
        reference_hierarchy_type_repair_func=fake_reference_hierarchy_type_repair,
        teacher_guided_repair_queue_func=fake_teacher_guided_repair_queue,
        teacher_guided_plain_export_func=fake_teacher_guided_plain_export,
        teacher_guided_repair_run_func=fake_teacher_guided_repair_run,
        tls_low_vehicle_control_func=fake_low_vehicle_control,
        tls_signal_grouping_func=fake_signal_grouping,
        tls_connection_repair_func=fake_tls_connection_repair,
        command_runner=lambda command, **_kwargs: {"status": "pass", "returncode": 0, "stdout": "", "stderr": ""},
        review_html_func=lambda **kwargs: {
            "status": "pass",
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "review.html"),
            "workflow_review_net_file": str(kwargs["net_file"]),
            "workflow_report_file": str(tmp_path / "workflow_report.json"),
            "warnings": [],
        },
    )

    assert tmp_path / "teacher_guided_composite.net.xml" in calls["reference_join_candidate_net_files"]
    assert low_vehicle_net in calls["reference_join_candidate_net_files"]
    assert signal_grouped_net in calls["reference_join_candidate_net_files"]
    assert tls_connection_repaired_net in calls["reference_join_candidate_net_files"]
    assert post_repair_movement_composite_net in calls["reference_join_candidate_net_files"]
    assert calls["reference_join_candidate_net_files"].index(tmp_path / "teacher_guided_composite.net.xml") < calls[
        "reference_join_candidate_net_files"
    ].index(low_vehicle_net)
    assert calls["reference_join_candidate_net_files"].index(low_vehicle_net) < calls[
        "reference_join_candidate_net_files"
    ].index(signal_grouped_net)
    assert calls["reference_join_candidate_net_files"].index(signal_grouped_net) < calls[
        "reference_join_candidate_net_files"
    ].index(tls_connection_repaired_net)
    assert calls["post_teacher_low_vehicle_source_net_file"] == tmp_path / "teacher_guided_composite.net.xml"
    assert calls["post_teacher_low_vehicle_queue_count"] == 1
    assert calls["post_teacher_signal_grouping_source_net_file"] == low_vehicle_net
    assert calls["post_teacher_signal_grouping_max_shared_groups"] == 2
    assert calls["post_teacher_tls_connection_repair_source_net_file"] == reference_net_file
    assert calls["post_teacher_tls_connection_repair_candidate_net_file"] == signal_grouped_net
    assert calls["post_teacher_tls_connection_repair_copy_unmapped_tls"] is True
    assert reference_net_file in calls["topology_net_files"]
    assert calls["topology_net_files"][-1] == hierarchy_type_repaired_net
    assert calls["reference_hierarchy_candidate_net_files"][-2:] == [
        post_repair_movement_composite_net,
        hierarchy_type_repaired_net,
    ]
    assert calls["reference_hierarchy_type_repair_candidate_net_files"] == [post_repair_movement_composite_net]
    assert len(calls["teacher_guided_queue_calls"]) == 2
    assert len(calls["teacher_guided_queue_reports"]) == 2
    assert len(calls["teacher_guided_run_calls"]) == 2
    post_repair_queue_call = calls["teacher_guided_queue_calls"][1]
    post_repair_queue_report = calls["teacher_guided_queue_reports"][1]
    assert post_repair_queue_call["candidate_net_file"] == tls_connection_repaired_net
    assert post_repair_queue_call["reference_join_audit_report"]["summary_file"] == str(
        tmp_path / "post_teacher_tls_connection_repair_delta.json"
    )
    post_repair_run_call = calls["teacher_guided_run_calls"][1]
    assert post_repair_run_call["queue_report"] is post_repair_queue_report
    assert post_repair_run_call["prefix"].endswith("_post_teacher_tls_connection_repair_movement_rebuild")
    assert report["reference_visual_detail_comparison_net_file"] == str(hierarchy_type_repaired_net)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "reference_hierarchy_type_repair_promoted"
    )
    assert report["reference_join_post_teacher_audit_status"] == "pass"
    assert report["reference_join_post_teacher_junction_pattern_mismatch_count"] == 0
    assert report["gate_status"]["connection_semantics_parity"] == "pass"
    assert report["gate_status"]["tls_semantics_parity"] == "pass"
    assert report["gate_status"]["internal_junction_parity"] == "pass"
    assert report["gate_status"]["topology_audit"] == "pass"
    assert report["topology_reference_parity_status"] == "pass"
    assert report["topology_reference_parity_reason"] == "candidate_topology_not_more_fragmented_than_reference"
    assert report["suspicious_topology_cluster_count"] == 4
    assert report["reference_topology_suspicious_cluster_count"] == 10
    assert report["reference_topology_junction_aggregation_candidate_count"] == 8
    assert report["reference_hierarchy_type_repair_status"] == "variant_created_for_review"
    assert report["reference_hierarchy_type_repair_count"] == 1
    assert report["reference_hierarchy_type_repair_sumo_load_status"] == "pass"
    assert report["reference_hierarchy_type_repair_audit_status"] == "pass"
    assert report["reference_hierarchy_type_repair_issue_count"] == 0
    assert report["reference_hierarchy_type_repair_promotion_status"] == "pass"
    assert report["gate_status"]["reference_join_aggregation"] == "skipped"
    assert report["gate_status"]["netedit_connection_mode_review"] == "blocked"
    assert calls["post_repair_movement_equivalent_approach_edge_map"] == {
        "teacher_west": "candidate_west"
    }
    assert report["reference_join_post_teacher_junction_pattern_mismatch_field_counts"] == {}
    assert report["reference_join_post_teacher_network_structural_missing_counts"] == {
        "connection_count": 2,
        "crossing_edge_count": 1,
    }
    assert report["reference_join_post_teacher_network_structural_extra_counts"] == {
        "walkingarea_edge_count": 2,
    }
    assert report["post_teacher_tls_low_vehicle_control_status"] == "pass"
    assert report["post_teacher_tls_low_vehicle_control_reference_promotion_status"] == "pass"
    assert report["post_teacher_tls_low_vehicle_control_reference_tls_semantic_delta_score"] == 8
    assert report["post_teacher_tls_signal_grouping_status"] == "pass"
    assert report["post_teacher_tls_signal_grouping_reference_promotion_status"] == "pass"
    assert report["post_teacher_tls_signal_grouping_reference_tls_semantic_delta_score"] == 5
    assert report["post_teacher_tls_connection_repair_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_reference_promotion_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_reference_tls_semantic_delta_score"] == 0
    assert report["post_teacher_tls_connection_repair_junction_pattern_mismatch_count"] == 2
    assert report["post_teacher_tls_connection_repair_junction_pattern_mismatch_field_counts"] == {
        "control_type": 1,
        "internal_function_counts": 2,
        "movement_signature_counts": 2,
    }
    assert report["post_teacher_tls_connection_repair_internal_function_count_deficits"] == {
        "crossing": 3,
        "internal": 6,
        "walkingarea": 2,
    }
    assert report["post_teacher_tls_connection_repair_top_junction_pattern_mismatches"][0] == {
        "junction_id": "tls_repair_j1",
        "mismatch_fields": ["internal_function_counts", "movement_signature_counts"],
        "teacher_control_type": "traffic_light",
        "candidate_control_type": "traffic_light",
        "teacher_has_tls": True,
        "candidate_has_tls": True,
        "internal_function_count_deficits": {
            "crossing": 2,
            "internal": 3,
            "walkingarea": 1,
        },
    }
    assert report["post_teacher_tls_connection_repair_movement_rebuild_queue_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_movement_rebuild_candidate_count"] == 2
    assert report["post_teacher_tls_connection_repair_movement_rebuild_ready_candidate_count"] == 1
    assert report["post_teacher_tls_connection_repair_movement_rebuild_expanded_scope_candidate_count"] == 1
    assert report["post_teacher_tls_connection_repair_movement_rebuild_gap_candidate_count"] == 1
    assert report["post_teacher_tls_connection_repair_movement_rebuild_max_gap_count"] == 3
    assert report["post_teacher_tls_connection_repair_movement_rebuild_queue_file"] == str(
        tmp_path / "post_repair_movement_queue.json"
    )
    assert report["post_teacher_tls_connection_repair_movement_rebuild_run_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_movement_rebuild_parity_gate_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_movement_rebuild_best_variant_file"] == str(
        post_repair_movement_composite_net
    )


def test_reference_matched_workflow_runs_post_repair_movement_rebuild_when_repair_is_not_promoted(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "filtered.osm.xml.gz"
    teacher_guided_net = tmp_path / "teacher_guided.net.xml"
    signal_grouped_net = tmp_path / "signal_grouped.net.xml"
    repaired_net = tmp_path / "repaired.net.xml"
    movement_rebuilt_net = tmp_path / "movement_rebuilt.net.xml"
    calls: dict[str, list[dict[str, object]]] = {"queue": [], "run": []}

    def write_net(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<net/>", encoding="utf-8")
        return path

    def fake_build(**kwargs):
        net_file = write_net(tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml")
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def delta(*, missing: int, mismatch: int = 0, summary: str = "delta.json") -> dict[str, object]:
        comparisons = (
            [
                {
                    "junction_id": "89129103",
                    "status": "fail",
                    "mismatch_fields": ["movement_signature_counts"],
                    "teacher": {"control_type": "traffic_light", "has_tls": True},
                    "candidate": {"control_type": "traffic_light", "has_tls": True},
                }
            ]
            if mismatch
            else []
        )
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "summary_file": str(tmp_path / summary),
            "reference_case_count": 1,
            "matched_case_count": 1,
            "unmatched_case_count": 0,
            "junction_pattern_index": [{"junction_id": "89129103"}],
            "junction_pattern_mismatch_count": mismatch,
            "junction_pattern_mismatch_field_counts": {"movement_signature_counts": mismatch} if mismatch else {},
            "junction_pattern_comparisons": comparisons,
            "network_structural_missing_counts": {"tls_controlled_connection_count": missing},
            "network_structural_extra_counts": {},
            "tls_control_review_queue": [],
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        candidate = kwargs["candidate_net_file"]
        if candidate == teacher_guided_net:
            return {
                **delta(missing=8, summary="post_teacher_delta.json"),
                "tls_control_review_queue": [{"repair_category": "tls_linkindex_phase_repair"}],
            }
        if candidate == signal_grouped_net:
            return delta(missing=4, summary="signal_grouped_delta.json")
        if candidate == repaired_net:
            return delta(missing=10, mismatch=1, summary="repaired_delta.json")
        if candidate == movement_rebuilt_net:
            return delta(missing=2, summary="movement_rebuilt_delta.json")
        return delta(missing=12, mismatch=1, summary="initial_delta.json")

    def fake_teacher_guided_queue(**kwargs):
        calls["queue"].append(kwargs)
        if kwargs["prefix"].endswith("_post_teacher_tls_connection_repair_movement_rebuild"):
            return {
                "status": "pass",
                "repair_candidate_count": 1,
                "ready_candidate_count": 1,
                "expanded_scope_candidate_count": 0,
                "queue_file": str(tmp_path / "movement_queue.json"),
                "repair_candidates": [{"vehicle_movement_matrix_missing_count": 1}],
            }
        return {
            "status": "pass",
            "repair_candidate_count": 1,
            "ready_candidate_count": 1,
            "expanded_scope_candidate_count": 0,
            "queue_file": str(tmp_path / "teacher_queue.json"),
            "repair_candidates": [
                {"reference_id": "89129103", "candidate_status": "ready_for_teacher_guided_variant"}
            ],
        }

    def fake_plain_export(**_kwargs):
        return {
            "status": "pass",
            "raw_node_file": str(tmp_path / "plain.nod.xml"),
            "raw_edge_file": str(tmp_path / "plain.edg.xml"),
            "raw_connection_file": str(tmp_path / "plain.con.xml"),
            "raw_type_file": str(tmp_path / "plain.typ.xml"),
        }

    def fake_repair_run(**kwargs):
        calls["run"].append(kwargs)
        is_movement_rebuild = kwargs["prefix"].endswith("_post_teacher_tls_connection_repair_movement_rebuild")
        net_file = write_net(movement_rebuilt_net if is_movement_rebuild else teacher_guided_net)
        return {
            "status": "pass",
            "parity_gate_status": "pass",
            "composite_applied_candidate_count": 1,
            "composite_net_file": str(net_file),
            "run_report_file": str(tmp_path / "teacher_run.json"),
            "variant_reports": [],
        }

    def fake_signal_grouping(**_kwargs):
        return {
            "status": "pass",
            "tls_signal_grouping_variant_file": str(write_net(signal_grouped_net)),
            "tls_signal_grouping_merged_group_count": 1,
            "tls_signal_grouping_remapped_connection_count": 1,
        }

    def fake_connection_repair(**_kwargs):
        return {
            "status": "pass",
            "variant_file": str(write_net(repaired_net)),
            "candidate_tls_controlled_connection_count_before": 1,
            "candidate_tls_controlled_connection_count_after": 1,
            "updated_connection_count": 1,
            "skipped_invalid_mapped_linkindex_connection_count": 0,
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-post-teacher-blocked",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {"status": "pass", "tls_candidate_count": 0, "warnings": []},
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "passenger_edge_count": 1},
        topology_audit_func=lambda **_kwargs: {"status": "pass", "topology_fragmentation_status": "pass", "warnings": []},
        routeability_audit_func=lambda **_kwargs: {"status": "pass", "routeability_status": "pass", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "skipped", "warnings": []},
        sumo_gui_func=lambda _path, **_kwargs: {"status": "blocked", "sumo_gui_status": "skipped", "warnings": []},
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=lambda **_kwargs: {"status": "blocked", "warnings": []},
        teacher_guided_repair_queue_func=fake_teacher_guided_queue,
        teacher_guided_plain_export_func=fake_plain_export,
        teacher_guided_repair_run_func=fake_repair_run,
        tls_low_vehicle_control_func=lambda **_kwargs: {"status": "skipped"},
        tls_signal_grouping_func=fake_signal_grouping,
        tls_connection_repair_func=fake_connection_repair,
        command_runner=lambda command, **_kwargs: {"status": "pass", "returncode": 0, "stdout": "", "stderr": ""},
        review_html_func=lambda **kwargs: {
            "status": "pass",
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "review.html"),
            "workflow_review_net_file": str(kwargs["net_file"]),
            "workflow_report_file": str(tmp_path / "workflow_report.json"),
            "warnings": [],
        },
    )

    assert report["post_teacher_tls_connection_repair_reference_promotion_status"] == "blocked"
    assert report["post_teacher_tls_connection_repair_reference_promotion_reason"] == (
        "reference_tls_semantic_delta_regressed"
    )
    assert report["post_teacher_tls_connection_repair_movement_rebuild_queue_status"] == "pass"
    assert calls["queue"][-1]["candidate_net_file"] == repaired_net
    assert len(calls["run"]) == 2
    assert calls["run"][-1]["prefix"].endswith("_post_teacher_tls_connection_repair_movement_rebuild")
    assert report["post_teacher_tls_connection_repair_movement_rebuild_run_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_movement_rebuild_parity_gate_status"] == "pass"
    assert report["post_teacher_tls_connection_repair_movement_rebuild_best_variant_file"] == str(
        movement_rebuilt_net
    )
    assert report["reference_visual_detail_comparison_net_file"] == str(movement_rebuilt_net)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "post_teacher_tls_connection_repair_movement_rebuild_promoted"
    )
    assert report["reference_join_post_teacher_junction_pattern_mismatch_count"] == 0
    assert report["gate_status"]["connection_semantics_parity"] == "pass"
    assert report["gate_status"]["tls_semantics_parity"] == "pass"
    assert report["gate_status"]["internal_junction_parity"] == "pass"
    assert report["gate_status"]["reference_join_aggregation"] == "skipped"
    assert report["gate_status"]["netedit_connection_mode_review"] == "blocked"


def test_reference_matched_workflow_promotes_post_teacher_non_controller_junction_demotion(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "filtered.osm.xml.gz"
    teacher_guided_net = tmp_path / "teacher_guided.net.xml"
    demoted_net = tmp_path / "tls_non_controller_junction_demoted.net.xml"
    followup_movement_net = tmp_path / "followup_movement.net.xml"
    followup_demoted_net = tmp_path / "followup_tls_non_controller_junction_demoted.net.xml"
    final_movement_net = tmp_path / "final_movement.net.xml"
    calls: dict[str, object] = {
        "reference_join_candidate_net_files": [],
        "teacher_guided_queue_candidate_net_files": [],
    }

    def write_net(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<net/>", encoding="utf-8")
        return path

    def fake_build(**kwargs):
        net_file = write_net(tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml")
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def delta(
        *,
        extra_tls_junctions: int = 0,
        missing_tls_controlled_connections: int = 0,
        mismatch: int = 0,
        summary: str,
    ) -> dict[str, object]:
        missing_counts = {}
        if missing_tls_controlled_connections:
            missing_counts["tls_controlled_connection_count"] = missing_tls_controlled_connections
        extra_counts = {}
        if extra_tls_junctions:
            extra_counts["traffic_light_junction_count"] = extra_tls_junctions
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "summary_file": str(tmp_path / summary),
            "reference_case_count": 1,
            "matched_case_count": 1,
            "unmatched_case_count": 0,
            "junction_pattern_index": [{"junction_id": "j1"}],
            "junction_pattern_mismatch_count": mismatch,
            "junction_pattern_mismatch_field_counts": {"movement_signature_counts": mismatch} if mismatch else {},
            "junction_pattern_comparisons": [],
            "network_structural_missing_counts": missing_counts,
            "network_structural_extra_counts": extra_counts,
            "tls_control_review_queue": [],
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        candidate = kwargs["candidate_net_file"]
        calls["reference_join_candidate_net_files"].append(candidate)
        if candidate == teacher_guided_net:
            return delta(extra_tls_junctions=5, summary="post_teacher_delta.json")
        if candidate == demoted_net:
            calls["non_controller_equivalent_approach_edge_map"] = kwargs.get("equivalent_approach_edge_map")
            return delta(extra_tls_junctions=1, mismatch=2, summary="non_controller_demotion_delta.json")
        if candidate == followup_demoted_net:
            calls["followup_equivalent_approach_edge_map"] = kwargs.get("equivalent_approach_edge_map")
            return delta(
                missing_tls_controlled_connections=24,
                mismatch=1,
                summary="followup_non_controller_demotion_delta.json",
            )
        if candidate == final_movement_net:
            calls["final_equivalent_approach_edge_map"] = kwargs.get("equivalent_approach_edge_map")
            return delta(
                missing_tls_controlled_connections=24,
                summary="final_movement_delta.json",
            )
        return delta(extra_tls_junctions=6, mismatch=1, summary="initial_delta.json")

    def fake_teacher_guided_queue(**kwargs):
        calls["teacher_guided_queue_candidate_net_files"].append(kwargs["candidate_net_file"])
        is_followup = kwargs["candidate_net_file"] == demoted_net
        is_final = kwargs["candidate_net_file"] == followup_demoted_net
        return {
            "status": "pass",
            "repair_candidate_count": 1,
            "ready_candidate_count": 1,
            "expanded_scope_candidate_count": 0,
            "queue_file": str(
                tmp_path
                / (
                    "final_teacher_queue.json"
                    if is_final
                    else "followup_teacher_queue.json"
                    if is_followup
                    else "teacher_queue.json"
                )
            ),
            "repair_candidates": [{"vehicle_movement_matrix_missing_count": 1}],
        }

    def fake_plain_export(**_kwargs):
        return {
            "status": "pass",
            "raw_node_file": str(tmp_path / "plain.nod.xml"),
            "raw_edge_file": str(tmp_path / "plain.edg.xml"),
            "raw_connection_file": str(tmp_path / "plain.con.xml"),
            "raw_type_file": str(tmp_path / "plain.typ.xml"),
        }

    def fake_repair_run(**kwargs):
        is_followup = kwargs["queue_report"]["queue_file"].endswith("followup_teacher_queue.json")
        is_final = kwargs["queue_report"]["queue_file"].endswith("final_teacher_queue.json")
        return {
            "status": "pass",
            "parity_gate_status": "pass",
            "composite_applied_candidate_count": 1,
            "composite_net_file": str(
                write_net(final_movement_net if is_final else followup_movement_net if is_followup else teacher_guided_net)
            ),
            "run_report_file": str(tmp_path / "teacher_run.json"),
            "variant_reports": [
                {
                    "status": "pass",
                    "parity_gate_status": "pass",
                    "target_internal_replay": {
                        "effective_edge_map": {
                            "teacher_edge": "candidate_edge",
                            **({"followup_teacher_edge": "followup_candidate_edge"} if is_followup else {}),
                            **({"final_teacher_edge": "final_candidate_edge"} if is_final else {}),
                        }
                    },
                }
            ],
        }

    def fake_non_controller_demotion(**kwargs):
        calls.setdefault("non_controller_source_net_files", []).append(kwargs["source_net_file"])
        variant_file = followup_demoted_net if kwargs["source_net_file"] == followup_movement_net else demoted_net
        write_net(variant_file)
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_non_controller_junction_demotion_status": "variant_created_for_review",
            "tls_non_controller_junction_demotion_variant_file": str(variant_file),
            "tls_non_controller_traffic_light_junction_demoted_count": 4,
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-post-teacher-non-controller",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {"status": "pass", "tls_candidate_count": 0, "warnings": []},
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "passenger_edge_count": 1},
        topology_audit_func=lambda **_kwargs: {"status": "pass", "topology_fragmentation_status": "pass", "warnings": []},
        routeability_audit_func=lambda **_kwargs: {"status": "pass", "routeability_status": "pass", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "skipped", "warnings": []},
        sumo_gui_func=lambda _path, **_kwargs: {"status": "blocked", "sumo_gui_status": "skipped", "warnings": []},
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=lambda **_kwargs: {"status": "blocked", "warnings": []},
        teacher_guided_repair_queue_func=fake_teacher_guided_queue,
        teacher_guided_plain_export_func=fake_plain_export,
        teacher_guided_repair_run_func=fake_repair_run,
        tls_low_vehicle_control_func=lambda **_kwargs: {"status": "skipped"},
        tls_signal_grouping_func=lambda **_kwargs: {"status": "skipped"},
        tls_connection_repair_func=lambda **_kwargs: {"status": "skipped"},
        tls_non_controller_junction_demotion_func=fake_non_controller_demotion,
        command_runner=lambda command, **_kwargs: {"status": "pass", "returncode": 0, "stdout": "", "stderr": ""},
        review_html_func=lambda **kwargs: {
            "status": "pass",
            "workflow_review_html_status": "pass",
            "workflow_review_html_file": str(tmp_path / "review.html"),
            "workflow_review_net_file": str(kwargs["net_file"]),
            "workflow_report_file": str(tmp_path / "workflow_report.json"),
            "warnings": [],
        },
    )

    assert calls["non_controller_source_net_files"] == [teacher_guided_net, followup_movement_net]
    assert calls["non_controller_equivalent_approach_edge_map"] == {"teacher_edge": "candidate_edge"}
    assert calls["followup_equivalent_approach_edge_map"] == {
        "teacher_edge": "candidate_edge",
        "followup_teacher_edge": "followup_candidate_edge",
    }
    assert calls["final_equivalent_approach_edge_map"]["final_teacher_edge"] == "final_candidate_edge"
    assert demoted_net in calls["reference_join_candidate_net_files"]
    assert followup_demoted_net in calls["reference_join_candidate_net_files"]
    assert final_movement_net in calls["reference_join_candidate_net_files"]
    assert demoted_net in calls["teacher_guided_queue_candidate_net_files"]
    assert calls["teacher_guided_queue_candidate_net_files"][-1] == followup_demoted_net
    assert report["reference_visual_detail_comparison_net_file"] == str(final_movement_net)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "final_movement_rebuild_promoted_by_reference_delta"
    )
    assert report["post_teacher_tls_non_controller_junction_demotion_status"] == "pass"
    assert report["post_teacher_tls_non_controller_junction_demotion_sumo_load_status"] == "pass"
    assert report["post_teacher_tls_non_controller_junction_demotion_reference_promotion_status"] == "pass"
    assert report["post_teacher_tls_non_controller_junction_demotion_reference_tls_semantic_delta_score"] == 24


def test_reference_matched_workflow_prefers_tls_aggregated_visual_detail_for_reference_join(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-tls_filtered.osm.xml.gz"
    visual_tls_net_file = tmp_path / "tls_aggregation" / "reference_visual_detail_tls.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        net_file = Path(kwargs["net_file"])
        if "reference_visual_detail" in net_file.name:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "tls_candidate_count": 4,
                "tls_cluster_count": 2,
                "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**kwargs):
        assert "reference_visual_detail" in Path(kwargs["net_file"]).name
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_physical_cluster_count": 2,
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "tls_aggregated_traffic_light_junction_count": 2,
            "tls_aggregated_tl_logic_count": 2,
            "tls_aggregated_controlled_connection_count": 7,
            "tls_aggregated_tl_connection_missing_linkindex_count": 1,
            "tls_controlled_connection_preservation_status": "pass",
            "tls_controlled_connection_regression_count": 0,
            "warnings": ["TLS aggregation variant requires Google Maps and Netedit review before adoption"],
        }

    def fake_reference_join_audit(**kwargs):
        calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
        calls["reference_join_structural_only"] = kwargs["structural_only"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "structural_only",
            "reference_case_count": 1,
            "matched_case_count": 1,
            "unmatched_case_count": 0,
            "summary_file": str(tmp_path / "reference_join_audit.json"),
            "cases_file": str(tmp_path / "reference_join_cases.csv"),
            "warnings": [],
        }

    def fail_reference_join_aggregation(**_kwargs):
        raise AssertionError("structural-only audit should not trigger reference join aggregation")

    def fail_teacher_guided_repair_queue(**_kwargs):
        raise AssertionError("structural-only audit should not trigger teacher-guided repair queue")

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-tls",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=fail_reference_join_aggregation,
        teacher_guided_repair_queue_func=fail_teacher_guided_repair_queue,
    )

    assert calls["reference_join_candidate_net_file"] == visual_tls_net_file
    assert calls["reference_join_structural_only"] is True
    assert report["reference_join_audit_mode"] == "structural_only"
    assert report["reference_visual_detail_net_file"] == str(tmp_path / "sumo" / "reference-tls_reference_visual_detail.net.xml")
    assert report["reference_visual_detail_comparison_net_file"] == str(visual_tls_net_file)
    assert report["reference_visual_detail_tls_aggregation_status"] == "variant_created_for_review"
    assert report["reference_visual_detail_tls_aggregated_tl_logic_count"] == 2
    assert report["reference_visual_detail_tls_aggregated_controlled_connection_count"] == 7
    assert report["reference_visual_detail_tls_aggregated_tl_connection_missing_linkindex_count"] == 1
    assert report["reference_visual_detail_tls_controlled_connection_preservation_status"] == "pass"
    assert report["reference_visual_detail_tls_controlled_connection_regression_count"] == 0


def test_reference_matched_structural_only_pattern_mismatch_queues_teacher_guided_repair(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-tls_filtered.osm.xml.gz"
    visual_tls_net_file = tmp_path / "tls_aggregation" / "reference_visual_detail_tls.net.xml"
    calls: dict[str, object] = {"teacher_guided_queue_calls": []}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        if "reference_visual_detail" in Path(kwargs["net_file"]).name:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "tls_candidate_count": 2,
                "tls_cluster_count": 1,
                "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**_kwargs):
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_physical_cluster_count": 1,
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        calls["reference_join_structural_only"] = kwargs["structural_only"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "structural_only",
            "reference_case_count": 0,
            "matched_case_count": 0,
            "unmatched_case_count": 0,
            "summary_file": str(tmp_path / "reference_join_audit.json"),
            "cases_file": str(tmp_path / "reference_join_cases.csv"),
            "junction_pattern_comparison_status": "fail",
            "junction_pattern_mismatch_count": 1,
            "junction_pattern_mismatch_field_counts": {"movement_signature_counts": 1},
            "junction_pattern_comparisons": [
                {
                    "junction_id": "89129103",
                    "status": "fail",
                    "mismatch_fields": ["movement_signature_counts"],
                    "teacher": {"has_tls": True, "control_type": "traffic_light"},
                    "candidate": {"has_tls": True, "control_type": "traffic_light"},
                }
            ],
            "warnings": [],
        }

    def fake_teacher_guided_repair_queue(**kwargs):
        calls["teacher_guided_queue_calls"].append(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "repair_candidate_count": 1,
            "ready_candidate_count": 0,
            "expanded_scope_candidate_count": 0,
            "queue_file": str(tmp_path / "teacher_guided_queue.json"),
            "queue_csv_file": str(tmp_path / "teacher_guided_queue.csv"),
            "repair_candidates": [{"reference_id": "89129103", "candidate_status": "blocked"}],
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-structural-pattern",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger reference join aggregation")
        ),
        teacher_guided_repair_queue_func=fake_teacher_guided_repair_queue,
    )

    assert calls["reference_join_structural_only"] is True
    queue_calls = calls["teacher_guided_queue_calls"]
    assert len(queue_calls) == 1
    assert queue_calls[0]["candidate_net_file"] == visual_tls_net_file
    assert queue_calls[0]["reference_join_audit_report"]["audit_mode"] == "structural_only"
    assert report["teacher_guided_repair_queue_status"] == "pass"
    assert report["teacher_guided_repair_candidate_count"] == 1
    assert report["gate_status"]["teacher_guided_junction_parity"] == "blocked"


def test_reference_matched_workflow_promotes_repaired_tls_variant_when_gates_pass(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-regression_filtered.osm.xml.gz"
    visual_tls_net_file = tmp_path / "tls_aggregation" / "reference_visual_detail_tls.net.xml"
    representatives_file = tmp_path / "tls_aggregation" / "representatives.csv"
    repaired_tls_net_file = tmp_path / "tls_connection_repair" / "repaired.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        if "reference_visual_detail" in Path(kwargs["net_file"]).name:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "tls_candidate_count": 4,
                "tls_cluster_count": 2,
                "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**_kwargs):
        calls["tls_aggregation_guess_signals_dist"] = _kwargs.get("tls_guess_signals_dist_m")
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        representatives_file.write_text(
            "cluster_id,representative_node_id,tls_ids,tls_count,google_maps_url\n"
            "G001,agg_tls,raw_tls;agg_tls,2,https://example.invalid\n",
            encoding="utf-8",
        )
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "tls_aggregation_representatives_file": str(representatives_file),
            "tls_controlled_connection_preservation_status": "fail",
            "tls_controlled_connection_regression_count": 12,
            "warnings": [],
        }

    def fake_reference_join_audit(**kwargs):
        if Path(kwargs["candidate_net_file"]) == visual_tls_net_file:
            calls["rejected_tls_delta_candidate_net_file"] = kwargs["candidate_net_file"]
            calls["rejected_tls_delta_structural_only"] = kwargs["structural_only"]
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 337},
                "network_structural_extra_counts": {"tl_logic_count": 12, "traffic_light_junction_count": 41},
                "network_structural_junction_type_missing_counts": {},
                "network_structural_junction_type_extra_counts": {"traffic_light": 41},
                "summary_file": str(tmp_path / "rejected_tls_delta.json"),
                "warnings": [],
            }
        if Path(kwargs["candidate_net_file"]) == repaired_tls_net_file and "tls_connection_repair_reference_delta" in str(
            kwargs["output_dir"]
        ):
            calls["repair_tls_delta_candidate_net_file"] = kwargs["candidate_net_file"]
            calls["repair_tls_delta_structural_only"] = kwargs["structural_only"]
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 90},
                "network_structural_extra_counts": {"tl_logic_count": 0, "traffic_light_junction_count": 41},
                "network_structural_junction_type_missing_counts": {},
                "network_structural_junction_type_extra_counts": {"traffic_light": 41},
                "summary_file": str(tmp_path / "repair_tls_delta.json"),
                "warnings": [],
            }
        calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "structural_only",
            "reference_case_count": 0,
            "matched_case_count": 0,
            "unmatched_case_count": 0,
            "network_structural_delta_status": "fail",
            "network_structural_missing_counts": {},
            "network_structural_extra_counts": {"tl_logic_count": 35},
            "network_structural_junction_type_missing_counts": {},
            "network_structural_junction_type_extra_counts": {"traffic_light": 186},
            "warnings": [],
        }

    def fake_tls_connection_repair(**kwargs):
        calls["tls_connection_repair_source_net_file"] = kwargs["source_net_file"]
        calls["tls_connection_repair_candidate_net_file"] = kwargs["candidate_net_file"]
        calls["tls_connection_repair_tls_id_map"] = kwargs["tls_id_map"]
        calls["tls_connection_repair_copy_unmapped_tls"] = kwargs["copy_unmapped_tls"]
        calls["tls_connection_repair_require_capacity"] = kwargs["require_target_link_index_capacity"]
        calls["tls_connection_repair_pad_capacity"] = kwargs.get("pad_mapped_tllogic_capacity", False)
        calls["tls_connection_repair_add_green"] = kwargs.get("add_green_phases_for_padded_links", False)
        calls["tls_connection_repair_add_yellow"] = kwargs.get("add_yellow_phases_for_generated_green", False)
        repaired_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        repaired_tls_net_file.write_text("<net/>", encoding="utf-8")
        summary_file = tmp_path / "tls_connection_repair" / "summary.json"
        summary_file.write_text("{}", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "variant_file": str(repaired_tls_net_file),
            "summary_file": str(summary_file),
            "candidate_tls_controlled_connection_count_before": 7,
            "candidate_tls_controlled_connection_count_after": 9,
            "updated_connection_count": 2,
            "skipped_invalid_mapped_linkindex_connection_count": 0,
            "added_green_phase_count": 3,
            "added_yellow_phase_count": 3,
            "warnings": ["diagnostic repair"],
        }

    def fake_command_runner(command, **_kwargs):
        calls["tls_connection_repair_sumo_command"] = command
        return {"status": "pass", "returncode": 0, "stdout": "", "stderr": ""}

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-regression",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        tls_connection_repair_func=fake_tls_connection_repair,
        command_runner=fake_command_runner,
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger aggregation")
        ),
        teacher_guided_repair_queue_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger teacher queue")
        ),
    )

    raw_visual_detail_net_file = tmp_path / "sumo" / "reference-regression_reference_visual_detail.net.xml"
    assert calls["rejected_tls_delta_candidate_net_file"] == visual_tls_net_file
    assert calls["rejected_tls_delta_structural_only"] is True
    assert calls["tls_connection_repair_source_net_file"] == raw_visual_detail_net_file
    assert calls["tls_connection_repair_candidate_net_file"] == visual_tls_net_file
    assert calls["tls_connection_repair_tls_id_map"] == {"raw_tls": "agg_tls", "agg_tls": "agg_tls"}
    assert calls["tls_connection_repair_copy_unmapped_tls"] is False
    assert calls["tls_connection_repair_require_capacity"] is True
    assert calls["tls_connection_repair_pad_capacity"] is True
    assert calls["tls_connection_repair_add_green"] is True
    assert calls["tls_connection_repair_add_yellow"] is True
    assert calls["repair_tls_delta_candidate_net_file"] == repaired_tls_net_file
    assert calls["repair_tls_delta_structural_only"] is True
    assert calls["reference_join_candidate_net_file"] == repaired_tls_net_file
    assert calls["tls_connection_repair_sumo_command"][0] == "sumo"
    assert calls["tls_connection_repair_sumo_command"][1:3] == ["-n", "sumo_load_candidate.net.xml"]
    assert report["reference_visual_detail_comparison_net_file"] == str(repaired_tls_net_file)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "tls_connection_repair_promoted_after_sumo_load_and_reference_delta"
    )
    assert report["reference_visual_detail_tls_controlled_connection_preservation_status"] == "fail"
    assert report["reference_visual_detail_tls_controlled_connection_regression_count"] == 12
    assert report["reference_join_tls_semantic_delta_score"] == 35
    assert report["reference_visual_detail_tls_aggregation_reference_delta_status"] == "fail"
    assert report["reference_visual_detail_tls_aggregation_reference_tls_semantic_delta_score"] == 390
    assert report["reference_visual_detail_tls_aggregation_reference_delta_missing_counts"] == {
        "tls_controlled_connection_count": 337
    }
    assert report["reference_visual_detail_tls_aggregation_reference_delta_extra_counts"] == {
        "tl_logic_count": 12,
        "traffic_light_junction_count": 41,
    }
    assert report["reference_visual_detail_tls_connection_repair_status"] == "pass"
    assert report["reference_visual_detail_tls_connection_repair_controlled_connection_count_before"] == 7
    assert report["reference_visual_detail_tls_connection_repair_controlled_connection_count_after"] == 9
    assert report["reference_visual_detail_tls_connection_repair_updated_connection_count"] == 2
    assert report["reference_visual_detail_tls_connection_repair_skipped_invalid_mapped_linkindex_count"] == 0
    assert report["reference_visual_detail_tls_connection_repair_promotion_status"] == "pass"
    assert report["reference_visual_detail_tls_connection_repair_sumo_load_status"] == "pass"
    assert report["reference_visual_detail_tls_connection_repair_reference_tls_semantic_delta_score"] == 131
    assert report["reference_visual_detail_tls_connection_repair_reference_delta_missing_counts"] == {
        "tls_controlled_connection_count": 90
    }


def test_reference_matched_workflow_reviews_best_tls_aggregation_when_repair_is_unavailable(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-review_filtered.osm.xml.gz"
    visual_tls_net_file = tmp_path / "reference_visual_detail_tls_aggregation" / "tls_aggregated.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        if "reference_visual_detail" not in str(kwargs["net_file"]):
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "tls_candidate_count": 0,
                "tls_cluster_count": 0,
                "clusters_file": str(tmp_path / "tls_clusters.csv"),
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 8,
            "tls_cluster_count": 2,
            "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**_kwargs):
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "tls_aggregation_representatives_file": str(tmp_path / "missing_representatives.csv"),
            "tls_controlled_connection_preservation_status": "fail",
            "tls_controlled_connection_regression_count": 12,
            "warnings": ["review variant"],
        }

    def fake_reference_join_audit(**kwargs):
        candidate_net_file = Path(kwargs["candidate_net_file"])
        calls["last_reference_join_candidate_net_file"] = candidate_net_file
        if candidate_net_file == visual_tls_net_file:
            calls["aggregation_delta_candidate_net_file"] = candidate_net_file
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 50},
                "network_structural_extra_counts": {"tl_logic_count": 5},
                "tls_control_review_queue": [],
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "structural_only",
            "network_structural_delta_status": "fail",
            "network_structural_missing_counts": {},
            "network_structural_extra_counts": {"tl_logic_count": 1},
            "tls_control_review_queue": [],
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-review",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        tls_connection_repair_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("missing representatives should skip TLS connection repair")
        ),
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        run_topology_audit_after_build=False,
        run_routeability_audit_after_build=False,
        run_reference_hierarchy_audit_after_build=False,
        run_reference_scope_audit_after_build=False,
        run_reference_join_aggregation_after_build=False,
        launch_netedit_after_build=False,
        launch_sumo_gui_after_build=False,
        reference_join_audit_func=fake_reference_join_audit,
    )

    assert calls["aggregation_delta_candidate_net_file"] == visual_tls_net_file
    assert calls["last_reference_join_candidate_net_file"] == visual_tls_net_file
    assert report["reference_visual_detail_comparison_net_file"] == str(visual_tls_net_file)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "tls_aggregation_rejected_controlled_connection_regression"
    )


def test_reference_matched_workflow_promotes_tls_aggregation_when_reference_delta_improves(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-delta_filtered.osm.xml.gz"
    best_visual_tls_net_file = tmp_path / "reference_visual_detail_tls_aggregation_guess20" / "tls_aggregated.net.xml"
    low_vehicle_net_file = tmp_path / "reference_visual_detail_tls_low_vehicle_control" / "tls_low_vehicle_control_review.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        if "reference_visual_detail" in Path(kwargs["net_file"]).name:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "tls_candidate_count": 4,
                "tls_cluster_count": 2,
                "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**_kwargs):
        calls.setdefault("tls_aggregation_guess_signal_dists", []).append(_kwargs.get("tls_guess_signals_dist_m"))
        visual_tls_net_file = Path(_kwargs["output_dir"]) / "tls_aggregated.net.xml"
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "tls_controlled_connection_preservation_status": "fail",
            "tls_controlled_connection_regression_count": 12,
            "warnings": [],
        }

    raw_visual_detail_net_file = tmp_path / "sumo" / "reference-delta_reference_visual_detail.net.xml"

    def fake_reference_join_audit(**kwargs):
        candidate_net_file = Path(kwargs["candidate_net_file"])
        output_dir = str(kwargs["output_dir"])
        if "tls_aggregation_reference_delta" in output_dir:
            calls.setdefault("aggregation_delta_candidate_net_files", []).append(kwargs["candidate_net_file"])
            score_counts = (
                {"traffic_light_junction_count": 30, "tls_controlled_connection_count": 77}
                if "guess20" in str(candidate_net_file.parent)
                else {"traffic_light_junction_count": 300}
            )
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 90},
                "network_structural_extra_counts": score_counts,
                "network_structural_junction_type_missing_counts": {},
                "network_structural_junction_type_extra_counts": {"traffic_light": score_counts["traffic_light_junction_count"]},
                "tls_control_review_queue": [
                    {
                        "repair_category": "tls_reality_review",
                        "review_type": "downgrade_low_vehicle_approach_tls",
                        "tl_id": "lowTls",
                        "controlled_connection_count": 77,
                        "controlled_passenger_from_edge_count": 1,
                    }
                ]
                if "guess20" in str(candidate_net_file.parent)
                else [],
                "summary_file": str(tmp_path / "aggregation_delta.json"),
                "warnings": [],
            }
        if candidate_net_file == raw_visual_detail_net_file and "raw_reference_delta" in output_dir:
            calls["raw_delta_candidate_net_file"] = kwargs["candidate_net_file"]
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_shared_linkindex_group_count": 40},
                "network_structural_extra_counts": {"traffic_light_junction_count": 354},
                "network_structural_junction_type_missing_counts": {},
                "network_structural_junction_type_extra_counts": {"traffic_light": 354},
                "summary_file": str(tmp_path / "raw_delta.json"),
                "warnings": [],
            }
        if candidate_net_file == best_visual_tls_net_file:
            calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 90},
                "network_structural_extra_counts": {"traffic_light_junction_count": 30},
                "network_structural_junction_type_missing_counts": {},
                "network_structural_junction_type_extra_counts": {"traffic_light": 30},
                "warnings": [],
            }
        if candidate_net_file == low_vehicle_net_file:
            calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_delta_status": "fail",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 90},
                "network_structural_extra_counts": {"traffic_light_junction_count": 5},
                "network_structural_junction_type_missing_counts": {},
                "network_structural_junction_type_extra_counts": {"traffic_light": 5},
                "summary_file": str(tmp_path / "low_vehicle_delta.json"),
                "warnings": [],
            }
        calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "structural_only",
            "network_structural_delta_status": "fail",
            "network_structural_missing_counts": {"tls_controlled_connection_count": 165},
            "network_structural_extra_counts": {"traffic_light_junction_count": 46},
            "network_structural_junction_type_missing_counts": {},
            "network_structural_junction_type_extra_counts": {"traffic_light": 46},
            "warnings": [],
        }

    def fake_low_vehicle_control(**kwargs):
        calls["low_vehicle_source_net_file"] = kwargs["source_net_file"]
        calls.setdefault("low_vehicle_budgets", []).append(kwargs["max_removed_controlled_connections"])
        calls.setdefault("low_vehicle_max_selected_counts", []).append(kwargs["max_selected_tllogic_count"])
        calls.setdefault("low_vehicle_queue_counts", []).append(len(kwargs["tls_control_review_queue"]))
        low_vehicle_net_file.parent.mkdir(parents=True, exist_ok=True)
        low_vehicle_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_low_vehicle_control_status": "variant_created_for_review",
            "tls_low_vehicle_control_variant_file": str(low_vehicle_net_file),
            "tls_low_vehicle_control_selected_tllogic_count": 1,
            "tls_low_vehicle_control_removed_connection_count": 77,
            "warnings": [],
        }

    def fake_command_runner(command, **_kwargs):
        calls["low_vehicle_sumo_command"] = command
        return {"status": "pass", "returncode": 0, "stdout": "", "stderr": ""}

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-delta",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        tls_low_vehicle_control_func=fake_low_vehicle_control,
        command_runner=fake_command_runner,
        tls_connection_repair_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("reference-delta promotion should skip TLS repair")
        ),
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger aggregation")
        ),
        teacher_guided_repair_queue_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger teacher queue")
        ),
    )

    assert calls["tls_aggregation_guess_signal_dists"] == [35.0, 20.0, None]
    assert best_visual_tls_net_file in [Path(str(path)) for path in calls["aggregation_delta_candidate_net_files"]]
    assert calls["raw_delta_candidate_net_file"] == raw_visual_detail_net_file
    assert calls["low_vehicle_source_net_file"] == best_visual_tls_net_file
    assert 77 in calls["low_vehicle_budgets"]
    assert calls["low_vehicle_queue_counts"] == [1, 1]
    assert calls["reference_join_candidate_net_file"] == low_vehicle_net_file
    assert report["reference_visual_detail_comparison_net_file"] == str(low_vehicle_net_file)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "tls_low_vehicle_control_promoted_by_reference_delta"
    )
    assert report["reference_visual_detail_tls_aggregation_reference_promotion_status"] == "pass"
    assert report["reference_visual_detail_tls_aggregation_reference_tls_semantic_delta_score"] == 197
    assert report["reference_visual_detail_tls_low_vehicle_control_reference_promotion_status"] == "pass"
    assert report["reference_visual_detail_tls_low_vehicle_control_reference_tls_semantic_delta_score"] == 95
    assert report["reference_visual_detail_tls_low_vehicle_control_sumo_load_status"] == "pass"
    assert report["reference_visual_detail_raw_reference_tls_semantic_delta_score"] == 394
    assert report["reference_join_tls_semantic_delta_score"] == 95
    assert report["reference_visual_detail_tls_aggregation_candidate_count"] == 3


def test_reference_matched_workflow_promotes_signal_grouping_when_reference_delta_improves(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-signal_filtered.osm.xml.gz"
    visual_tls_net_file = tmp_path / "tls_aggregation" / "reference_visual_detail_tls.net.xml"
    signal_grouped_net_file = tmp_path / "tls_signal_grouping" / "signal_grouped.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 2,
            "tls_cluster_count": 1 if "reference_visual_detail" in Path(kwargs["net_file"]).name else 0,
            "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**_kwargs):
        calls.setdefault("tls_aggregation_guess_signal_dists", []).append(_kwargs.get("tls_guess_signals_dist_m"))
        if _kwargs.get("tls_guess_signals_dist_m") != 35.0:
            return {
                "status": "fail",
                "claim_status": "construction-invalid",
                "tls_aggregation_status": "failed",
                "tls_aggregation_variant_file": "",
                "warnings": [],
            }
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "tls_controlled_connection_preservation_status": "fail",
            "warnings": [],
        }

    def fake_signal_grouping(**kwargs):
        calls["signal_grouping_max_shared_linkindex_groups"] = kwargs["max_shared_linkindex_groups"]
        signal_grouped_net_file.parent.mkdir(parents=True, exist_ok=True)
        signal_grouped_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_signal_grouping_status": "variant_created_for_review",
            "tls_signal_grouping_variant_file": str(signal_grouped_net_file),
            "tls_signal_grouping_merged_group_count": kwargs["max_shared_linkindex_groups"],
            "warnings": [],
        }

    def fake_command_runner(command, **_kwargs):
        calls["signal_grouping_sumo_command"] = command
        return {"status": "pass", "returncode": 0, "stdout": "", "stderr": ""}

    raw_visual_detail_net_file = tmp_path / "sumo" / "reference-signal_reference_visual_detail.net.xml"

    def fake_reference_join_audit(**kwargs):
        candidate_net_file = Path(kwargs["candidate_net_file"])
        output_dir = str(kwargs["output_dir"])
        if candidate_net_file == visual_tls_net_file and "tls_aggregation_reference_delta" in output_dir:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_missing_counts": {
                    "tls_controlled_connection_count": 160,
                    "tls_shared_linkindex_group_count": 40,
                },
                "network_structural_extra_counts": {"traffic_light_junction_count": 46, "tl_logic_count": 41},
                "summary_file": str(tmp_path / "aggregation_delta.json"),
                "warnings": [],
            }
        if candidate_net_file == raw_visual_detail_net_file and "raw_reference_delta" in output_dir:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_missing_counts": {"tls_shared_linkindex_group_count": 40},
                "network_structural_extra_counts": {"traffic_light_junction_count": 354},
                "summary_file": str(tmp_path / "raw_delta.json"),
                "warnings": [],
            }
        if candidate_net_file == signal_grouped_net_file and "tls_signal_grouping_reference_delta" in output_dir:
            calls["signal_grouping_delta_candidate_net_file"] = kwargs["candidate_net_file"]
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "audit_mode": "structural_only",
                "network_structural_missing_counts": {"tls_controlled_connection_count": 160},
                "network_structural_extra_counts": {
                    "traffic_light_junction_count": 46,
                    "tl_logic_count": 41,
                    "multi_junction_tl_logic_count": 5,
                    "tls_sparse_linkindex_tl_logic_count": 3,
                },
                "summary_file": str(tmp_path / "signal_grouping_delta.json"),
                "warnings": [],
            }
        calls["reference_join_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "audit_mode": "structural_only",
            "network_structural_missing_counts": {"tls_controlled_connection_count": 160},
            "network_structural_extra_counts": {
                "traffic_light_junction_count": 46,
                "tl_logic_count": 41,
                "multi_junction_tl_logic_count": 5,
                "tls_sparse_linkindex_tl_logic_count": 3,
            },
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-signal",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        tls_signal_grouping_func=fake_signal_grouping,
        command_runner=fake_command_runner,
        tls_connection_repair_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("signal grouping promotion should skip TLS repair")
        ),
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "warnings": []},
        topology_audit_func=lambda **_kwargs: {"status": "pass", "topology_fragmentation_status": "pass", "warnings": []},
        routeability_audit_func=lambda **_kwargs: {"status": "pass", "routeability_status": "pass", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "skipped", "warnings": []},
        sumo_gui_func=lambda _path, **_kwargs: {"status": "blocked", "sumo_gui_status": "skipped", "warnings": []},
        reference_join_audit_func=fake_reference_join_audit,
        reference_join_aggregation_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger aggregation")
        ),
        teacher_guided_repair_queue_func=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("structural-only audit should not trigger teacher queue")
        ),
    )

    assert calls["signal_grouping_max_shared_linkindex_groups"] == 40
    assert calls["tls_aggregation_guess_signal_dists"] == [35.0, 20.0, None]
    assert calls["signal_grouping_sumo_command"][0] == "sumo"
    assert calls["signal_grouping_delta_candidate_net_file"] == signal_grouped_net_file
    assert calls["reference_join_candidate_net_file"] == signal_grouped_net_file
    assert report["reference_visual_detail_comparison_net_file"] == str(signal_grouped_net_file)
    assert report["reference_visual_detail_comparison_selection_reason"] == (
        "tls_signal_grouping_promoted_by_reference_delta"
    )
    assert report["reference_visual_detail_tls_signal_grouping_reference_promotion_status"] == "pass"
    assert report["reference_visual_detail_tls_signal_grouping_sumo_load_status"] == "pass"
    assert report["reference_visual_detail_tls_signal_grouping_reference_tls_semantic_delta_score"] == 255
    assert report["reference_join_tls_semantic_delta_score"] == 255


def test_reference_matched_workflow_runs_reference_scope_audit_without_default_pruning_variant(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-scope_filtered.osm.xml.gz"
    visual_tls_net_file = tmp_path / "tls_aggregation" / "reference_visual_detail_tls.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        net_file = Path(kwargs["net_file"])
        if "reference_visual_detail" in net_file.name:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "tls_candidate_count": 2,
                "tls_cluster_count": 1,
                "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**kwargs):
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "warnings": [],
        }

    def fake_reference_scope_audit(**kwargs):
        calls["scope_reference_net_file"] = kwargs["reference_net_file"]
        calls["scope_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "blocked",
            "claim_status": "blocked",
            "reference_scope_status": "needs_pruning_review",
            "prune_candidate_count": 4,
            "report_file": str(tmp_path / "scope_audit.json"),
            "prune_candidates_file": str(tmp_path / "scope_candidates.csv"),
            "warnings": ["reference scope audit found 4 prune candidate edge(s)"],
        }

    def fake_scope_pruning(**kwargs):
        raise AssertionError("scope pruning variant should require an explicit workflow opt-in")

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-scope",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_join_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "reference_case_count": 0,
            "matched_case_count": 0,
            "unmatched_case_count": 0,
            "warnings": [],
        },
        reference_join_aggregation_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_aggregation_status": "not_needed",
            "junction_aggregation_candidate_count": 0,
            "warnings": [],
        },
        reference_scope_audit_func=fake_reference_scope_audit,
        scope_pruning_func=fake_scope_pruning,
    )

    assert calls["scope_reference_net_file"] == reference_net_file
    assert calls["scope_candidate_net_file"] == visual_tls_net_file
    assert report["reference_scope_status"] == "needs_pruning_review"
    assert report["reference_scope_prune_candidate_count"] == 4
    assert report["reference_scope_pruning_status"] == "skipped"
    assert report["reference_scope_pruning_variant_file"] == ""
    assert report["gate_status"]["reference_scope_audit"] == "blocked"
    assert report["gate_status"]["reference_scope_pruning"] == "skipped"


def test_reference_matched_workflow_runs_reference_hierarchy_audit_on_visual_detail_layer(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    filtered_osm = tmp_path / "osm" / "reference-hierarchy_filtered.osm.xml.gz"
    visual_tls_net_file = tmp_path / "tls_aggregation" / "reference_visual_detail_tls.net.xml"
    calls: dict[str, object] = {}

    def fake_build(**kwargs):
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": sorted(kwargs["allowed_highways"]),
            "warnings": [],
        }

    def fake_tls(**kwargs):
        net_file = Path(kwargs["net_file"])
        if "reference_visual_detail" in net_file.name:
            return {
                "status": "pass",
                "claim_status": "diagnostic-demo",
                "tls_candidate_count": 2,
                "tls_cluster_count": 1,
                "clusters_file": str(tmp_path / "visual_tls_clusters.csv"),
                "warnings": [],
            }
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        }

    def fake_tls_aggregation(**_kwargs):
        visual_tls_net_file.parent.mkdir(parents=True, exist_ok=True)
        visual_tls_net_file.write_text("<net/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "blocked",
            "tls_aggregation_status": "variant_created_for_review",
            "tls_aggregation_variant_file": str(visual_tls_net_file),
            "warnings": [],
        }

    def fake_reference_hierarchy_audit(**kwargs):
        calls["hierarchy_reference_net_file"] = kwargs["reference_net_file"]
        calls["hierarchy_candidate_net_file"] = kwargs["candidate_net_file"]
        return {
            "status": "blocked",
            "claim_status": "blocked",
            "reference_hierarchy_status": "needs_review",
            "high_hierarchy_issue_count": 5,
            "decision_counts": {"matched_but_oversplit": 3, "out_of_reference_scope": 2},
            "corridor_match_basis_counts": {"same_name": 2, "same_type_distance": 3},
            "same_name_match_status_counts": {"matched_by_name": 4, "no_same_name_reference": 1},
            "cases_file": str(tmp_path / "hierarchy_cases.csv"),
            "type_comparison_file": str(tmp_path / "hierarchy_types.csv"),
            "summary_file": str(tmp_path / "hierarchy_summary.json"),
            "warnings": ["reference hierarchy audit found 5 high-road review case(s)"],
        }

    report = run_osm_cleanup_workflow(
        bbox="11.413800,48.755391,11.433800,48.775391",
        output_dir=tmp_path,
        prefix="reference-hierarchy",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        build_func=fake_build,
        tls_audit_func=fake_tls,
        tls_aggregation_func=fake_tls_aggregation,
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 100,
            "passenger_component_count": 1,
            "largest_component_edge_count": 100,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        reference_scope_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "reference_scope_status": "pass",
            "prune_candidate_count": 0,
            "warnings": [],
        },
        reference_join_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "reference_case_count": 0,
            "matched_case_count": 0,
            "unmatched_case_count": 0,
            "warnings": [],
        },
        reference_join_aggregation_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "junction_aggregation_status": "not_needed",
            "junction_aggregation_candidate_count": 0,
            "warnings": [],
        },
        reference_hierarchy_audit_func=fake_reference_hierarchy_audit,
    )

    assert calls["hierarchy_reference_net_file"] == reference_net_file
    assert calls["hierarchy_candidate_net_file"] == visual_tls_net_file
    assert report["reference_hierarchy_status"] == "needs_review"
    assert report["reference_hierarchy_issue_count"] == 5
    assert report["reference_hierarchy_audit_candidate_layer"] == "reference_visual_detail"
    assert report["reference_hierarchy_audit_candidate_net_file"] == str(visual_tls_net_file)
    assert report["reference_hierarchy_decision_counts"] == {
        "matched_but_oversplit": 3,
        "out_of_reference_scope": 2,
    }
    assert report["reference_hierarchy_corridor_match_basis_counts"] == {
        "same_name": 2,
        "same_type_distance": 3,
    }
    assert report["reference_hierarchy_same_name_match_status_counts"] == {
        "matched_by_name": 4,
        "no_same_name_reference": 1,
    }
    assert report["reference_hierarchy_cases_file"] == str(tmp_path / "hierarchy_cases.csv")
    assert report["gate_status"]["reference_hierarchy_audit"] == "blocked"


def test_reference_matched_workflow_derives_bbox_from_reference_geometry(tmp_path: Path) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    derived_bbox = "11.413800,48.755391,11.433800,48.775391"
    build_calls: list[dict[str, object]] = []

    def fake_build(**kwargs):
        build_calls.append({"bbox": kwargs["bbox"], "prefix": kwargs["prefix"]})
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        source_osm_file = tmp_path / "osm" / f"{kwargs['prefix']}.osm.xml.gz"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        source_osm_file.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text(
            """<net>
    <edge id="primary_a" type="highway.primary">
        <lane id="primary_a_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
</net>""",
            encoding="utf-8",
        )
        source_osm_file.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(source_osm_file),
            "source_osm_file": str(source_osm_file),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        output_dir=tmp_path,
        prefix="reference-derived-bbox",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        reference_bbox_func=lambda _path: {
            "status": "pass",
            "reference_bbox_status": "derived_from_reference_geometry",
            "reference_bbox": derived_bbox,
            "reference_bbox_source": "junction_geometry",
            "reference_bbox_padding_m": 75.0,
            "warnings": [],
        },
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "warnings": [],
        },
        connectivity_func=lambda _path: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 1,
            "passenger_component_count": 1,
            "largest_component_edge_count": 1,
            "warnings": [],
        },
        topology_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "topology_fragmentation_status": "pass",
            "warnings": [],
        },
        routeability_audit_func=lambda **_kwargs: {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "routeability_status": "pass",
            "warnings": [],
        },
        netedit_func=lambda _path: {
            "status": "blocked",
            "netedit_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
        sumo_gui_func=lambda _path, **_kwargs: {
            "status": "blocked",
            "sumo_gui_status": "skipped",
            "claim_status": "diagnostic-demo",
            "warnings": [],
        },
    )

    assert report["status"] == "pass"
    assert report["area_input"] == derived_bbox
    assert report["candidate_bbox"] == derived_bbox
    assert report["reference_bbox_status"] == "derived_from_reference_geometry"
    assert report["reference_bbox"] == derived_bbox
    assert report["reference_bbox_source"] == "junction_geometry"
    assert report["reference_bbox_padding_m"] == 75.0
    assert build_calls[0]["bbox"] == derived_bbox


def test_reference_matched_workflow_prefers_reference_bbox_over_place_resolution(
    tmp_path: Path,
) -> None:
    reference_net_file = tmp_path / "reference.net.xml"
    _write_reference_net(reference_net_file)
    derived_bbox = "11.4062777,48.7483625,11.4382247,48.7803406"
    build_calls: list[dict[str, object]] = []

    def fake_build(**kwargs):
        build_calls.append({"bbox": kwargs["bbox"]})
        current_net_file = tmp_path / "sumo" / f"{kwargs['prefix']}.net.xml"
        source_osm_file = tmp_path / "osm" / f"{kwargs['prefix']}.osm.xml.gz"
        current_net_file.parent.mkdir(parents=True, exist_ok=True)
        source_osm_file.parent.mkdir(parents=True, exist_ok=True)
        current_net_file.write_text(
            """<net>
    <edge id="primary_a" type="highway.primary">
        <lane id="primary_a_0" index="0" allow="passenger" speed="13.9" length="25.0"/>
    </edge>
</net>""",
            encoding="utf-8",
        )
        source_osm_file.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(current_net_file),
            "filtered_osm_file": str(source_osm_file),
            "source_osm_file": str(source_osm_file),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        place_name="Ingolstadt city center",
        output_dir=tmp_path,
        prefix="reference-place-derived-bbox",
        network_profile="reference_matched",
        reference_net_file=reference_net_file,
        place_resolver=lambda _place: (_ for _ in ()).throw(AssertionError("place resolver should not run")),
        reference_bbox_func=lambda _path: {
            "status": "pass",
            "reference_bbox_status": "derived_from_reference_geometry",
            "reference_bbox": derived_bbox,
            "reference_bbox_source": "junction_geometry",
            "reference_bbox_padding_m": 75.0,
            "warnings": [],
        },
        build_func=fake_build,
        tls_audit_func=lambda **_kwargs: {"status": "pass", "tls_candidate_count": 0, "warnings": []},
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "warnings": []},
        topology_audit_func=lambda **_kwargs: {"status": "pass", "topology_fragmentation_status": "pass", "warnings": []},
        routeability_audit_func=lambda **_kwargs: {"status": "pass", "routeability_status": "pass", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "skipped", "warnings": []},
        sumo_gui_func=lambda _path, **_kwargs: {"status": "blocked", "sumo_gui_status": "skipped", "warnings": []},
    )

    assert report["status"] == "pass"
    assert report["area_input"] == "Ingolstadt city center"
    assert report["candidate_bbox"] == derived_bbox
    assert report["reference_bbox_status"] == "derived_from_reference_geometry"
    assert build_calls[0]["bbox"] == derived_bbox
