from pathlib import Path
import xml.etree.ElementTree as ET

from torii_sumo.core.command_runner import CommandResult
from torii_sumo.core.routeability_audit import (
    inspect_routeability_outputs,
    run_routeability_audit,
)


def test_routeability_outputs_reject_incomplete_final_summary(tmp_path: Path) -> None:
    summary = tmp_path / "summary.xml"
    tripinfo = tmp_path / "tripinfo.xml"
    summary.write_text(
        """<summary>
  <step time="119.00" loaded="60" inserted="60" arrived="4" ended="4" running="56" waiting="0" teleports="0" collisions="0"/>
</summary>""",
        encoding="utf-8",
    )
    tripinfo.write_text(
        """<tripinfos>
  <tripinfo id="veh0" duration="10" waitingTime="0" timeLoss="1"/>
  <tripinfo id="veh1" duration="10" waitingTime="0" timeLoss="1"/>
  <tripinfo id="veh2" duration="10" waitingTime="0" timeLoss="1"/>
  <tripinfo id="veh3" duration="10" waitingTime="0" timeLoss="1"/>
</tripinfos>""",
        encoding="utf-8",
    )

    report = inspect_routeability_outputs(
        summary_path=summary,
        tripinfo_path=tripinfo,
        expected_vehicle_count=60,
    )

    assert report["status"] == "fail"
    assert report["claim_status"] == "construction-invalid"
    assert report["routeability_status"] == "incomplete"
    assert report["summary"]["arrived"] == 4
    assert report["summary"]["running"] == 56
    assert any("arrived 4/60 vehicles" in warning for warning in report["warnings"])
    assert any("56 vehicles still running" in warning for warning in report["warnings"])


def test_routeability_audit_extends_horizon_until_all_vehicles_finish(tmp_path: Path) -> None:
    net_file = tmp_path / "network.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_runner(command: list[str], *, cwd: Path | None = None, timeout_seconds: float = 60.0):
        calls.append(command)
        assert cwd is not None
        if "randomTrips.py" in command:
            route_path = cwd / command[command.index("-r") + 1]
            route_path.write_text("<routes/>", encoding="utf-8")
            return CommandResult(command=command, cwd=str(cwd), status="pass", returncode=0)

        cfg_path = cwd / command[command.index("-c") + 1]
        cfg_root = ET.parse(cfg_path).getroot()
        end = int(cfg_root.find("time/end").attrib["value"])
        summary_path = cwd / cfg_root.find("output/summary-output").attrib["value"]
        tripinfo_path = cwd / cfg_root.find("output/tripinfo-output").attrib["value"]
        if end == 300:
            arrived = 4
            running = 6
        else:
            arrived = 10
            running = 0
        summary_path.write_text(
            f"""<summary>
  <step time="{end}.00" loaded="10" inserted="10" arrived="{arrived}" ended="{arrived}" running="{running}" waiting="0" teleports="0" collisions="0"/>
</summary>""",
            encoding="utf-8",
        )
        tripinfo_path.write_text(
            "<tripinfos>"
            + "".join(
                f'<tripinfo id="veh{i}" duration="10" waitingTime="0" timeLoss="1"/>'
                for i in range(arrived)
            )
            + "</tripinfos>",
            encoding="utf-8",
        )
        return CommandResult(command=command, cwd=str(cwd), status="pass", returncode=0)

    report = run_routeability_audit(
        net_file=net_file,
        output_dir=tmp_path / "audit",
        prefix="demo",
        vehicle_count=10,
        initial_end=300,
        max_end=600,
        seed=7,
        binaries={"sumo": "sumo", "randomTrips": "randomTrips.py"},
        command_runner=fake_runner,
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["routeability_status"] == "pass"
    assert [attempt["end"] for attempt in report["attempts"]] == [300, 600]
    assert report["final_attempt"]["inspection"]["summary"]["arrived"] == 10
    assert report["final_attempt"]["inspection"]["summary"]["running"] == 0
    assert Path(report["report_file"]).is_file()
    assert any(command[0] == "sumo" for command in calls)
