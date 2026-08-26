"""Bootstrap the Torii MCP stdio server without relying on the developer shell.

When the plugin is used from a repository checkout, this launcher delegates to
``uv run --frozen`` using the repository lockfile.  When the package is already
importable, it falls back to the installed ``torii_sumo.server`` module.  Both
paths use the same server implementation.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parent
SRC_ROOT = PLUGIN_ROOT / "src"


def _repo_start_command() -> list[str] | None:
    if not (REPO_ROOT / "pyproject.toml").is_file():
        return None
    uv = shutil.which("uv")
    if not uv:
        return None
    return [
        uv,
        "run",
        "--isolated",
        "--frozen",
        "--project",
        str(REPO_ROOT),
        "python",
        str(PLUGIN_ROOT / "scripts" / "run_torii_sumo.py"),
    ]


def _check() -> int:
    command = _repo_start_command()
    if command is None:
        if str(SRC_ROOT) not in sys.path:
            sys.path.insert(0, str(SRC_ROOT))
        try:
            import torii_sumo.server  # noqa: F401
        except Exception as exc:  # noqa: BLE001 - bootstrap diagnostics are user-facing.
            print(f"torii MCP bootstrap failed: {exc}", file=sys.stderr)
            return 2
        print("torii MCP bootstrap: installed-package fallback is available")
        return 0
    print("torii MCP bootstrap: uv run --frozen " + " ".join(command[2:]))
    return 0


def _start() -> int:
    os.environ.setdefault("TORII_MCP_PROFILE", "default")
    command = _repo_start_command()
    if command is not None:
        env = os.environ.copy()
        return subprocess.call(command, cwd=REPO_ROOT, env=env)
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from torii_sumo.server import main

    main()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the Torii MCP server.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the bootstrap path without starting the MCP server.",
    )
    args = parser.parse_args()
    return _check() if args.check else _start()


if __name__ == "__main__":
    raise SystemExit(main())
