import anyio


EXPECTED_TOOL_NAMES = sorted(
    [
        "sumo_get_environment",
        "sumo_preflight",
        "sumo_config_pair_preflight",
        "sumo_run_config",
        "sumo_run_minimal_smoke",
        "sumo_compare_outputs",
        "sumo_collect_evidence",
        "sumo_osm_resolve_place",
        "sumo_osm_cleanup_workflow",
        "sumo_osm_build_network",
        "sumo_tls_audit",
        "sumo_network_routeability_probe",
    ]
)


def test_package_imports() -> None:
    import torii_sumo

    assert torii_sumo.__version__ == "1.0.0"


def test_server_factory_imports() -> None:
    from torii_sumo.server import create_server

    server = create_server()
    assert server is not None


def test_server_registers_expected_tool_names() -> None:
    from torii_sumo.server import create_server

    async def _list_tool_names() -> list[str]:
        server = create_server()
        tools = await server.list_tools()
        return sorted(tool.name for tool in tools)

    assert anyio.run(_list_tool_names) == EXPECTED_TOOL_NAMES


def test_server_smoke_tool_reports_blocked_without_real_sumo(tmp_path) -> None:
    from torii_sumo.server import create_server

    async def _call_minimal_smoke() -> dict[str, object]:
        server = create_server()
        _content, structured = await server.call_tool(
            "sumo_run_minimal_smoke",
            {
                "work_dir": str(tmp_path),
                "require_real_sumo": False,
            },
        )
        return structured

    result = anyio.run(_call_minimal_smoke)

    assert result["status"] == "blocked"
    assert result["claim_status"] == "blocked"
    assert result["work_dir"] == str(tmp_path)
    assert result["commands"] == []
    assert result["artifacts"] == []
