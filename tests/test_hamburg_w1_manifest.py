from __future__ import annotations

import json
from pathlib import Path

import pytest

from torii_sumo.core.candidate_contracts import file_sha256
from torii_sumo.core.hamburg_w1_manifest import resolve_hamburg_w1_network


def _write_w1_manifest(path: Path, network: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "torii.hamburg-official-corridor-geometry/v1",
                "status": "review_ready",
                "execution_gate": "pass",
                "network": {
                    "path": network.name,
                    "sha256": file_sha256(network),
                },
            }
        ),
        encoding="utf-8",
    )


def test_w1_manifest_resolves_and_hash_checks_its_network(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    manifest = tmp_path / "W1.json"
    _write_w1_manifest(manifest, network)

    resolved, identity = resolve_hamburg_w1_network(
        w1_manifest_file=manifest,
        net_file=None,
    )

    assert resolved == network.resolve()
    assert identity == {
        "path": str(manifest.resolve()),
        "sha256": file_sha256(manifest),
    }

    network.write_text("<net id=\"mutated\"/>\n", encoding="utf-8")
    with pytest.raises(ValueError, match="W1 network SHA-256 mismatch"):
        resolve_hamburg_w1_network(w1_manifest_file=manifest, net_file=None)


def test_explicit_network_must_be_the_manifest_network(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    copied_network = tmp_path / "copied.net.xml"
    copied_network.write_bytes(network.read_bytes())
    manifest = tmp_path / "W1.json"
    _write_w1_manifest(manifest, network)

    with pytest.raises(ValueError, match="does not match the W1 manifest network path"):
        resolve_hamburg_w1_network(
            w1_manifest_file=manifest,
            net_file=copied_network,
        )


def test_w1_manifest_is_required_and_must_be_execution_ready(tmp_path: Path) -> None:
    network = tmp_path / "candidate.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")

    with pytest.raises(ValueError, match="w1_manifest_file is required"):
        resolve_hamburg_w1_network(w1_manifest_file=None, net_file=network)  # type: ignore[arg-type]

    manifest = tmp_path / "W1.json"
    _write_w1_manifest(manifest, network)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["execution_gate"] = "blocked"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="execution gate is not pass"):
        resolve_hamburg_w1_network(w1_manifest_file=manifest, net_file=network)
