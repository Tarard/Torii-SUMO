from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any, Sequence
import xml.etree.ElementTree as ET


def audit_complete_osm_way_filter(
    *,
    source_osm_file: Path,
    filtered_osm_file: Path,
    acquisition_bbox: Sequence[float],
    allowed_highways: Sequence[str],
) -> dict[str, Any]:
    """Prove that filtering retained every selected OSM way without trimming it."""

    bbox = tuple(float(value) for value in acquisition_bbox)
    if len(bbox) != 4:
        raise ValueError("acquisition_bbox must contain west, south, east, north")
    allowed = {str(value) for value in allowed_highways}
    if not allowed:
        raise ValueError("allowed_highways must not be empty")

    source_root = _read_osm(source_osm_file)
    filtered_root = _read_osm(filtered_osm_file)
    source_nodes = _nodes(source_root)
    filtered_nodes = _nodes(filtered_root)
    source_ways = {
        way_id: signature
        for way in source_root.findall("way")
        if (way_id := way.attrib.get("id"))
        and _tag(way, "highway") in allowed
        and (signature := _way_signature(way))
    }
    filtered_ways = {
        way_id: signature
        for way in filtered_root.findall("way")
        if (way_id := way.attrib.get("id"))
        and _tag(way, "highway") in allowed
        and (signature := _way_signature(way))
    }
    missing_way_ids = sorted(source_ways.keys() - filtered_ways.keys(), key=_natural_key)
    extra_way_ids = sorted(filtered_ways.keys() - source_ways.keys(), key=_natural_key)
    modified_way_ids = sorted(
        (
            way_id
            for way_id in source_ways.keys() & filtered_ways.keys()
            if source_ways[way_id] != filtered_ways[way_id]
        ),
        key=_natural_key,
    )
    source_missing_node_refs = sorted(
        {
            node_id
            for refs, _tags in source_ways.values()
            for node_id in refs
            if node_id not in source_nodes
        },
        key=_natural_key,
    )
    filtered_missing_node_refs = sorted(
        {
            node_id
            for refs, _tags in filtered_ways.values()
            for node_id in refs
            if node_id not in filtered_nodes
        },
        key=_natural_key,
    )
    outside_way_ids = sorted(
        (
            way_id
            for way_id, (refs, _tags) in source_ways.items()
            if any(
                node_id in source_nodes
                and not _inside_bbox(source_nodes[node_id], bbox)
                for node_id in refs
            )
        ),
        key=_natural_key,
    )
    status = (
        "pass"
        if not (
            missing_way_ids
            or extra_way_ids
            or modified_way_ids
            or source_missing_node_refs
            or filtered_missing_node_refs
        )
        else "blocked"
    )
    return {
        "schema": "torii.complete-osm-way-filter-audit/v1",
        "status": status,
        "acquisition_bbox": list(bbox),
        "allowed_highways": sorted(allowed),
        "source_selected_way_count": len(source_ways),
        "filtered_selected_way_count": len(filtered_ways),
        "missing_way_count": len(missing_way_ids),
        "missing_way_ids": missing_way_ids,
        "extra_way_count": len(extra_way_ids),
        "extra_way_ids": extra_way_ids,
        "modified_way_count": len(modified_way_ids),
        "modified_way_ids": modified_way_ids,
        "source_missing_node_ref_count": len(source_missing_node_refs),
        "source_missing_node_refs": source_missing_node_refs,
        "filtered_missing_node_ref_count": len(filtered_missing_node_refs),
        "filtered_missing_node_refs": filtered_missing_node_refs,
        "ways_with_nodes_outside_bbox_count": len(outside_way_ids),
        "ways_with_nodes_outside_bbox_ids": outside_way_ids,
    }


def _read_osm(path: Path) -> ET.Element:
    source = Path(path).expanduser().resolve(strict=True)
    if source.suffix == ".gz":
        with gzip.open(source, "rb") as handle:
            root = ET.parse(handle).getroot()
    else:
        root = ET.parse(source).getroot()
    if root.tag != "osm":
        raise ValueError(f"OSM root must be <osm>, got <{root.tag}>")
    return root


def _nodes(root: ET.Element) -> dict[str, tuple[float, float]]:
    return {
        node_id: (float(node.attrib["lon"]), float(node.attrib["lat"]))
        for node in root.findall("node")
        if (node_id := node.attrib.get("id"))
        and "lon" in node.attrib
        and "lat" in node.attrib
    }


def _way_signature(
    way: ET.Element,
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    return (
        tuple(
            node.attrib["ref"]
            for node in way.findall("nd")
            if "ref" in node.attrib
        ),
        tuple(
            sorted(
                (tag.attrib["k"], tag.attrib.get("v", ""))
                for tag in way.findall("tag")
                if "k" in tag.attrib
            )
        ),
    )


def _tag(way: ET.Element, key: str) -> str | None:
    return next(
        (
            tag.attrib.get("v")
            for tag in way.findall("tag")
            if tag.attrib.get("k") == key
        ),
        None,
    )


def _inside_bbox(
    point: tuple[float, float],
    bbox: tuple[float, ...],
) -> bool:
    west, south, east, north = bbox
    lon, lat = point
    return west <= lon <= east and south <= lat <= north


def _natural_key(value: str) -> tuple[object, ...]:
    parts: list[object] = []
    token = ""
    numeric = value[:1].isdigit()
    for character in value:
        is_numeric = character.isdigit()
        if token and is_numeric != numeric:
            parts.append(int(token) if numeric else token)
            token = ""
        token += character
        numeric = is_numeric
    if token:
        parts.append(int(token) if numeric else token)
    return tuple(parts)
