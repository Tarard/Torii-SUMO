from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "torii-sumo"
BOOTSTRAP = PLUGIN / "scripts" / "bootstrap_mcp.py"


def _load_bootstrap() -> ModuleType:
    spec = importlib.util.spec_from_file_location("torii_mcp_bootstrap_regression", BOOTSTRAP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mcp_server_config() -> dict[str, Any]:
    config = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))
    return config["mcpServers"]["torii-sumo"]


def test_bootstrap_resolves_the_checkout_repository_root() -> None:
    bootstrap = _load_bootstrap()

    assert bootstrap.REPO_ROOT == ROOT
    assert (bootstrap.REPO_ROOT / "pyproject.toml").is_file()
    assert (bootstrap.REPO_ROOT / "uv.lock").is_file()


def test_mcp_config_does_not_launch_with_bare_python() -> None:
    server_config = _mcp_server_config()
    configured_executable = Path(server_config["command"]).stem.casefold()

    assert configured_executable != "python"


def test_bootstrap_uses_the_checkout_lock() -> None:
    bootstrap = _load_bootstrap()
    repo_command = bootstrap._repo_start_command()
    assert repo_command is not None
    assert "--frozen" in repo_command

    project_index = repo_command.index("--project")
    project_root = Path(repo_command[project_index + 1]).resolve()
    assert project_root == ROOT
    assert (project_root / "uv.lock").is_file()


def test_mcp_config_starts_default_profile_with_exactly_ten_tools() -> None:
    server_config = _mcp_server_config()
    environment = os.environ.copy()
    environment.pop("TORII_MCP_PROFILE", None)
    parameters = StdioServerParameters(
        command=server_config["command"],
        args=server_config.get("args", []),
        cwd=PLUGIN,
        env=environment,
    )

    async def initialize_and_list_tools() -> list[str]:
        with anyio.fail_after(30):
            async with stdio_client(parameters) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [tool.name for tool in result.tools]

    tool_names = anyio.run(initialize_and_list_tools)

    assert len(tool_names) == 10
    assert len(set(tool_names)) == 10
