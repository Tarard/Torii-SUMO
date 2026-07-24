"""Resolve the one hash-bound W1 network used by Hamburg downstream stages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .candidate_contracts import file_sha256


HAMBURG_W1_SCHEMA = "torii.hamburg-official-corridor-geometry/v1"


def resolve_hamburg_w1_network(
    *,
    w1_manifest_file: Path,
    net_file: Path | None,
) -> tuple[Path, dict[str, str]]:
    """Return the verified W1 network and the selected W1 manifest identity."""

    if w1_manifest_file is None:
        raise ValueError("w1_manifest_file is required; net_file is only a cross-check")

    manifest_path = Path(w1_manifest_file).expanduser().resolve(strict=True)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("W1 manifest is not valid JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("schema") != HAMBURG_W1_SCHEMA:
        raise ValueError("W1 manifest schema mismatch")
    if payload.get("execution_gate") != "pass":
        raise ValueError("W1 manifest execution gate is not pass")

    network = payload.get("network_binding") or payload.get("network")
    if not isinstance(network, Mapping):
        raise ValueError("W1 manifest has no network identity")
    raw_path = network.get("path")
    declared_sha256 = network.get("sha256")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("W1 network path is missing")
    if (
        not isinstance(declared_sha256, str)
        or len(declared_sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in declared_sha256)
    ):
        raise ValueError("W1 network SHA-256 is invalid")

    network_path = Path(raw_path).expanduser()
    if not network_path.is_absolute():
        network_path = manifest_path.parent / network_path
    network_path = network_path.resolve(strict=True)
    if file_sha256(network_path) != declared_sha256.lower():
        raise ValueError("W1 network SHA-256 mismatch")
    if net_file is not None and Path(net_file).expanduser().resolve(strict=True) != network_path:
        raise ValueError("net_file does not match the W1 manifest network path")

    return network_path, {
        "path": str(manifest_path),
        "sha256": file_sha256(manifest_path),
    }
