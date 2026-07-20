from __future__ import annotations

import xml.etree.ElementTree as ET

from torii_sumo.road_network.official_splice_materializer import (
    _axis_node_at_station,
    _forbidden_intervals,
    _source_polygon_station_interval,
)


def test_two_direction_events_keep_both_splice_boundaries() -> None:
    corridor = "hh-sib-axis-example"
    events = [
        {
            "node_id": "2150",
            "axis_station_m": 58.555434,
            "junction_station_m": 320.638660,
        },
        {
            "node_id": "2150",
            "axis_station_m": 357.614654,
            "junction_station_m": 339.308953,
        },
    ]

    intervals = _forbidden_intervals({corridor: events})[corridor]

    # The old min/max shortcut expanded past both events and removed the
    # boundary fragments needed by the two directional bridge connections.
    assert intervals == [(58.555434, 357.614654)]


def test_event_at_source_endpoint_resolves_to_splice_node() -> None:
    source = ET.fromstring(
        '<edge id="axis" from="old-from" to="old-to">'
        '<param key="torii:station_direction" value="with_stationing"/>'
        '<param key="torii:station_from_m" value="0"/>'
        '<param key="torii:station_to_m" value="10"/>'
        '<lane id="axis_0" shape="0,0 10,0"/>'
        '</edge>'
    )

    node = _axis_node_at_station(
        source,
        0.0,
        corridor_id="hh-sib-axis-example",
        events=[{"axis_station_m": 0.0, "splice_node_id": "splice"}],
        cut_nodes={},
    )

    assert node == "splice"


def test_core_polygon_intersection_returns_axis_station_interval() -> None:
    source = ET.fromstring(
        '<edge id="axis" shape="0,0 10,0">'
        '<param key="torii:station_direction" value="with_stationing"/>'
        '<param key="torii:station_from_m" value="0"/>'
        '<param key="torii:station_to_m" value="10"/>'
        '</edge>'
    )

    interval = _source_polygon_station_interval(
        source,
        [(4.0, -1.0), (6.0, -1.0), (6.0, 1.0), (4.0, 1.0)],
    )

    assert interval == (4.0, 6.0)
