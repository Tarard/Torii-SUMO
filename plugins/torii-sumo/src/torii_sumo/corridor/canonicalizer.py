from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from .base import ContractModel, Sha256, StableToken
from .enums import TrafficSide
from .ids import (
    make_approach_id,
    make_boundary_port_id,
    make_lane_role_id,
    make_movement_id,
    make_physical_cell_id,
    make_signal_group_id,
    require_stable_id,
    stable_digest,
    stable_id,
)
from .netxml import RawConnection, RawEdge, RawLane, RawNetwork, parse_net_xml_file


class CanonicalEntity(ContractModel):
    kind: str
    stable_entity_id: StableToken
    semantic_signature: StableToken
    owner_physical_cell_ids: tuple[StableToken, ...] = ()
    boundary_port_ids: tuple[StableToken, ...] = ()
    payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_entity(self) -> CanonicalEntity:
        require_stable_id(self.stable_entity_id)
        require_stable_id(self.semantic_signature, kind="signature")
        for cell_id in self.owner_physical_cell_ids:
            require_stable_id(cell_id, kind="cell")
        for port_id in self.boundary_port_ids:
            require_stable_id(port_id, kind="port")
        return self


class CanonicalNetworkSnapshot(ContractModel):
    schema_id: str = "torii.corridor.canonical-network/v1"
    traffic_side: TrafficSide
    source_sha256: Sha256 | None = None
    entities: tuple[CanonicalEntity, ...]
    raw_id_maps: dict[str, dict[str, StableToken]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_snapshot(self) -> CanonicalNetworkSnapshot:
        keys = [(entity.kind, entity.stable_entity_id) for entity in self.entities]
        if len(keys) != len(set(keys)):
            raise ValueError("Canonical entity kind/ID pairs must be unique.")
        if self.traffic_side is TrafficSide.UNKNOWN:
            raise ValueError("Canonicalization requires an explicit traffic side.")
        return self

    def entity_index(self) -> dict[tuple[str, str], CanonicalEntity]:
        return {
            (entity.kind, entity.stable_entity_id): entity
            for entity in self.entities
        }


def canonicalize_net_xml_file(
    path: Path,
    *,
    traffic_side: TrafficSide,
) -> CanonicalNetworkSnapshot:
    source = path.resolve()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return canonicalize_raw_network(
        parse_net_xml_file(source),
        traffic_side=traffic_side,
        source_sha256=digest,
    )


def canonicalize_raw_network(
    network: RawNetwork,
    *,
    traffic_side: TrafficSide,
    source_sha256: str | None = None,
) -> CanonicalNetworkSnapshot:
    if traffic_side is TrafficSide.UNKNOWN:
        raise ValueError("Canonicalization is blocked until traffic side is known.")

    outgoing_connections: dict[tuple[str, int], list[RawConnection]] = defaultdict(list)
    for connection in network.connections:
        if connection.from_lane is not None:
            outgoing_connections[(connection.from_edge, connection.from_lane)].append(connection)

    entities: dict[tuple[str, str], CanonicalEntity] = {}
    junction_cell_ids: dict[str, str] = {}
    port_ids_by_edge_flow: dict[tuple[str, str, str], str] = {}
    approach_ids_by_edge_flow: dict[tuple[str, str, str], str] = {}
    lane_role_ids: dict[tuple[str, str, str, int], str] = {}
    raw_lane_role_ids: dict[tuple[str, str], str] = {}
    port_descriptors: dict[tuple[str, str, str], dict[str, Any]] = {}

    for junction_id, junction in sorted(network.junctions.items()):
        incident = _incident_external_edges(network, junction_id)
        if not _junction_requires_physical_cell(
            network,
            junction_id=junction_id,
            incident=incident,
        ):
            continue
        for edge, flow in incident:
            descriptor = _port_descriptor(
                edge,
                flow=flow,
                traffic_side=traffic_side,
                outgoing_connections=outgoing_connections,
                network=network,
            )
            key = (junction_id, edge.edge_id, flow)
            port_descriptors[key] = descriptor
            port_ids_by_edge_flow[key] = descriptor["port_id"]
        cell_id = make_physical_cell_id(
            boundary_port_ids=tuple(
                port_ids_by_edge_flow[(junction_id, edge.edge_id, flow)]
                for edge, flow in incident
            ),
            grade_separation_signature=_grade_separation_signature(incident),
        )
        junction_cell_ids[junction_id] = cell_id

        for edge, flow in incident:
            key = (junction_id, edge.edge_id, flow)
            port_id = port_ids_by_edge_flow[key]
            approach_id = make_approach_id(
                physical_cell_id=cell_id,
                boundary_port_id=port_id,
                flow=flow,
            )
            approach_ids_by_edge_flow[key] = approach_id
            lane_ids_for_port: list[str] = []
            for lane in edge.lanes:
                ordinal_from_curb = _ordinal_from_curb(
                    lane.ordinal,
                    lane_count=len(edge.lanes),
                    traffic_side=traffic_side,
                )
                role = _lane_role(
                    edge,
                    lane,
                    flow=flow,
                    outgoing_connections=outgoing_connections,
                    network=network,
                )
                lane_role_id = make_lane_role_id(
                    approach_id=approach_id,
                    ordinal_from_curb=ordinal_from_curb,
                    role=role,
                    modes=_permission_tokens(lane),
                    traffic_side=traffic_side.value,
                )
                lane_role_ids[(junction_id, edge.edge_id, flow, lane.ordinal)] = lane_role_id
                raw_lane_role_ids[(junction_id, lane.lane_id)] = lane_role_id
                lane_ids_for_port.append(lane_role_id)
                _put_entity(
                    entities,
                    kind="lane_role",
                    entity_id=lane_role_id,
                    owner_cell_ids=(cell_id,),
                    boundary_port_ids=(port_id,),
                    payload={
                        "approach_id": approach_id,
                        "boundary_port_id": port_id,
                        "flow": flow,
                        "ordinal_from_curb": ordinal_from_curb,
                        "role": role,
                        "permissions": _lane_permissions(lane),
                        "speed_mps": lane.speed,
                        "length_m": lane.length,
                        "width_m": lane.width,
                        "shape_xy": _rounded_shape(lane.shape),
                    },
                )
            descriptor = port_descriptors[key]
            _put_entity(
                entities,
                kind="boundary_port",
                entity_id=port_id,
                owner_cell_ids=(cell_id,),
                boundary_port_ids=(port_id,),
                payload={
                    "source_anchor_refs": descriptor["source_anchor_refs"],
                    "source_geometry_sha256": descriptor["source_geometry_sha256"],
                    "flow": flow,
                    "center_xy": descriptor["center_xy"],
                    "tangent_xy": descriptor["tangent_xy"],
                    "normal_xy": descriptor["normal_xy"],
                    "lane_role_ids": lane_ids_for_port,
                    "lane_widths_m": [
                        lane.width if lane.width is not None else 3.2
                        for lane in edge.lanes
                    ],
                    "traffic_side": traffic_side.value,
                    "edge_semantics": {
                        "type": edge.edge_type,
                        "priority": edge.priority,
                        "name": edge.name,
                        "params": edge.params,
                    },
                },
            )
            _put_entity(
                entities,
                kind="approach",
                entity_id=approach_id,
                owner_cell_ids=(cell_id,),
                boundary_port_ids=(port_id,),
                payload={
                    "physical_cell_id": cell_id,
                    "boundary_port_id": port_id,
                    "flow": flow,
                    "lane_role_ids": lane_ids_for_port,
                },
            )

        request_payload = [
            {
                "index": request.index,
                "response": request.response,
                "foes": request.foes,
                "cont": request.cont,
            }
            for request in junction.requests
        ]
        _put_entity(
            entities,
            kind="physical_cell",
            entity_id=cell_id,
            owner_cell_ids=(cell_id,),
            boundary_port_ids=tuple(
                sorted(
                    port_ids_by_edge_flow[(junction_id, edge.edge_id, flow)]
                    for edge, flow in incident
                )
            ),
            payload={
                "junction_type": junction.junction_type,
                "position_xy": _rounded_point((junction.x, junction.y)),
                "boundary_port_ids": sorted(
                    port_ids_by_edge_flow[(junction_id, edge.edge_id, flow)]
                    for edge, flow in incident
                ),
                "requests": request_payload,
            },
        )
        request_id = stable_id("request", {"physical_cell_id": cell_id})
        _put_entity(
            entities,
            kind="request_foes",
            entity_id=request_id,
            owner_cell_ids=(cell_id,),
            payload={
                "physical_cell_id": cell_id,
                "request_rows": request_payload,
            },
        )

    connection_movement_ids: dict[str, str] = {}
    movement_variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    movement_owners: dict[str, tuple[str, str, str]] = {}
    for connection in network.connections:
        source_edge = network.edges.get(connection.from_edge)
        target_edge = network.edges.get(connection.to_edge)
        if (
            source_edge is None
            or target_edge is None
            or not source_edge.external
            or not target_edge.external
            or source_edge.to_junction != target_edge.from_junction
        ):
            continue
        junction_id = source_edge.to_junction
        cell_id = junction_cell_ids.get(junction_id)
        source_port_id = port_ids_by_edge_flow.get((junction_id, source_edge.edge_id, "incoming"))
        target_port_id = port_ids_by_edge_flow.get((junction_id, target_edge.edge_id, "outgoing"))
        source_role_id = lane_role_ids.get(
            (junction_id, source_edge.edge_id, "incoming", connection.from_lane)
        )
        target_role_id = lane_role_ids.get(
            (junction_id, target_edge.edge_id, "outgoing", connection.to_lane)
        )
        if not all((cell_id, source_port_id, target_port_id, source_role_id, target_role_id)):
            continue
        source_lane = _lane_by_ordinal(source_edge, connection.from_lane)
        target_lane = _lane_by_ordinal(target_edge, connection.to_lane)
        mode = _movement_mode(source_lane, target_lane)
        turn_class = _turn_class(connection.direction)
        movement_id = make_movement_id(
            physical_cell_id=cell_id,
            source_boundary_port_id=source_port_id,
            source_lane_role_id=source_role_id,
            destination_boundary_port_id=target_port_id,
            destination_lane_role_id=target_role_id,
            mode=mode,
            turn_class=turn_class,
        )
        connection_movement_ids[str(connection.connection_index)] = movement_id
        path = _trace_internal_semantics(connection, network)
        path_signature = stable_id(
            "signature",
            {"movement_id": movement_id, "path": path},
        )
        movement_variants[movement_id].append(
            {
                "source_boundary_port_id": source_port_id,
                "source_lane_role_id": source_role_id,
                "destination_boundary_port_id": target_port_id,
                "destination_lane_role_id": target_role_id,
                "mode": mode,
                "turn_class": turn_class,
                "state": connection.state,
                "path_signature": path_signature,
                "path": path,
            }
        )
        movement_owners[movement_id] = (cell_id, source_port_id, target_port_id)

    for movement_id, variants in sorted(movement_variants.items()):
        cell_id, source_port_id, target_port_id = movement_owners[movement_id]
        normalized_variants = sorted(variants, key=lambda value: stable_digest("movement-variant", value))
        path_id = stable_id("path", {"movement_id": movement_id})
        _put_entity(
            entities,
            kind="internal_path",
            entity_id=path_id,
            owner_cell_ids=(cell_id,),
            boundary_port_ids=(source_port_id, target_port_id),
            payload={
                "movement_id": movement_id,
                "multiplicity": len(normalized_variants),
                "path_variants": [
                    {
                        "path_signature": variant["path_signature"],
                        "path": variant["path"],
                    }
                    for variant in normalized_variants
                ],
            },
        )
        _put_entity(
            entities,
            kind="movement",
            entity_id=movement_id,
            owner_cell_ids=(cell_id,),
            boundary_port_ids=(source_port_id, target_port_id),
            payload={
                "multiplicity": len(normalized_variants),
                "variants": [
                    {
                        key: value
                        for key, value in variant.items()
                        if key != "path"
                    }
                    for variant in normalized_variants
                ],
                "internal_path_id": path_id,
            },
        )

    tls_controller_ids: dict[str, str] = {}
    for raw_controller_id, programs in sorted(network.tls_programs.items()):
        controlled = [
            connection
            for connection in network.connections
            if connection.controller_id == raw_controller_id
            and str(connection.connection_index) in connection_movement_ids
        ]
        if not controlled:
            continue
        movement_ids = sorted(
            {connection_movement_ids[str(connection.connection_index)] for connection in controlled}
        )
        owner_cells = sorted(
            {
                cell_id
                for movement_id in movement_ids
                for cell_id in entities[("movement", movement_id)].owner_physical_cell_ids
            }
        )
        controller_id = stable_id(
            "controller",
            {
                "owner_physical_cell_ids": owner_cells,
                "controlled_movement_ids": movement_ids,
                "program_ids": sorted(program.program_id for program in programs),
            },
        )
        tls_controller_ids[raw_controller_id] = controller_id
        movements_by_index: dict[int, set[str]] = defaultdict(set)
        for connection in controlled:
            movement_id = connection_movement_ids[str(connection.connection_index)]
            if connection.link_index is not None:
                movements_by_index[connection.link_index].add(movement_id)
            if connection.link_index2 is not None:
                movements_by_index[connection.link_index2].add(movement_id)
        indices_by_movement_set: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for link_index, ids in movements_by_index.items():
            indices_by_movement_set[tuple(sorted(ids))].append(link_index)
        signal_groups: list[tuple[str, tuple[int, ...], tuple[str, ...]]] = []
        for grouped_movement_ids, indices in sorted(indices_by_movement_set.items()):
            signal_group_id = make_signal_group_id(
                controller_scope_id=controller_id,
                movement_ids=grouped_movement_ids,
            )
            sorted_indices = tuple(sorted(indices))
            signal_groups.append((signal_group_id, sorted_indices, grouped_movement_ids))
            _put_entity(
                entities,
                kind="signal_group",
                entity_id=signal_group_id,
                owner_cell_ids=tuple(owner_cells),
                payload={
                    "controller_id": controller_id,
                    "movement_ids": grouped_movement_ids,
                    "source_link_indices": sorted_indices,
                    "multiple_source_indices": len(sorted_indices) > 1,
                },
            )
        program_entity_ids: list[str] = []
        for program in programs:
            program_id = stable_id(
                "program",
                {
                    "controller_id": controller_id,
                    "source_program_id": program.program_id,
                    "controller_type": program.controller_type,
                },
            )
            phases = []
            for phase in program.phases:
                group_states = []
                for signal_group_id, indices, _ in signal_groups:
                    states = tuple(
                        phase.state[index] if 0 <= index < len(phase.state) else "?"
                        for index in indices
                    )
                    group_states.append(
                        {
                            "signal_group_id": signal_group_id,
                            "states": states,
                            "consistent": len(set(states)) <= 1,
                        }
                    )
                phases.append(
                    {
                        "duration": phase.duration,
                        "minimum_duration": phase.minimum_duration,
                        "maximum_duration": phase.maximum_duration,
                        "next_phases": phase.next_phases,
                        "name": phase.name,
                        "group_states": group_states,
                    }
                )
            _put_entity(
                entities,
                kind="controller_program",
                entity_id=program_id,
                owner_cell_ids=tuple(owner_cells),
                payload={
                    "controller_id": controller_id,
                    "controller_type": program.controller_type,
                    "offset": program.offset,
                    "signal_group_ids": [group[0] for group in signal_groups],
                    "phases": phases,
                },
            )
            program_entity_ids.append(program_id)
        _put_entity(
            entities,
            kind="controller",
            entity_id=controller_id,
            owner_cell_ids=tuple(owner_cells),
            payload={
                "owner_physical_cell_ids": owner_cells,
                "controlled_movement_ids": movement_ids,
                "signal_group_ids": [group[0] for group in signal_groups],
                "program_ids": program_entity_ids,
            },
        )

    return CanonicalNetworkSnapshot(
        traffic_side=traffic_side,
        source_sha256=source_sha256,
        entities=tuple(
            entity
            for _, entity in sorted(
                entities.items(),
                key=lambda item: item[0],
            )
        ),
        raw_id_maps={
            "junction_to_physical_cell": junction_cell_ids,
            "connection_index_to_movement": connection_movement_ids,
            "tls_to_controller": tls_controller_ids,
            "edge_flow_to_boundary_port": {
                "|".join(key): value
                for key, value in port_ids_by_edge_flow.items()
            },
            "edge_flow_lane_to_lane_role": {
                "|".join((*key[:3], str(key[3]))): value
                for key, value in lane_role_ids.items()
            },
            "junction_lane_to_lane_role": {
                "|".join(key): value
                for key, value in raw_lane_role_ids.items()
            },
        },
    )


def _put_entity(
    entities: dict[tuple[str, str], CanonicalEntity],
    *,
    kind: str,
    entity_id: str,
    payload: dict[str, Any],
    owner_cell_ids: tuple[str, ...] = (),
    boundary_port_ids: tuple[str, ...] = (),
) -> None:
    entity = CanonicalEntity(
        kind=kind,
        stable_entity_id=entity_id,
        semantic_signature=stable_id(
            "signature",
            {"kind": kind, "payload": payload},
        ),
        owner_physical_cell_ids=tuple(sorted(set(owner_cell_ids))),
        boundary_port_ids=tuple(sorted(set(boundary_port_ids))),
        payload=payload,
    )
    key = (kind, entity_id)
    if key in entities:
        raise ValueError(f"Canonical entity collision: {kind}/{entity_id}")
    entities[key] = entity


def _incident_external_edges(
    network: RawNetwork,
    junction_id: str,
) -> list[tuple[RawEdge, str]]:
    incident: list[tuple[RawEdge, str]] = []
    for edge in network.edges.values():
        if not edge.external:
            continue
        if edge.to_junction == junction_id:
            incident.append((edge, "incoming"))
        if edge.from_junction == junction_id:
            incident.append((edge, "outgoing"))
    return sorted(incident, key=lambda item: (item[0].edge_id, item[1]))


def _junction_requires_physical_cell(
    network: RawNetwork,
    *,
    junction_id: str,
    incident: list[tuple[RawEdge, str]],
) -> bool:
    if not incident:
        return False
    junction = network.junctions[junction_id]
    if junction.junction_type == "dead_end":
        return False
    if junction.requests or junction.junction_type in {
        "traffic_light",
        "traffic_light_unregulated",
        "rail_crossing",
        "rail_signal",
    }:
        return True
    incoming_edge_ids = {
        edge.edge_id for edge, flow in incident if flow == "incoming"
    }
    outgoing_edge_ids = {
        edge.edge_id for edge, flow in incident if flow == "outgoing"
    }
    return any(
        connection.from_edge in incoming_edge_ids
        and connection.to_edge in outgoing_edge_ids
        for connection in network.connections
    )


def _port_descriptor(
    edge: RawEdge,
    *,
    flow: str,
    traffic_side: TrafficSide,
    outgoing_connections: dict[tuple[str, int], list[RawConnection]],
    network: RawNetwork,
) -> dict[str, Any]:
    lane_semantics = [
        {
            "ordinal_from_curb": _ordinal_from_curb(
                lane.ordinal,
                lane_count=len(edge.lanes),
                traffic_side=traffic_side,
            ),
            "role": _lane_role(
                edge,
                lane,
                flow=flow,
                outgoing_connections=outgoing_connections,
                network=network,
            ),
            "permissions": _lane_permissions(lane),
            "width_m": lane.width,
        }
        for lane in edge.lanes
    ]
    source_anchor_refs = _source_anchor_refs(edge)
    far_geometry = [
        _far_shape(lane.shape, flow=flow)
        for lane in edge.lanes
    ]
    source_geometry_sha256 = stable_digest(
        "boundary-port-source-geometry/v1",
        far_geometry,
    )
    port_id = make_boundary_port_id(
        source_anchor_refs=source_anchor_refs,
        source_geometry_sha256=source_geometry_sha256,
        lane_semantic_keys=lane_semantics,
        traffic_side=traffic_side.value,
    )
    far_points = [
        lane.shape[0] if flow == "incoming" else lane.shape[-1]
        for lane in edge.lanes
        if lane.shape
    ]
    center = _mean_point(far_points)
    tangent = _mean_tangent(edge.lanes, flow=flow)
    normal = (-tangent[1], tangent[0])
    return {
        "port_id": port_id,
        "source_anchor_refs": source_anchor_refs,
        "source_geometry_sha256": source_geometry_sha256,
        "center_xy": center,
        "tangent_xy": tangent,
        "normal_xy": normal,
    }


def _source_anchor_refs(edge: RawEdge) -> tuple[str, ...]:
    origin = edge.params.get("origId", "").strip()
    if origin:
        return tuple(sorted({token for token in origin.replace(",", " ").split() if token}))
    return (f"external-edge/{edge.edge_id}",)


def _far_shape(
    shape: tuple[tuple[float, float], ...],
    *,
    flow: str,
) -> tuple[tuple[float, float], ...]:
    if flow == "incoming":
        return _rounded_shape(shape[: min(2, len(shape))])
    return _rounded_shape(shape[max(0, len(shape) - 2) :])


def _mean_point(points: list[tuple[float, float]]) -> tuple[float, float]:
    if not points:
        return (0.0, 0.0)
    return (
        round(sum(point[0] for point in points) / len(points), 6),
        round(sum(point[1] for point in points) / len(points), 6),
    )


def _mean_tangent(lanes: tuple[RawLane, ...], *, flow: str) -> tuple[float, float]:
    vectors: list[tuple[float, float]] = []
    for lane in lanes:
        if len(lane.shape) < 2:
            continue
        if flow == "incoming":
            start, end = lane.shape[0], lane.shape[1]
        else:
            start, end = lane.shape[-2], lane.shape[-1]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length:
            vectors.append((dx / length, dy / length))
    if not vectors:
        return (1.0, 0.0)
    dx = sum(vector[0] for vector in vectors)
    dy = sum(vector[1] for vector in vectors)
    length = math.hypot(dx, dy)
    if not length:
        return (1.0, 0.0)
    return (round(dx / length, 6), round(dy / length, 6))


def _grade_separation_signature(
    incident: list[tuple[RawEdge, str]],
) -> dict[str, Any]:
    return {
        "layers": sorted(
            {
                edge.params.get("layer", "0")
                for edge, _ in incident
            }
        ),
        "bridge": any(edge.params.get("bridge", "") not in {"", "no", "false", "0"} for edge, _ in incident),
        "tunnel": any(edge.params.get("tunnel", "") not in {"", "no", "false", "0"} for edge, _ in incident),
    }


def _ordinal_from_curb(
    ordinal: int,
    *,
    lane_count: int,
    traffic_side: TrafficSide,
) -> int:
    if traffic_side is TrafficSide.RIGHT:
        return ordinal
    return lane_count - ordinal - 1


def _lane_role(
    edge: RawEdge,
    lane: RawLane,
    *,
    flow: str,
    outgoing_connections: dict[tuple[str, int], list[RawConnection]],
    network: RawNetwork,
) -> str:
    if flow == "outgoing":
        return "receiving"
    turns = sorted(
        {
            _turn_class(connection.direction)
            for connection in outgoing_connections.get((edge.edge_id, lane.ordinal), [])
            if network.edges.get(connection.to_edge) is not None
            and network.edges[connection.to_edge].external
        }
    )
    return "+".join(turns) if turns else "unconnected"


def _lane_permissions(lane: RawLane | None) -> dict[str, tuple[str, ...]]:
    if lane is None:
        return {"allow": (), "disallow": ()}
    return {"allow": lane.allow, "disallow": lane.disallow}


def _permission_tokens(lane: RawLane) -> tuple[str, ...]:
    if lane.allow:
        return tuple(f"allow:{mode}" for mode in lane.allow)
    if lane.disallow:
        return tuple(f"not:{mode}" for mode in lane.disallow)
    return ("allow:default",)


def _movement_mode(source_lane: RawLane | None, target_lane: RawLane | None) -> str:
    return stable_digest(
        "movement-permission/v1",
        {
            "source": _lane_permissions(source_lane),
            "target": _lane_permissions(target_lane),
        },
    )[:16]


def _turn_class(direction: str) -> str:
    return {
        "r": "right",
        "R": "right",
        "s": "straight",
        "l": "left",
        "L": "left",
        "t": "uturn",
        "T": "uturn",
    }.get(direction, "unknown")


def _lane_by_ordinal(edge: RawEdge, ordinal: int | None) -> RawLane | None:
    if ordinal is None or not 0 <= ordinal < len(edge.lanes):
        return None
    return edge.lanes[ordinal]


def _trace_internal_semantics(
    direct: RawConnection,
    network: RawNetwork,
) -> dict[str, Any]:
    if not direct.via:
        return {"status": "missing-via", "segments": (), "failures": ("missing-via",)}
    lane = network.lanes.get(direct.via)
    if lane is None:
        return {"status": "invalid", "segments": (), "failures": ("via-not-found",)}
    outgoing: dict[tuple[str, int], list[RawConnection]] = defaultdict(list)
    for connection in network.connections:
        if connection.from_lane is not None:
            outgoing[(connection.from_edge, connection.from_lane)].append(connection)
    segments: list[dict[str, Any]] = []
    failures: list[str] = []
    visited: set[str] = set()
    maximum_hops = max(
        1,
        sum(
            len(edge.lanes)
            for edge in network.edges.values()
            if not edge.external
        )
        + 1,
    )
    current = lane
    for _ in range(maximum_hops):
        if current.lane_id in visited:
            failures.append("cycle")
            break
        visited.add(current.lane_id)
        edge_id = network.lane_edge_ids.get(current.lane_id, "")
        segments.append(
            {
                "shape_xy": _rounded_shape(current.shape),
                "permissions": _lane_permissions(current),
                "width_m": current.width,
                "speed_mps": current.speed,
            }
        )
        candidates = outgoing.get((edge_id, current.ordinal), [])
        if len(candidates) != 1:
            failures.append(f"outgoing-count:{len(candidates)}")
            break
        continuation = candidates[0]
        if continuation.to_edge != direct.to_edge or continuation.to_lane != direct.to_lane:
            failures.append("target-mismatch")
        if continuation.via:
            next_lane = network.lanes.get(continuation.via)
            if next_lane is None:
                failures.append("continuation-not-found")
                break
            current = next_lane
            continue
        break
    else:
        failures.append("bounded-trace-exhausted")
    return {
        "status": "pass" if not failures else "invalid",
        "segments": segments,
        "failures": tuple(failures),
    }


def _rounded_shape(
    shape: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    return tuple((round(point[0], 6), round(point[1], 6)) for point in shape)


def _rounded_point(
    point: tuple[float | None, float | None],
) -> tuple[float | None, float | None]:
    return tuple(round(value, 6) if value is not None else None for value in point)
