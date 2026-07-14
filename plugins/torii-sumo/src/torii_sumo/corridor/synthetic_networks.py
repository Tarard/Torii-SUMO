from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Literal
from xml.etree import ElementTree as ET

from .enums import GateStatus, TrafficSide


@dataclass(frozen=True)
class SyntheticFixtureDefinition:
    fixture_id: str
    expected_clean_status: GateStatus


@dataclass(frozen=True)
class _MovementSpec:
    from_edge: str
    to_edge: str
    from_lane: int
    to_lane: int
    turn: str
    start: tuple[float, float]
    end: tuple[float, float]
    mode: str = "passenger"
    internal_function: str = "internal"


FIXTURES = {
    "standard-x4": SyntheticFixtureDefinition("standard-x4", GateStatus.PASS),
    "parallel-two-lane-x4": SyntheticFixtureDefinition(
        "parallel-two-lane-x4",
        GateStatus.PASS,
    ),
    "pedestrian-x4": SyntheticFixtureDefinition("pedestrian-x4", GateStatus.REVIEW),
    "rail-x4": SyntheticFixtureDefinition("rail-x4", GateStatus.REVIEW),
}


def build_synthetic_fixture(
    fixture_id: str,
    *,
    traffic_side: TrafficSide,
) -> ET.Element:
    if fixture_id not in FIXTURES:
        raise ValueError(f"Unknown synthetic fixture: {fixture_id}")
    if traffic_side is TrafficSide.UNKNOWN:
        raise ValueError("Synthetic fixtures require an explicit traffic side.")
    modal_kind: Literal["pedestrian", "rail"] | None = None
    if fixture_id == "pedestrian-x4":
        modal_kind = "pedestrian"
    elif fixture_id == "rail-x4":
        modal_kind = "rail"
    return _build_x4(
        traffic_side=traffic_side,
        parallel_straight=fixture_id == "parallel-two-lane-x4",
        modal_kind=modal_kind,
    )


def apply_synthetic_mutation(root: ET.Element, mutation_id: str) -> ET.Element:
    try:
        mutation = _MUTATIONS[mutation_id]
    except KeyError as exc:
        raise ValueError(f"Unknown synthetic mutation: {mutation_id}") from exc
    mutated = deepcopy(root)
    mutation(mutated)
    return mutated


def _build_x4(
    *,
    traffic_side: TrafficSide,
    parallel_straight: bool,
    modal_kind: Literal["pedestrian", "rail"] | None,
) -> ET.Element:
    root = ET.Element("net")
    if traffic_side is TrafficSide.LEFT:
        root.set("lefthand", "true")
    coordinates = {
        "W": (-100.0, 0.0),
        "E": (100.0, 0.0),
        "S": (0.0, -100.0),
        "N": (0.0, 100.0),
    }
    incoming_lane_ids: list[str] = []
    peripheral_junctions: list[tuple[str, float, float]] = []
    for arm, (x, y) in coordinates.items():
        priority = "3" if arm in {"W", "E"} else "2"
        incoming = ET.SubElement(
            root,
            "edge",
            {"id": f"{arm}_in", "from": arm, "to": "J0", "priority": priority},
        )
        outgoing = ET.SubElement(
            root,
            "edge",
            {"id": f"{arm}_out", "from": "J0", "to": arm, "priority": priority},
        )
        for lane_index in range(3):
            incoming_boundary = _lane_boundary(arm, lane_index, incoming=True)
            outgoing_boundary = _lane_boundary(arm, lane_index, incoming=False)
            incoming_lane_id = f"{arm}_in_{lane_index}"
            incoming_lane_ids.append(incoming_lane_id)
            ET.SubElement(
                incoming,
                "lane",
                {
                    "id": incoming_lane_id,
                    "index": str(lane_index),
                    "allow": "passenger",
                    "width": "3.2",
                    "speed": "13.89",
                    "length": "100",
                    "shape": f"{_point((x, y))} {_point(incoming_boundary)}",
                },
            )
            ET.SubElement(
                outgoing,
                "lane",
                {
                    "id": f"{arm}_out_{lane_index}",
                    "index": str(lane_index),
                    "allow": "passenger",
                    "width": "3.2",
                    "speed": "13.89",
                    "length": "100",
                    "shape": f"{_point(outgoing_boundary)} {_point((x, y))}",
                },
            )
        peripheral_junctions.append((arm, x, y))

    movement_rows = {
        "W": (("S", 0, 0, "r"), ("E", 1, 1, "s"), ("N", 2, 2, "l")),
        "E": (("N", 0, 0, "r"), ("W", 1, 1, "s"), ("S", 2, 2, "l")),
        "S": (("E", 0, 0, "r"), ("N", 1, 1, "s"), ("W", 2, 2, "l")),
        "N": (("W", 0, 0, "r"), ("S", 1, 1, "s"), ("E", 2, 2, "l")),
    }
    movements = [
        _MovementSpec(
            from_edge=f"{arm}_in",
            to_edge=f"{target}_out",
            from_lane=source_lane,
            to_lane=target_lane,
            turn=turn,
            start=_lane_boundary(arm, source_lane, incoming=True),
            end=_lane_boundary(target, target_lane, incoming=False),
        )
        for arm, rows in movement_rows.items()
        for target, source_lane, target_lane, turn in rows
    ]
    if parallel_straight:
        movements.append(
            _MovementSpec(
                from_edge="W_in",
                to_edge="E_out",
                from_lane=2,
                to_lane=2,
                turn="s",
                start=_lane_boundary("W", 2, incoming=True),
                end=_lane_boundary("E", 2, incoming=False),
            )
        )
    if modal_kind is not None:
        prefix = "P" if modal_kind == "pedestrian" else "R"
        source_junction = f"{prefix}N"
        target_junction = f"{prefix}S"
        incoming_edge = f"{prefix}_in"
        outgoing_edge = f"{prefix}_out"
        incoming_lane = f"{incoming_edge}_0"
        outgoing_lane = f"{outgoing_edge}_0"
        incoming = ET.SubElement(
            root,
            "edge",
            {"id": incoming_edge, "from": source_junction, "to": "J0", "priority": "4"},
        )
        outgoing = ET.SubElement(
            root,
            "edge",
            {"id": outgoing_edge, "from": "J0", "to": target_junction, "priority": "4"},
        )
        width = "2.0" if modal_kind == "pedestrian" else "3.2"
        speed = "1.4" if modal_kind == "pedestrian" else "22.0"
        ET.SubElement(
            incoming,
            "lane",
            {
                "id": incoming_lane,
                "index": "0",
                "allow": modal_kind,
                "width": width,
                "speed": speed,
                "length": "100",
                "shape": "0.0,100.0 0.0,5.0",
            },
        )
        ET.SubElement(
            outgoing,
            "lane",
            {
                "id": outgoing_lane,
                "index": "0",
                "allow": modal_kind,
                "width": width,
                "speed": speed,
                "length": "100",
                "shape": "0.0,-5.0 0.0,-100.0",
            },
        )
        incoming_lane_ids.append(incoming_lane)
        peripheral_junctions.extend(
            ((source_junction, 0.0, 100.0), (target_junction, 0.0, -100.0))
        )
        movements.append(
            _MovementSpec(
                from_edge=incoming_edge,
                to_edge=outgoing_edge,
                from_lane=0,
                to_lane=0,
                turn="s",
                start=(0.0, 5.0),
                end=(0.0, -5.0),
                mode=modal_kind,
                internal_function=("crossing" if modal_kind == "pedestrian" else "internal"),
            )
        )

    internal_lane_ids: list[str] = []
    internal_edge_ids: list[str] = []
    for index, movement in enumerate(movements):
        edge_id = f":J0_{index}"
        lane_id = f"{edge_id}_0"
        internal_edge_ids.append(edge_id)
        internal_lane_ids.append(lane_id)
        internal = ET.SubElement(
            root,
            "edge",
            {"id": edge_id, "function": movement.internal_function},
        )
        ET.SubElement(
            internal,
            "lane",
            {
                "id": lane_id,
                "index": "0",
                "allow": movement.mode,
                "width": "2.0" if movement.mode == "pedestrian" else "3.2",
                "speed": "1.4" if movement.mode == "pedestrian" else "10.0",
                "length": "12",
                "shape": f"{_point(movement.start)} 0.0,0.0 {_point(movement.end)}",
            },
        )

    movement_count = len(movements)
    logic = ET.SubElement(
        root,
        "tlLogic",
        {"id": "J0", "type": "static", "programID": "gold", "offset": "0"},
    )
    road_green = ["r"] * movement_count
    road_green[1] = "G"
    ET.SubElement(logic, "phase", {"duration": "30", "state": "".join(road_green)})
    ET.SubElement(logic, "phase", {"duration": "3", "state": "r" * movement_count})
    if modal_kind is not None:
        modal_green = ["r"] * movement_count
        modal_green[-1] = "G"
        ET.SubElement(logic, "phase", {"duration": "20", "state": "".join(modal_green)})

    junction = ET.SubElement(
        root,
        "junction",
        {
            "id": "J0",
            "type": "traffic_light",
            "x": "0",
            "y": "0",
            "incLanes": " ".join(incoming_lane_ids),
            "intLanes": " ".join(internal_lane_ids),
        },
    )
    for request_index in range(movement_count):
        foes = ["0"] * movement_count
        if request_index == 0:
            foes[movement_count - 1 - 1] = "1"
        elif request_index == 1:
            foes[movement_count - 1 - 0] = "1"
        ET.SubElement(
            junction,
            "request",
            {
                "index": str(request_index),
                "response": "0" * movement_count,
                "foes": "".join(foes),
                "cont": "0",
            },
        )
    for junction_id, x, y in peripheral_junctions:
        ET.SubElement(
            root,
            "junction",
            {"id": junction_id, "type": "priority", "x": str(x), "y": str(y)},
        )

    for index, movement in enumerate(movements):
        ET.SubElement(
            root,
            "connection",
            {
                "from": movement.from_edge,
                "to": movement.to_edge,
                "fromLane": str(movement.from_lane),
                "toLane": str(movement.to_lane),
                "via": internal_lane_ids[index],
                "tl": "J0",
                "linkIndex": str(index),
                "dir": movement.turn,
                "state": "o",
            },
        )
    for index, movement in enumerate(movements):
        ET.SubElement(
            root,
            "connection",
            {
                "from": internal_edge_ids[index],
                "to": movement.to_edge,
                "fromLane": "0",
                "toLane": str(movement.to_lane),
                "dir": movement.turn,
                "state": "M",
            },
        )
    return root


def _lane_boundary(arm: str, lane_index: int, *, incoming: bool) -> tuple[float, float]:
    offset = -3.2 + 3.2 * lane_index
    if arm == "W":
        return (-5.0, offset if incoming else -offset)
    if arm == "E":
        return (5.0, -offset if incoming else offset)
    if arm == "S":
        return (-offset if incoming else offset, -5.0)
    return (offset if incoming else -offset, 5.0)


def _point(value: tuple[float, float]) -> str:
    return f"{value[0]:.1f},{value[1]:.1f}"


def _controlled(root: ET.Element) -> list[ET.Element]:
    return [
        connection
        for connection in root.findall("connection")
        if connection.attrib.get("tl") == "J0"
    ]


def _find_controlled(
    root: ET.Element,
    *,
    from_edge: str,
    to_edge: str,
    from_lane: int | None = None,
) -> ET.Element:
    matches = [
        connection
        for connection in _controlled(root)
        if connection.attrib.get("from") == from_edge
        and connection.attrib.get("to") == to_edge
        and (
            from_lane is None
            or connection.attrib.get("fromLane") == str(from_lane)
        )
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one controlled movement {from_edge}->{to_edge}/{from_lane}, got {len(matches)}."
        )
    return matches[0]


def _edge_for_lane(root: ET.Element, lane_id: str) -> ET.Element:
    for edge in root.findall("edge"):
        if edge.find(f"lane[@id='{lane_id}']") is not None:
            return edge
    raise ValueError(f"Lane not found in synthetic fixture: {lane_id}")


def _lane(root: ET.Element, lane_id: str) -> ET.Element:
    edge = _edge_for_lane(root, lane_id)
    lane = edge.find(f"lane[@id='{lane_id}']")
    assert lane is not None
    return lane


def _internal_connection(root: ET.Element, via_lane_id: str) -> ET.Element:
    edge_id = _edge_for_lane(root, via_lane_id).attrib["id"]
    matches = [
        connection
        for connection in root.findall("connection")
        if connection.attrib.get("from") == edge_id
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one continuation for {via_lane_id}, got {len(matches)}.")
    return matches[0]


def _wrong_to_lane(root: ET.Element) -> None:
    movement = _find_controlled(root, from_edge="W_in", to_edge="E_out", from_lane=1)
    movement.set("toLane", "0")


def _crossed_lane_map(root: ET.Element) -> None:
    first = _find_controlled(root, from_edge="W_in", to_edge="E_out", from_lane=1)
    second = _find_controlled(root, from_edge="W_in", to_edge="E_out", from_lane=2)
    for movement, target_lane in ((first, 2), (second, 1)):
        movement.set("toLane", str(target_lane))
        via = movement.attrib["via"]
        continuation = _internal_connection(root, via)
        continuation.set("toLane", str(target_lane))
        target = _lane(root, f"E_out_{target_lane}")
        target_start = target.attrib["shape"].split()[0]
        internal = _lane(root, via)
        points = internal.attrib["shape"].split()
        points[-1] = target_start
        internal.set("shape", " ".join(points))


def _duplicate_connection(root: ET.Element) -> None:
    root.append(deepcopy(_controlled(root)[0]))


def _missing_connection(root: ET.Element) -> None:
    root.remove(_controlled(root)[0])


def _incorrect_via(root: ET.Element) -> None:
    controlled = _controlled(root)
    controlled[0].set("via", controlled[1].attrib["via"])


def _internal_cycle(root: ET.Element) -> None:
    via = _controlled(root)[0].attrib["via"]
    _internal_connection(root, via).set("via", via)


def _target_mismatch(root: ET.Element) -> None:
    movement = _controlled(root)[0]
    continuation = _internal_connection(root, movement.attrib["via"])
    continuation.set("to", "E_out")
    continuation.set("toLane", "0")


def _dangling_internal(root: ET.Element) -> None:
    _controlled(root)[0].set("via", ":J0_missing_0")


def _endpoint_gap(root: ET.Element) -> None:
    via = _controlled(root)[0].attrib["via"]
    lane = _lane(root, via)
    points = lane.attrib["shape"].split()
    x, y = (float(value) for value in points[0].split(",")[:2])
    points[0] = _point((x + 20.0, y + 20.0))
    lane.set("shape", " ".join(points))


def _wrong_turn(root: ET.Element) -> None:
    _controlled(root)[0].set("dir", "l")


def _illegal_movement(root: ET.Element) -> None:
    controlled = _controlled(root)
    new_index = len(controlled)
    edge_id = f":J0_{new_index}"
    lane_id = f"{edge_id}_0"
    internal = ET.Element("edge", {"id": edge_id, "function": "internal"})
    ET.SubElement(
        internal,
        "lane",
        {
            "id": lane_id,
            "index": "0",
            "allow": "passenger",
            "width": "3.2",
            "speed": "10",
            "length": "12",
            "shape": "-5.0,3.2 0.0,0.0 -5.0,-3.2",
        },
    )
    logic = root.find("tlLogic")
    assert logic is not None
    root.insert(list(root).index(logic), internal)
    junction = root.find("junction[@id='J0']")
    assert junction is not None
    junction.set("intLanes", f"{junction.attrib.get('intLanes', '')} {lane_id}".strip())
    for request in junction.findall("request"):
        request.set("foes", "0" + request.attrib.get("foes", ""))
        request.set("response", "0" + request.attrib.get("response", ""))
    ET.SubElement(
        junction,
        "request",
        {
            "index": str(new_index),
            "foes": "0" * (new_index + 1),
            "response": "0" * (new_index + 1),
            "cont": "0",
        },
    )
    for phase in logic.findall("phase"):
        phase.set("state", phase.attrib.get("state", "") + "r")
    root.append(
        ET.Element(
            "connection",
            {
                "from": "W_in",
                "to": "W_out",
                "fromLane": "2",
                "toLane": "2",
                "via": lane_id,
                "tl": "J0",
                "linkIndex": str(new_index),
                "dir": "t",
                "state": "o",
            },
        )
    )
    root.append(
        ET.Element(
            "connection",
            {
                "from": edge_id,
                "to": "W_out",
                "fromLane": "0",
                "toLane": "2",
                "dir": "t",
                "state": "M",
            },
        )
    )


def _missing_legal_movement(root: ET.Element) -> None:
    movement = _controlled(root)[0]
    removed_index = int(movement.attrib["linkIndex"])
    via = movement.attrib["via"]
    internal_edge = _edge_for_lane(root, via)
    continuation = _internal_connection(root, via)
    root.remove(movement)
    root.remove(continuation)
    root.remove(internal_edge)
    junction = root.find("junction[@id='J0']")
    logic = root.find("tlLogic[@id='J0']")
    assert junction is not None and logic is not None
    junction.set(
        "intLanes",
        " ".join(token for token in junction.attrib.get("intLanes", "").split() if token != via),
    )
    requests = junction.findall("request")
    for request in requests:
        junction.remove(request)
    new_count = len(requests) - 1
    for index in range(new_count):
        ET.SubElement(
            junction,
            "request",
            {
                "index": str(index),
                "foes": "0" * new_count,
                "response": "0" * new_count,
                "cont": "0",
            },
        )
    for connection in _controlled(root):
        link_index = int(connection.attrib["linkIndex"])
        if link_index > removed_index:
            connection.set("linkIndex", str(link_index - 1))
    for phase in logic.findall("phase"):
        state = phase.attrib.get("state", "")
        phase.set("state", state[:removed_index] + state[removed_index + 1 :])


def _request_length(root: ET.Element) -> None:
    request = root.find("junction[@id='J0']/request[@index='0']")
    assert request is not None
    request.set("foes", request.attrib["foes"][:-1])


def _request_bit_order(root: ET.Element) -> None:
    first = root.find("junction[@id='J0']/request[@index='0']")
    second = root.find("junction[@id='J0']/request[@index='1']")
    assert first is not None and second is not None
    first.set("index", "1")
    second.set("index", "0")


def _asymmetric_foes(root: ET.Element) -> None:
    request = root.find("junction[@id='J0']/request[@index='0']")
    assert request is not None
    bits = list(request.attrib["foes"])
    count = len(bits)
    bits[count - 1 - 1] = "0"
    request.set("foes", "".join(bits))


def _set_protected_pair(root: ET.Element, first: int, second: int) -> None:
    phase = root.find("tlLogic[@id='J0']/phase")
    assert phase is not None
    state = ["r"] * len(phase.attrib["state"])
    state[first] = "G"
    state[second] = "G"
    phase.set("state", "".join(state))


def _protected_green_conflict(root: ET.Element) -> None:
    _set_protected_pair(root, 1, 7)


def _shared_link_index_conflict(root: ET.Element) -> None:
    first = _find_controlled(root, from_edge="W_in", to_edge="E_out", from_lane=1)
    second = _find_controlled(root, from_edge="S_in", to_edge="N_out", from_lane=1)
    second.set("linkIndex", first.attrib["linkIndex"])


def _out_of_range_link_index(root: ET.Element) -> None:
    _controlled(root)[0].set("linkIndex", "999")


def _phase_state_length(root: ET.Element) -> None:
    phase = root.find("tlLogic[@id='J0']/phase")
    assert phase is not None
    phase.set("state", phase.attrib["state"][:-1])


def _missing_program(root: ET.Element) -> None:
    logic = root.find("tlLogic[@id='J0']")
    assert logic is not None
    root.remove(logic)


def _link_index_2(root: ET.Element) -> None:
    _controlled(root)[0].set("linkIndex2", "0")


def _modal_conflict(root: ET.Element) -> None:
    controlled = _controlled(root)
    _set_protected_pair(root, 1, len(controlled) - 1)


_MUTATIONS: dict[str, Callable[[ET.Element], None]] = {
    "wrong-to-lane": _wrong_to_lane,
    "crossed-lane-map": _crossed_lane_map,
    "duplicate-connection": _duplicate_connection,
    "missing-connection": _missing_connection,
    "incorrect-via": _incorrect_via,
    "internal-cycle": _internal_cycle,
    "target-mismatch": _target_mismatch,
    "dangling-internal": _dangling_internal,
    "endpoint-gap": _endpoint_gap,
    "wrong-turn": _wrong_turn,
    "illegal-movement": _illegal_movement,
    "missing-legal-movement": _missing_legal_movement,
    "request-length": _request_length,
    "request-bit-order": _request_bit_order,
    "asymmetric-foes": _asymmetric_foes,
    "protected-green-conflict": _protected_green_conflict,
    "shared-link-index-conflict": _shared_link_index_conflict,
    "out-of-range-link-index": _out_of_range_link_index,
    "phase-state-length": _phase_state_length,
    "missing-program": _missing_program,
    "link-index-2": _link_index_2,
    "pedestrian-conflict": _modal_conflict,
    "rail-conflict": _modal_conflict,
}
