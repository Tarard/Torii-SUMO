from pathlib import Path

import pytest

from torii_sumo.core.artifact_io import (
    copy_file_atomic,
    relative_or_absolute_path,
    write_json_atomic,
    write_text_atomic,
)


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


def test_atomic_file_copy_replaces_destination_without_temp_artifacts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.net.xml"
    destination = tmp_path / "candidate.net.xml"
    source.write_bytes(b"new-network\x00content")
    destination.write_bytes(b"old-network")

    copy_file_atomic(source, destination)

    assert destination.read_bytes() == source.read_bytes()
    assert list(tmp_path.glob(".candidate.net.xml.*.tmp")) == []


def test_relative_path_falls_back_to_absolute_across_windows_drives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "candidate.net.xml"
    target.write_text("<net/>", encoding="utf-8")

    def cross_drive_failure(*_args, **_kwargs):
        raise ValueError("path is on a different drive")

    monkeypatch.setattr(
        "torii_sumo.core.artifact_io.os.path.relpath",
        cross_drive_failure,
    )

    assert relative_or_absolute_path(target, tmp_path / "output") == (target.resolve().as_posix())
