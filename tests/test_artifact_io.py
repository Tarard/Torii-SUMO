from pathlib import Path

import pytest

from torii_sumo.core.artifact_io import write_json_atomic, write_text_atomic


def test_atomic_text_write_replaces_destination_without_temp_artifacts(tmp_path: Path) -> None:
    destination = tmp_path / "manifest.json"
    destination.write_text("old", encoding="utf-8")

    write_text_atomic(destination, "new")

    assert destination.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob(".manifest.json.*.tmp")) == []


def test_json_serialization_failure_preserves_existing_destination(tmp_path: Path) -> None:
    destination = tmp_path / "report.json"
    destination.write_text('{"status":"old"}', encoding="utf-8")

    with pytest.raises(TypeError):
        write_json_atomic(destination, {"invalid": {1, 2, 3}})

    assert destination.read_text(encoding="utf-8") == '{"status":"old"}'
    assert list(tmp_path.glob(".report.json.*.tmp")) == []
