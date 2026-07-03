from __future__ import annotations

import math
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .schema import CompiledSUMOArtifacts, IntersectionIR


def compile_intersection_to_plain(
    ir: IntersectionIR,
    output_dir: Path,
    prefix: str,
    compile_net: bool = True,
) -> CompiledSUMOArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    node_file = output_dir / f"{prefix}.nod.xml"
    edge_file = output_dir / f"{prefix}.edg.xml"
    connection_file = output_dir / f"{prefix}.con.xml"
    type_file = output_dir / f"{prefix}.typ.xml"
    tllogic_file = output_dir / f"{prefix}.tll.xml" if ir.control.control_type == "traffic_light" else None
    net_file = output_dir / f"{prefix}.net.xml"

    _write_nodes(node_file, ir)
    _write_edges(edge_file, ir)
    _write_connections(connection_file, ir)
    _write_types(type_file, {approach.highway_class for approach in ir.approaches})
    if tllogic_file is not None:
        _write_tllogic(tllogic_file, ir)

    netconvert_warnings: list[str] = []
    compiled_net = False
    if compile_net:
        compiled_net, netconvert_warnings = _run_netconvert(
            node_file,
            edge_file,
            connection_file,
            type_file,
            tllogic_file,
            net_file,
        )
    return CompiledSUMOArtifacts(
        plain_node_file=str(node_file),
        plain_edge_file=str(edge_file),
        plain_connection_file=str(connection_file),
        plain_type_file=str(type_file),
        plain_tllogic_file=str(tllogic_file) if tllogic_file else None,
        net_file=str(net_file) if compiled_net else "",
        sumocfg_file=None,
        netconvert_warnings=netconvert_warnings,
    )


def _write_nodes(path: Path, ir: IntersectionIR) -> None:
    root = ET.Element("nodes")
    center_x, center_y = ir.core.center_xy
    ET.SubElement(
        root,
        "node",
        id=ir.core.core_id,
        type=ir.control.control_type,
        x=f"{center_x:.2f}",
        y=f"{center_y:.2f}",
    )
    for approach in ir.approaches:
        if approach.endpoint_xy is None:
            dx = math.sin(math.radians(approach.bearing_from_core)) * 50
            dy = math.cos(math.radians(approach.bearing_from_core)) * 50
            x, y = center_x + dx, center_y + dy
        else:
            x, y = approach.endpoint_xy
        ET.SubElement(
            root,
            "node",
            id=approach.approach_id,
            x=f"{x:.2f}",
            y=f"{y:.2f}",
            type="priority",
        )
    _write_xml(path, root)


def _write_edges(path: Path, ir: IntersectionIR) -> None:
    root = ET.Element("edges")
    for approach in ir.approaches:
        edge_type = f"highway.{approach.highway_class}"
        allow = " ".join(sorted(approach.allowed_modes))
        incoming_attrs = {"from": approach.approach_id, "to": ir.core.core_id, "type": edge_type, "numLanes": str(approach.incoming_lane_count), "allow": allow}
        outgoing_attrs = {"from": ir.core.core_id, "to": approach.approach_id, "type": edge_type, "numLanes": str(approach.outgoing_lane_count), "allow": allow}
        if approach.source_shape_xy:
            incoming_attrs["shape"] = _format_shape(approach.source_shape_xy)
            outgoing_attrs["shape"] = _format_shape(list(reversed(approach.source_shape_xy)))
        ET.SubElement(root, "edge", id=approach.incoming_edge_ids[0], **incoming_attrs)
        ET.SubElement(root, "edge", id=approach.outgoing_edge_ids[0], **outgoing_attrs)
    _write_xml(path, root)


def _write_connections(path: Path, ir: IntersectionIR) -> None:
    root = ET.Element("connections")
    approaches = {approach.approach_id: approach for approach in ir.approaches}
    for movement in ir.movement_matrix.movements:
        if not movement.allowed:
            continue
        source = approaches[movement.from_approach_id]
        target = approaches[movement.to_approach_id]
        attrs = {
            "from": source.incoming_edge_ids[0],
            "to": target.outgoing_edge_ids[0],
            "fromLane": str(movement.from_lane_indices[0]),
            "toLane": str(movement.to_lane_indices[0]),
            "dir": movement.turn[0],
        }
        if movement.movement_id in ir.control.link_index_map:
            attrs["tl"] = ir.control.tls_id or ir.core.core_id
            attrs["linkIndex"] = str(ir.control.link_index_map[movement.movement_id])
        ET.SubElement(root, "connection", **attrs)
    _write_xml(path, root)


def _write_types(path: Path, highway_classes: set[str]) -> None:
    root = ET.Element("types")
    for highway_class in sorted({"primary", "secondary", "residential", "road", *highway_classes}):
        ET.SubElement(root, "type", id=f"highway.{highway_class}", numLanes="1", speed="13.89")
    _write_xml(path, root)


def _write_tllogic(path: Path, ir: IntersectionIR) -> None:
    root = ET.Element("tlLogics")
    logic = ET.SubElement(root, "tlLogic", id=ir.control.tls_id or ir.core.core_id, type="static", programID="0", offset="0")
    for phase in ir.control.phases:
        ET.SubElement(logic, "phase", duration=f"{phase.duration:g}", state=phase.state)
    _write_xml(path, root)


def _format_shape(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def _run_netconvert(
    node_file: Path,
    edge_file: Path,
    connection_file: Path,
    type_file: Path,
    tllogic_file: Path | None,
    net_file: Path,
) -> tuple[bool, list[str]]:
    netconvert = shutil.which("netconvert")
    if not netconvert:
        return False, []
    command = [
        netconvert,
        "--node-files",
        str(node_file),
        "--edge-files",
        str(edge_file),
        "--connection-files",
        str(connection_file),
        "--type-files",
        str(type_file),
        "--no-turnarounds",
        "--output-file",
        str(net_file),
    ]
    if tllogic_file:
        command.extend(["--tllogic-files", str(tllogic_file)])
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    return result.returncode == 0, _warning_lines(result.stdout, result.stderr)


def _warning_lines(*texts: str) -> list[str]:
    return [line.strip() for text in texts for line in text.splitlines() if line.strip().startswith("Warning:")]


def _write_xml(path: Path, root: ET.Element) -> None:
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
