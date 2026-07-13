from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any


def write_json_atomic(
    path: Path,
    payload: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
    sort_keys: bool = False,
) -> None:
    """Serialize JSON completely before atomically replacing the destination."""
    text = json.dumps(
        payload,
        indent=indent,
        ensure_ascii=ensure_ascii,
        sort_keys=sort_keys,
    )
    write_text_atomic(path, text, encoding="utf-8")


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write a text artifact through a same-directory temporary file."""
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
            newline="",
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            # The original exception remains authoritative; a later run can
            # safely ignore a uniquely named temporary artifact.
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
