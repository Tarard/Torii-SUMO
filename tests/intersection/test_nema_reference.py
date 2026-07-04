import json
import xml.etree.ElementTree as ET
from pathlib import Path

from torii_sumo.core.command_runner import CommandResult
from torii_sumo.intersection.nema_reference import NEMA_PARAMS, build_nema_four_way_reference
from torii_sumo.tools.intersection_tools import sumo_nema_four_way_reference_workflow


def _fake_netconvert_from_plain(command: list[str]) -> None:
    node_file = Path(command[command.index("-n") + 1])
    tllogic_file = Path(command[command.index("--tllogic-files") + 1])
    net_file = Path(command[command.index("-o") + 1])

    root = ET.Element("net")
    for node in ET.parse(node_file).getroot().findall("node"):
        ET.SubElement(root, "junction", id=node.attrib["id"], type=node.attrib.get("type", "priority"))
    for logic in ET.parse(tllogic_file).getroot().findall("tlLogic"):
        root.append(logic)
    for connection in ET.parse(tllogic_file).getroot().findall("connection"):
        attrs = dict(connection.attrib)
        attrs.setdefault("dir", "l" if attrs["fromLane"] == "2" else "s")
        ET.SubElement(root, "connection", **attrs)
    ET.ElementTree(root).write(net_file, encoding="utf-8", xml_declaration=True)


def test_build_nema_four_way_reference_writes_dual_ring_nema_artifacts(tmp_path: Path) -> None:
    def fake_runner(command: list[str], **_kwargs) -> CommandResult:
        if command[0] == "netconvert":
            _fake_netconvert_from_plain(command)
        return CommandResult(command=command, cwd=None, status="pass", returncode=0)

    report = build_nema_four_way_reference(
        tmp_path,
        command_runner=fake_runner,
        which_func=lambda name: name,
        run_sumo_smoke=False,
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["nema_params"]["total-cycle-length"] == "90"
    assert "cycle-length" not in report["nema_params"]
    assert report["controlled_link_count"] == 12
    assert report["tls_signal_group_count"] == 8
    assert Path(report["net_file"]).is_file()
    assert Path(report["sumocfg_file"]).is_file()

    logic = ET.parse(report["additional_file"]).getroot().find("tlLogic")
    assert logic is not None
    assert logic.attrib["type"] == "NEMA"
    assert logic.attrib["programID"] == "NEMA"
    assert {param.attrib["key"]: param.attrib["value"] for param in logic.findall("param")} == NEMA_PARAMS
    assert [phase.attrib["name"] for phase in logic.findall("phase")] == [str(i) for i in range(1, 9)]
    assert {len(phase.attrib["state"]) for phase in logic.findall("phase")} == {8}

    audit = json.loads(Path(report["audit_file"]).read_text(encoding="utf-8"))
    assert audit["phase_order"] == [str(i) for i in range(1, 9)]
    assert {row["linkIndex"] for row in audit["movement_map"]} == set(range(8))
    json.dumps(report)


def test_sumo_nema_four_way_reference_workflow_returns_json_report(monkeypatch, tmp_path: Path) -> None:
    from torii_sumo.tools import intersection_tools

    def fake_builder(output_dir: Path, **kwargs):
        assert output_dir == tmp_path
        assert kwargs["prefix"] == "probe"
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "workflow": "nema_four_way_reference",
            "net_file": str(tmp_path / "probe.net.xml"),
            "sumocfg_file": str(tmp_path / "probe.sumocfg"),
        }

    monkeypatch.setattr(intersection_tools, "build_nema_four_way_reference", fake_builder)

    report = sumo_nema_four_way_reference_workflow(
        output_dir=str(tmp_path),
        prefix="probe",
        run_sumo_smoke=False,
    )

    assert report["status"] == "pass"
    assert report["workflow"] == "nema_four_way_reference"
    json.dumps(report)
