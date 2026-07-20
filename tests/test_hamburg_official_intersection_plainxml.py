from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from torii_sumo.core.hamburg_official_intersection_plainxml import (
    HamburgOfficialIntersectionPlainXmlError,
    _validate_single_core_layout_profile,
    materialize_hamburg_official_intersection_plainxml,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = (
    REPO_ROOT
    / "artifacts"
    / "hamburg_sandtorkai_twin_20260719"
    / "official_first_named_corridor_v1"
    / "official"
    / "signals"
    / "assets"
)


def _inputs(node_id: str) -> dict[str, Path]:
    return {
        "map_xml_file": ASSET_DIR / f"{node_id}_map_xml.xml",
        "map_kml_file": ASSET_DIR / f"{node_id}_map_kml.kml",
        "ocit_c_file": ASSET_DIR / f"{node_id}_ocit_xml.xml",
    }


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _classification(
    tmp_path: Path,
    node_id: str,
    *,
    physical_arrangement: str = "single_core",
    control_domain: str = "one_owner_one_controller",
    core_count: int | None = 1,
    owner_count: int = 1,
) -> tuple[Path, str, str]:
    classification_id = f"intersection-archetype-{node_id}-test"
    path = tmp_path / f"{node_id}.classification.json"
    path.write_text(
        json.dumps(
            {
                "schema_id": "torii.composable-intersection-archetype/v2",
                "junction_id": node_id,
                "classification_id": classification_id,
                "status": "classified",
                "classification": {
                    "physical_arrangement": physical_arrangement,
                    "control_domain": control_domain,
                },
                "counts": {
                    "physical_conflict_core_count": core_count,
                    "owner_count_after_rebuild_candidate": owner_count,
                    "controller_domain_count": 1,
                },
                "physical_conflict_core_status": (
                    "known" if core_count is not None else "unknown_pending_conflict_analysis"
                ),
                "execution_hint": {
                    "classification_only": True,
                    "automatic_authorization": "blocked",
                    "controller_domain_ids": [node_id],
                },
            }
        ),
        encoding="utf-8",
    )
    return path, classification_id, _digest(path)


def test_real_2394_is_rejected_by_the_single_core_builder(tmp_path: Path) -> None:
    classification, classification_id, digest = _classification(
        tmp_path,
        "2394",
        physical_arrangement="compound",
        control_domain="multi_owner_single_controller",
        core_count=2,
        owner_count=5,
    )
    output = tmp_path / "candidate"

    with pytest.raises(
        HamburgOfficialIntersectionPlainXmlError,
        match="single-core classification gate failed",
    ):
        materialize_hamburg_official_intersection_plainxml(
            **_inputs("2394"),
            expected_node_id="2394",
            output_dir=output,
            classification_file=classification,
            accepted_classification_id=classification_id,
            expected_classification_sha256=digest,
            compile_net=False,
        )

    assert not output.exists()


@pytest.mark.parametrize("node_id", ["2349", "2394"])
def test_compound_hamburg_nodes_cannot_enter_the_single_core_compiler(
    node_id: str,
    tmp_path: Path,
) -> None:
    classification, classification_id, digest = _classification(
        tmp_path,
        node_id,
        physical_arrangement="compound",
        control_domain="multi_owner_single_controller",
        core_count=2,
        owner_count=2 if node_id == "2349" else 5,
    )
    output = tmp_path / f"candidate-{node_id}"

    with pytest.raises(HamburgOfficialIntersectionPlainXmlError):
        materialize_hamburg_official_intersection_plainxml(
            **_inputs(node_id),
            expected_node_id=node_id,
            output_dir=output,
            classification_file=classification,
            accepted_classification_id=classification_id,
            expected_classification_sha256=digest,
        )

    assert not output.exists()


def test_materializer_fails_before_writing_on_hash_mismatch(tmp_path: Path) -> None:
    output = tmp_path / "candidate"
    classification, classification_id, digest = _classification(tmp_path, "2394")
    with pytest.raises(HamburgOfficialIntersectionPlainXmlError, match="SHA-256"):
        materialize_hamburg_official_intersection_plainxml(
            **_inputs("2394"),
            expected_node_id="2394",
            expected_sha256={"map_xml": "0" * 64},
            output_dir=output,
            classification_file=classification,
            accepted_classification_id=classification_id,
            expected_classification_sha256=digest,
            compile_net=False,
        )
    assert not output.exists()


def test_materializer_never_overwrites_existing_candidate_directory(tmp_path: Path) -> None:
    output = tmp_path / "candidate"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("unchanged", encoding="utf-8")
    classification, classification_id, digest = _classification(tmp_path, "2349")

    with pytest.raises(HamburgOfficialIntersectionPlainXmlError, match="must not already exist"):
        materialize_hamburg_official_intersection_plainxml(
            **_inputs("2349"),
            expected_node_id="2349",
            output_dir=output,
            classification_file=classification,
            accepted_classification_id=classification_id,
            expected_classification_sha256=digest,
            compile_net=False,
        )

    assert marker.read_text(encoding="utf-8") == "unchanged"


def test_materializer_requires_a_hash_bound_single_core_classification(
    tmp_path: Path,
) -> None:
    output = tmp_path / "candidate"

    with pytest.raises(
        HamburgOfficialIntersectionPlainXmlError,
        match="requires classification_file",
    ):
        materialize_hamburg_official_intersection_plainxml(
            **_inputs("2349"),
            expected_node_id="2349",
            output_dir=output,
            compile_net=False,
        )

    assert not output.exists()


def test_single_core_profile_validator_accepts_only_confirmed_one_by_one_layout(
    tmp_path: Path,
) -> None:
    classification, classification_id, _digest_value = _classification(
        tmp_path,
        "example",
    )

    report = _validate_single_core_layout_profile(
        classification,
        node_id="example",
        accepted_classification_id=classification_id,
    )

    assert report["classification_id"] == classification_id


@pytest.mark.parametrize(
    ("core_count", "owner_count"),
    [(None, 1), (1, 2), (2, 1)],
)
def test_single_core_profile_validator_rejects_unknown_or_multi_core_owner_layout(
    tmp_path: Path,
    core_count: int | None,
    owner_count: int,
) -> None:
    classification, classification_id, _digest_value = _classification(
        tmp_path,
        f"case-{core_count}-{owner_count}",
        core_count=core_count,
        owner_count=owner_count,
    )

    with pytest.raises(
        HamburgOfficialIntersectionPlainXmlError,
        match="single-core classification gate failed",
    ):
        _validate_single_core_layout_profile(
            classification,
            node_id=f"case-{core_count}-{owner_count}",
            accepted_classification_id=classification_id,
        )
