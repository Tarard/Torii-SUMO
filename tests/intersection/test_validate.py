from pathlib import Path

from torii_sumo.intersection.clean import build_intersection_ir
from torii_sumo.intersection.schema import CompiledSUMOArtifacts
from torii_sumo.intersection.validate import validate_intersection


FIXTURES = Path(__file__).parent / "fixtures"


def test_validate_intersection_passes_absolute_net_path_to_sumo(monkeypatch, tmp_path: Path) -> None:
    ir = build_intersection_ir(FIXTURES / "t3_priority.osm.xml", tmp_path)
    monkeypatch.chdir(tmp_path)
    output_dir = Path("artifacts") / "intersection"
    output_dir.mkdir(parents=True)
    net_file = output_dir / "intersection.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    seen = {}

    monkeypatch.setattr("torii_sumo.intersection.validate.shutil.which", lambda _name: "sumo")

    def fake_run(command, **kwargs):
        seen["net_arg"] = command[2]
        seen["cwd"] = kwargs["cwd"]

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr("torii_sumo.intersection.validate.subprocess.run", fake_run)

    result = validate_intersection(
        ir,
        CompiledSUMOArtifacts(
            plain_node_file="",
            plain_edge_file="",
            plain_connection_file="",
            net_file=str(net_file),
        ),
        output_dir,
    )

    assert Path(seen["net_arg"]).is_absolute()
    assert seen["cwd"] == output_dir
    assert result.sumo_load_status == "pass"
