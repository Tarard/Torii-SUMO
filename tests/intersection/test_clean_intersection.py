from pathlib import Path

from torii_sumo.intersection.clean import clean_intersection


FIXTURES = Path(__file__).parent / "fixtures"


def test_clean_intersection_writes_ir_validation_and_plain_files(tmp_path: Path) -> None:
    result = clean_intersection(FIXTURES / "t3_priority.osm.xml", tmp_path, compile_net=True)

    assert result["status"] in {"pass", "blocked", "fail"}
    assert result["intersection_id"] == "core_1"
    assert result["topology_type"] == "T3"
    assert result["approach_count"] == 3
    assert result["movement_count"] > 0
    for name in ["intersection_ir.json", "validation.json", "intersection.nod.xml", "intersection.edg.xml", "intersection.con.xml"]:
        assert (tmp_path / name).exists()
