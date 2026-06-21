# OSM Cleanup Hard Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a high-level Torii OSM cleanup workflow that enforces area confirmation, Google Maps/current-or-user-targeted map review, connectivity checks, and Netedit launch before stronger SUMO network claims.

**Architecture:** Keep the existing low-level tools reusable and add a high-level workflow layer above them. Add focused core helpers for passenger connectivity and Netedit launch, then expose one new MCP tool, `sumo_osm_cleanup_workflow`, that orchestrates existing OSM build, TLS audit, routeability, connectivity, and Netedit helpers.

**Tech Stack:** Python 3.11, standard-library XML parsing, pytest, FastMCP, existing Torii `torii_sumo.core` and `torii_sumo.tools` modules, SUMO `netconvert`/`netedit` as local executables.

---

## File Structure

- Create `plugins/torii-sumo/src/torii_sumo/core/connectivity.py`: passenger-edge connectivity summary for generated SUMO `.net.xml` files.
- Create `plugins/torii-sumo/src/torii_sumo/core/netedit.py`: non-blocking local Netedit launcher.
- Create `plugins/torii-sumo/src/torii_sumo/core/osm_workflow.py`: high-level OSM cleanup hard-gate workflow with dependency injection for tests.
- Modify `plugins/torii-sumo/src/torii_sumo/tools/osm_tools.py`: expose `sumo_osm_cleanup_workflow` and pass highway presets into the workflow.
- Modify `plugins/torii-sumo/src/torii_sumo/server.py`: register the new MCP tool.
- Modify `tests/test_docs_plugin_install.py`: keep internal superpowers docs out of public release surfaces without forbidding the internal docs directory.
- Modify `tests/test_imports.py`: include the new tool in expected MCP tool names.
- Modify `tests/test_osm_network_tools.py`: add connectivity, Netedit launcher, and workflow tests.
- Modify skill references in both root and bundled plugin skill trees: route OSM cleanup to the new high-level workflow.
- Modify public docs: README English/Chinese/German, install doc, skill integration doc, and docs site text.

## Task 1: Preserve Internal Planning Docs Boundary

**Files:**
- Modify: `tests/test_docs_plugin_install.py`
- Test: `tests/test_docs_plugin_install.py::test_internal_superpowers_plans_are_not_public_release_content`

- [ ] **Step 1: Write the failing boundary test**

Replace the existing `test_internal_superpowers_plans_are_not_public_release_content` function with:

```python
def test_internal_superpowers_plans_are_not_public_release_content() -> None:
    public_files = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        ROOT / "README.de.md",
        ROOT / "docs" / "index.html",
        ROOT / "docs" / "release" / "public-repo-manifest.md",
        ROOT / "docs" / "release" / "mailing-list-announcement.md",
        ROOT / "docs" / "release" / "linkedin-posts.md",
    ]

    for path in public_files:
        body = path.read_text(encoding="utf-8")
        assert "docs/superpowers" not in body
        assert "superpowers/plans" not in body
        assert "superpowers/specs" not in body
```

- [ ] **Step 2: Run the boundary test**

Run:

```powershell
python -m pytest tests/test_docs_plugin_install.py::test_internal_superpowers_plans_are_not_public_release_content -q
```

Expected: PASS. This test should pass because public release files do not link internal Superpowers specs or plans.

- [ ] **Step 3: Commit**

```powershell
git add tests/test_docs_plugin_install.py
git commit -m "test: allow internal planning docs without public exposure"
```

## Task 2: Add Passenger Connectivity Summary

**Files:**
- Create: `plugins/torii-sumo/src/torii_sumo/core/connectivity.py`
- Modify: `tests/test_osm_network_tools.py`
- Test: `tests/test_osm_network_tools.py::test_summarize_passenger_connectivity_passes_single_component`
- Test: `tests/test_osm_network_tools.py::test_summarize_passenger_connectivity_fails_disconnected_components`

- [ ] **Step 1: Write failing connectivity tests**

Add this import near the top of `tests/test_osm_network_tools.py`:

```python
from torii_sumo.core.connectivity import summarize_passenger_connectivity
```

Append these tests:

```python
def test_summarize_passenger_connectivity_passes_single_component(tmp_path: Path) -> None:
    net_file = tmp_path / "connected.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a" from="n0" to="n1">
    <lane id="a_0" allow="passenger" speed="13.9" length="10.0"/>
  </edge>
  <edge id="b" from="n1" to="n2">
    <lane id="b_0" allow="passenger" speed="13.9" length="10.0"/>
  </edge>
  <connection from="a" to="b"/>
</net>""",
        encoding="utf-8",
    )

    report = summarize_passenger_connectivity(net_file)

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["connectivity_status"] == "pass"
    assert report["passenger_edge_count"] == 2
    assert report["passenger_component_count"] == 1
    assert report["largest_component_edge_count"] == 2
    assert report["small_component_count"] == 0
    assert report["isolated_passenger_edge_count"] == 0
```

```python
def test_summarize_passenger_connectivity_fails_disconnected_components(tmp_path: Path) -> None:
    net_file = tmp_path / "disconnected.net.xml"
    net_file.write_text(
        """<net>
  <edge id="a" from="n0" to="n1">
    <lane id="a_0" allow="passenger" speed="13.9" length="10.0"/>
  </edge>
  <edge id="b" from="n2" to="n3">
    <lane id="b_0" allow="passenger" speed="13.9" length="10.0"/>
  </edge>
</net>""",
        encoding="utf-8",
    )

    report = summarize_passenger_connectivity(net_file)

    assert report["status"] == "fail"
    assert report["claim_status"] == "construction-invalid"
    assert report["connectivity_status"] == "fail"
    assert report["passenger_edge_count"] == 2
    assert report["passenger_component_count"] == 2
    assert report["largest_component_edge_count"] == 1
    assert report["small_component_count"] == 2
    assert report["isolated_passenger_edge_count"] == 2
    assert "passenger network has 2 disconnected components" in report["warnings"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_osm_network_tools.py::test_summarize_passenger_connectivity_passes_single_component tests/test_osm_network_tools.py::test_summarize_passenger_connectivity_fails_disconnected_components -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'torii_sumo.core.connectivity'`.

- [ ] **Step 3: Create connectivity implementation**

Create `plugins/torii-sumo/src/torii_sumo/core/connectivity.py` with:

```python
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .osm_network import read_net_edges


def _failure(error_message: str) -> dict[str, Any]:
    return {
        "status": "fail",
        "claim_status": "construction-invalid",
        "connectivity_status": "fail",
        "error": error_message,
    }


def _weak_components(edge_ids: set[str], connections: dict[str, set[str]]) -> list[set[str]]:
    neighbors = {edge_id: set() for edge_id in edge_ids}
    for from_edge, to_edges in connections.items():
        if from_edge not in edge_ids:
            continue
        for to_edge in to_edges:
            if to_edge not in edge_ids:
                continue
            neighbors[from_edge].add(to_edge)
            neighbors[to_edge].add(from_edge)

    remaining = set(edge_ids)
    components = []
    while remaining:
        start = remaining.pop()
        component = {start}
        queue: deque[str] = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in neighbors[current]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return components


def summarize_passenger_connectivity(
    net_file: Path,
    *,
    small_component_threshold: int = 3,
) -> dict[str, Any]:
    try:
        edges, connections = read_net_edges(net_file)
    except (OSError, ET.ParseError, KeyError, ValueError) as exc:
        return _failure(f"{type(exc).__name__}: {exc}")

    passenger_edges = {
        edge_id
        for edge_id, edge in edges.items()
        if edge.allows_passenger
    }
    if not passenger_edges:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "connectivity_status": "fail",
            "net_file": str(net_file),
            "passenger_edge_count": 0,
            "passenger_component_count": 0,
            "largest_component_edge_count": 0,
            "small_component_count": 0,
            "isolated_passenger_edge_count": 0,
            "warnings": ["network has no passenger-allowed edges"],
        }

    passenger_connections = {
        from_edge: {to_edge for to_edge in to_edges if to_edge in passenger_edges}
        for from_edge, to_edges in connections.items()
        if from_edge in passenger_edges
    }
    components = _weak_components(passenger_edges, passenger_connections)
    component_sizes = sorted((len(component) for component in components), reverse=True)
    connected_edges = set(passenger_connections)
    for to_edges in passenger_connections.values():
        connected_edges.update(to_edges)
    isolated_edges = passenger_edges - connected_edges
    small_components = [
        component
        for component in components
        if len(component) <= small_component_threshold
    ]

    warnings = []
    if len(components) != 1:
        warnings.append(f"passenger network has {len(components)} disconnected components")
    if isolated_edges:
        warnings.append(f"passenger network has {len(isolated_edges)} isolated passenger edges")

    ok = len(components) == 1 and not isolated_edges
    return {
        "status": "pass" if ok else "fail",
        "claim_status": "diagnostic-demo" if ok else "construction-invalid",
        "connectivity_status": "pass" if ok else "fail",
        "net_file": str(net_file),
        "passenger_edge_count": len(passenger_edges),
        "passenger_component_count": len(components),
        "largest_component_edge_count": component_sizes[0] if component_sizes else 0,
        "small_component_count": len(small_components),
        "isolated_passenger_edge_count": len(isolated_edges),
        "component_sizes": component_sizes,
        "warnings": warnings,
    }
```

- [ ] **Step 4: Run connectivity tests**

Run:

```powershell
python -m pytest tests/test_osm_network_tools.py::test_summarize_passenger_connectivity_passes_single_component tests/test_osm_network_tools.py::test_summarize_passenger_connectivity_fails_disconnected_components -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/connectivity.py tests/test_osm_network_tools.py
git commit -m "feat: add passenger connectivity summary"
```

## Task 3: Add Netedit Launcher

**Files:**
- Create: `plugins/torii-sumo/src/torii_sumo/core/netedit.py`
- Modify: `tests/test_osm_network_tools.py`
- Test: `tests/test_osm_network_tools.py::test_launch_netedit_reports_unavailable_when_binary_missing`
- Test: `tests/test_osm_network_tools.py::test_launch_netedit_starts_non_blocking_process`

- [ ] **Step 1: Write failing Netedit tests**

Add these tests to `tests/test_osm_network_tools.py`:

```python
def test_launch_netedit_reports_unavailable_when_binary_missing(tmp_path: Path) -> None:
    from torii_sumo.core.netedit import launch_netedit

    net_file = tmp_path / "network.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    report = launch_netedit(
        net_file,
        which_func=lambda _name: None,
    )

    assert report["status"] == "blocked"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["netedit_status"] == "unavailable"
    assert report["netedit_network_file"] == str(net_file)
    assert "netedit binary not found" in report["warnings"]
```

```python
def test_launch_netedit_starts_non_blocking_process(tmp_path: Path) -> None:
    from torii_sumo.core.netedit import launch_netedit

    class FakeProcess:
        pid = 12345

    calls: list[list[str]] = []

    def fake_popen(command, **kwargs):
        calls.append(command)
        assert kwargs["stdin"] is not None
        assert kwargs["stdout"] is not None
        assert kwargs["stderr"] is not None
        return FakeProcess()

    net_file = tmp_path / "network.net.xml"
    net_file.write_text("<net/>", encoding="utf-8")

    report = launch_netedit(
        net_file,
        which_func=lambda _name: "C:/SUMO/bin/netedit.exe",
        popen_func=fake_popen,
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["netedit_status"] == "opened"
    assert report["netedit_binary"] == "C:/SUMO/bin/netedit.exe"
    assert report["netedit_process_id"] == 12345
    assert calls == [["C:/SUMO/bin/netedit.exe", "-s", str(net_file)]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_osm_network_tools.py::test_launch_netedit_reports_unavailable_when_binary_missing tests/test_osm_network_tools.py::test_launch_netedit_starts_non_blocking_process -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'torii_sumo.core.netedit'`.

- [ ] **Step 3: Create Netedit launcher**

Create `plugins/torii-sumo/src/torii_sumo/core/netedit.py` with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import shutil
import subprocess


def launch_netedit(
    net_file: Path,
    *,
    netedit_binary: str = "netedit",
    which_func: Callable[[str], str | None] = shutil.which,
    popen_func: Callable[..., Any] = subprocess.Popen,
) -> dict[str, Any]:
    if not net_file.exists():
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "netedit_status": "failed",
            "netedit_binary": netedit_binary,
            "netedit_process_id": None,
            "netedit_window_title": "",
            "netedit_network_file": str(net_file),
            "warnings": [f"network file not found: {net_file}"],
        }

    resolved_binary = which_func(netedit_binary)
    if resolved_binary is None:
        return {
            "status": "blocked",
            "claim_status": "diagnostic-demo",
            "netedit_status": "unavailable",
            "netedit_binary": None,
            "netedit_process_id": None,
            "netedit_window_title": "",
            "netedit_network_file": str(net_file),
            "warnings": ["netedit binary not found"],
        }

    command = [resolved_binary, "-s", str(net_file)]
    try:
        process = popen_func(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return {
            "status": "fail",
            "claim_status": "diagnostic-demo",
            "netedit_status": "failed",
            "netedit_binary": resolved_binary,
            "netedit_process_id": None,
            "netedit_window_title": "",
            "netedit_network_file": str(net_file),
            "warnings": [f"{type(exc).__name__}: {exc}"],
        }

    return {
        "status": "pass",
        "claim_status": "diagnostic-demo",
        "netedit_status": "opened",
        "netedit_binary": resolved_binary,
        "netedit_process_id": process.pid,
        "netedit_window_title": "",
        "netedit_network_file": str(net_file),
        "warnings": [],
    }
```

- [ ] **Step 4: Run Netedit tests**

Run:

```powershell
python -m pytest tests/test_osm_network_tools.py::test_launch_netedit_reports_unavailable_when_binary_missing tests/test_osm_network_tools.py::test_launch_netedit_starts_non_blocking_process -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/netedit.py tests/test_osm_network_tools.py
git commit -m "feat: add netedit launch evidence"
```

## Task 4: Add High-Level OSM Cleanup Workflow

**Files:**
- Create: `plugins/torii-sumo/src/torii_sumo/core/osm_workflow.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/tools/osm_tools.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/server.py`
- Modify: `tests/test_osm_network_tools.py`
- Modify: `tests/test_imports.py`
- Test: `tests/test_osm_network_tools.py::test_osm_cleanup_workflow_blocks_unconfirmed_place_name`
- Test: `tests/test_osm_network_tools.py::test_osm_cleanup_workflow_runs_build_tls_connectivity_and_netedit`
- Test: `tests/test_osm_network_tools.py::test_osm_cleanup_workflow_preserves_historical_user_target`
- Test: `tests/test_imports.py::test_server_registers_expected_tool_names`

- [ ] **Step 1: Write failing workflow tests**

Add this import to `tests/test_osm_network_tools.py`:

```python
from torii_sumo.core.osm_workflow import run_osm_cleanup_workflow
```

Append these tests:

```python
def test_osm_cleanup_workflow_blocks_unconfirmed_place_name(tmp_path: Path) -> None:
    report = run_osm_cleanup_workflow(
        place_name="Altstadt, Dresden",
        output_dir=tmp_path,
    )

    assert report["status"] == "blocked"
    assert report["claim_status"] == "blocked"
    assert report["area_resolution_status"] == "needs_user_confirmation"
    assert report["area_input"] == "Altstadt, Dresden"
    assert report["user_confirmed_area"] == "no"
    assert "openstreetmap.org/search" in report["osm_preview_url"]
    assert report["gate_status"]["area_confirmation"] == "blocked"
```

```python
def test_osm_cleanup_workflow_runs_build_tls_connectivity_and_netedit(tmp_path: Path) -> None:
    net_file = tmp_path / "sumo" / "demo.net.xml"
    filtered_osm = tmp_path / "osm" / "demo_filtered.osm.xml.gz"

    def fake_build(**kwargs):
        net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": ["primary"],
            "warnings": [],
        }

    def fake_tls(**kwargs):
        assert kwargs["net_file"] == net_file
        assert kwargs["osm_file"] == filtered_osm
        assert kwargs["google_maps_temporal_scope"] == "current"
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 2,
            "tls_cluster_count": 1,
            "candidates_file": str(tmp_path / "tls_candidates.csv"),
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "google_maps_baseline": {
                "google_maps_baseline_source": "Google Maps",
                "google_maps_temporal_scope": "current",
                "google_maps_target_date": "",
                "google_maps_requires_time_confirmation": "no",
            },
            "warnings": [],
        }

    def fake_connectivity(net_path):
        assert net_path == net_file
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "connectivity_status": "pass",
            "passenger_edge_count": 3,
            "passenger_component_count": 1,
            "largest_component_edge_count": 3,
            "small_component_count": 0,
            "isolated_passenger_edge_count": 0,
            "warnings": [],
        }

    def fake_netedit(net_path):
        assert net_path == net_file
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "netedit_status": "opened",
            "netedit_binary": "netedit",
            "netedit_process_id": 100,
            "netedit_window_title": "",
            "netedit_network_file": str(net_file),
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="13.6,50.9,13.9,51.1",
        output_dir=tmp_path,
        prefix="demo",
        highway_classes={"primary"},
        build_func=fake_build,
        tls_audit_func=fake_tls,
        connectivity_func=fake_connectivity,
        netedit_func=fake_netedit,
    )

    assert report["status"] == "pass"
    assert report["claim_status"] == "diagnostic-demo"
    assert report["area_resolution_status"] == "confirmed_by_input"
    assert report["gate_status"] == {
        "area_confirmation": "pass",
        "network_build": "pass",
        "tls_reality_audit": "pass",
        "connectivity": "pass",
        "netedit": "pass",
    }
    assert report["tls_review_complete"] == "no"
    assert report["tls_needs_review_count"] == 1
    assert report["connectivity_status"] == "pass"
    assert report["netedit_status"] == "opened"
```

```python
def test_osm_cleanup_workflow_preserves_historical_user_target(tmp_path: Path) -> None:
    net_file = tmp_path / "sumo" / "historical.net.xml"
    filtered_osm = tmp_path / "osm" / "historical_filtered.osm.xml.gz"

    def fake_build(**kwargs):
        net_file.parent.mkdir(parents=True, exist_ok=True)
        filtered_osm.parent.mkdir(parents=True, exist_ok=True)
        net_file.write_text("<net/>", encoding="utf-8")
        filtered_osm.write_text("<osm/>", encoding="utf-8")
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "bbox": kwargs["bbox"],
            "net_file": str(net_file),
            "filtered_osm_file": str(filtered_osm),
            "source_osm_file": str(filtered_osm),
            "road_classes": ["primary"],
            "warnings": [],
        }

    captured = {}

    def fake_tls(**kwargs):
        captured.update(kwargs)
        return {
            "status": "pass",
            "claim_status": "diagnostic-demo",
            "tls_candidate_count": 0,
            "tls_cluster_count": 0,
            "candidates_file": str(tmp_path / "tls_candidates.csv"),
            "clusters_file": str(tmp_path / "tls_clusters.csv"),
            "google_maps_baseline": {
                "google_maps_baseline_source": "Google Maps",
                "google_maps_temporal_scope": "historical",
                "google_maps_target_date": "2019-06",
                "google_maps_requires_time_confirmation": "no",
            },
            "warnings": [],
        }

    report = run_osm_cleanup_workflow(
        bbox="13.6,50.9,13.9,51.1",
        output_dir=tmp_path,
        prefix="historical",
        map_temporal_scope="historical",
        map_target_date="2019-06",
        build_func=fake_build,
        tls_audit_func=fake_tls,
        connectivity_func=lambda _path: {"status": "pass", "connectivity_status": "pass", "claim_status": "diagnostic-demo", "warnings": []},
        netedit_func=lambda _path: {"status": "blocked", "netedit_status": "unavailable", "claim_status": "diagnostic-demo", "warnings": []},
    )

    assert captured["google_maps_temporal_scope"] == "historical"
    assert captured["google_maps_target_date"] == "2019-06"
    assert report["map_temporal_scope"] == "historical"
    assert report["map_target_date"] == "2019-06"
```

- [ ] **Step 2: Run workflow tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_osm_network_tools.py::test_osm_cleanup_workflow_blocks_unconfirmed_place_name tests/test_osm_network_tools.py::test_osm_cleanup_workflow_runs_build_tls_connectivity_and_netedit tests/test_osm_network_tools.py::test_osm_cleanup_workflow_preserves_historical_user_target -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'torii_sumo.core.osm_workflow'`.

- [ ] **Step 3: Create workflow implementation**

Create `plugins/torii-sumo/src/torii_sumo/core/osm_workflow.py` with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping
from urllib import parse

from .connectivity import summarize_passenger_connectivity
from .netedit import launch_netedit
from .osm_network import audit_tls, build_osm_network, build_routeability_probe


def _osm_preview_url(place_name: str) -> str:
    return "https://www.openstreetmap.org/search?" + parse.urlencode({"query": place_name})


def _blocked_place_report(place_name: str, output_dir: Path) -> dict[str, Any]:
    return {
        "status": "blocked",
        "claim_status": "blocked",
        "area_input": place_name,
        "area_resolution_status": "needs_user_confirmation",
        "candidate_display_name": "",
        "candidate_osm_type": "",
        "candidate_osm_id": "",
        "candidate_bbox": "",
        "osm_preview_url": _osm_preview_url(place_name),
        "user_confirmed_area": "no",
        "output_dir": str(output_dir),
        "gate_status": {
            "area_confirmation": "blocked",
            "network_build": "not_started",
            "tls_reality_audit": "not_started",
            "connectivity": "not_started",
            "netedit": "not_started",
        },
        "warnings": ["place-name input requires OSM preview and user confirmation before network construction"],
    }


def _gate_value(report: Mapping[str, Any]) -> str:
    status = str(report.get("status", "fail"))
    if status == "pass":
        return "pass"
    if status == "blocked":
        return "blocked"
    return "fail"


def _tls_review_summary(tls_report: Mapping[str, Any]) -> dict[str, Any]:
    cluster_count = int(tls_report.get("tls_cluster_count", 0) or 0)
    candidate_count = int(tls_report.get("tls_candidate_count", 0) or 0)
    return {
        "tls_candidate_count": candidate_count,
        "tls_cluster_count": cluster_count,
        "tls_review_file": str(tls_report.get("clusters_file", "")),
        "tls_review_complete": "yes" if cluster_count == 0 and candidate_count == 0 else "no",
        "tls_keep_count": 0,
        "tls_remove_count": 0,
        "tls_downgrade_count": 0,
        "tls_needs_review_count": cluster_count,
    }


def run_osm_cleanup_workflow(
    *,
    output_dir: Path,
    bbox: str | None = None,
    place_name: str | None = None,
    confirmed_area: bool = False,
    prefix: str = "sumo_osm_cleanup",
    source_osm_path: Path | None = None,
    highway_classes: set[str] | None = None,
    historical_date: str | None = None,
    overpass_url: str = "https://overpass-api.de/api/interpreter",
    timeout_seconds: float = 240.0,
    max_tile_area_km2: float = 2500.0,
    max_retries: int = 2,
    retry_pause_seconds: float = 5.0,
    map_temporal_scope: str = "current",
    map_target_date: str | None = None,
    launch_netedit_after_build: bool = True,
    key_edge_queries: list[Mapping[str, Any]] | None = None,
    build_func: Callable[..., dict[str, Any]] = build_osm_network,
    tls_audit_func: Callable[..., dict[str, Any]] = audit_tls,
    connectivity_func: Callable[[Path], dict[str, Any]] = summarize_passenger_connectivity,
    routeability_func: Callable[..., dict[str, Any]] = build_routeability_probe,
    netedit_func: Callable[[Path], dict[str, Any]] = launch_netedit,
) -> dict[str, Any]:
    cleaned_place_name = (place_name or "").strip()
    if cleaned_place_name and not confirmed_area and not bbox and source_osm_path is None:
        return _blocked_place_report(cleaned_place_name, output_dir)
    if not bbox:
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "area_input": cleaned_place_name,
            "area_resolution_status": "blocked",
            "warnings": ["bbox is required for OSM network construction"],
        }

    area_status = "confirmed_by_user" if cleaned_place_name and confirmed_area else "confirmed_by_input"
    build_report = build_func(
        bbox=bbox,
        output_dir=output_dir,
        prefix=prefix,
        source_osm_path=source_osm_path,
        allowed_highways=highway_classes,
        historical_date=historical_date,
        overpass_url=overpass_url,
        timeout_seconds=timeout_seconds,
        max_tile_area_km2=max_tile_area_km2,
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
    )
    if build_report.get("status") != "pass":
        return {
            "status": "fail",
            "claim_status": "construction-invalid",
            "area_input": cleaned_place_name or bbox,
            "area_resolution_status": area_status,
            "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
            "build": build_report,
            "gate_status": {
                "area_confirmation": "pass",
                "network_build": _gate_value(build_report),
                "tls_reality_audit": "not_started",
                "connectivity": "not_started",
                "netedit": "not_started",
            },
            "warnings": list(build_report.get("warnings", [])),
        }

    net_file = Path(str(build_report["net_file"]))
    filtered_osm_value = build_report.get("filtered_osm_file") or build_report.get("source_osm_file")
    osm_file = Path(str(filtered_osm_value)) if filtered_osm_value else None
    tls_report = tls_audit_func(
        net_file=net_file,
        output_dir=output_dir / "tls_audit",
        prefix=f"{prefix}_tls_audit",
        osm_file=osm_file,
        google_maps_temporal_scope=map_temporal_scope,
        google_maps_target_date=map_target_date,
    )
    connectivity_report = connectivity_func(net_file)
    routeability_report = None
    if key_edge_queries:
        routeability_report = routeability_func(
            net_file=net_file,
            output_dir=output_dir / "routeability",
            prefix=f"{prefix}_routeability",
            key_edge_queries=key_edge_queries,
        )
    if launch_netedit_after_build:
        netedit_report = netedit_func(net_file)
    else:
        netedit_report = {
            "status": "blocked",
            "claim_status": "diagnostic-demo",
            "netedit_status": "skipped",
            "netedit_network_file": str(net_file),
            "warnings": ["netedit launch disabled by caller"],
        }

    tls_summary = _tls_review_summary(tls_report)
    warnings = []
    for child in (build_report, tls_report, connectivity_report, netedit_report):
        warnings.extend(str(item) for item in child.get("warnings", []))
    if tls_summary["tls_review_complete"] == "no":
        warnings.append("TLS reality review still requires human Google Maps/current-or-user-targeted map inspection")

    gate_status = {
        "area_confirmation": "pass",
        "network_build": _gate_value(build_report),
        "tls_reality_audit": _gate_value(tls_report),
        "connectivity": _gate_value(connectivity_report),
        "netedit": _gate_value(netedit_report),
    }
    workflow_ok = (
        gate_status["network_build"] == "pass"
        and gate_status["tls_reality_audit"] == "pass"
        and gate_status["connectivity"] == "pass"
        and gate_status["netedit"] in {"pass", "blocked"}
    )
    return {
        "status": "pass" if workflow_ok else "fail",
        "claim_status": "diagnostic-demo" if workflow_ok else "construction-invalid",
        "area_input": cleaned_place_name or bbox,
        "area_resolution_status": area_status,
        "candidate_display_name": "",
        "candidate_osm_type": "",
        "candidate_osm_id": "",
        "candidate_bbox": bbox,
        "osm_preview_url": _osm_preview_url(cleaned_place_name) if cleaned_place_name else "",
        "user_confirmed_area": "yes" if area_status == "confirmed_by_user" else "confirmed_by_input",
        "map_baseline_source": "Google Maps",
        "map_temporal_scope": map_temporal_scope,
        "map_target_date": map_target_date or "",
        **tls_summary,
        "connectivity_status": connectivity_report.get("connectivity_status", connectivity_report.get("status", "fail")),
        "passenger_edge_count": connectivity_report.get("passenger_edge_count", 0),
        "passenger_component_count": connectivity_report.get("passenger_component_count", 0),
        "largest_component_edge_count": connectivity_report.get("largest_component_edge_count", 0),
        "small_component_count": connectivity_report.get("small_component_count", 0),
        "isolated_passenger_edge_count": connectivity_report.get("isolated_passenger_edge_count", 0),
        "routeability_probe_file": "" if routeability_report is None else str(routeability_report.get("sumocfg_file", "")),
        "missing_key_edges": [] if routeability_report is None else routeability_report.get("missing_key_edges", []),
        "routeability_probe_status": "skipped" if routeability_report is None else routeability_report.get("status", "fail"),
        "netedit_status": netedit_report.get("netedit_status", "failed"),
        "netedit_binary": netedit_report.get("netedit_binary"),
        "netedit_process_id": netedit_report.get("netedit_process_id"),
        "netedit_window_title": netedit_report.get("netedit_window_title", ""),
        "netedit_network_file": netedit_report.get("netedit_network_file", str(net_file)),
        "net_file": str(net_file),
        "filtered_osm_file": str(filtered_osm_value) if filtered_osm_value else "",
        "build": build_report,
        "tls_audit": tls_report,
        "connectivity": connectivity_report,
        "netedit": netedit_report,
        "gate_status": gate_status,
        "warnings": warnings,
    }
```

- [ ] **Step 4: Expose workflow in tool wrapper**

Modify `plugins/torii-sumo/src/torii_sumo/tools/osm_tools.py` imports:

```python
from torii_sumo.core.osm_workflow import run_osm_cleanup_workflow
```

Add this function below `sumo_network_routeability_probe`:

```python
def sumo_osm_cleanup_workflow(
    output_dir: str,
    bbox: str | None = None,
    place_name: str | None = None,
    confirmed_area: bool = False,
    prefix: str = "sumo_osm_cleanup",
    source_osm_path: str | None = None,
    highway_classes: str | None = None,
    historical_date: str | None = None,
    overpass_url: str = "https://overpass-api.de/api/interpreter",
    timeout_seconds: float = 240.0,
    max_tile_area_km2: float = 2500.0,
    max_retries: int = 2,
    retry_pause_seconds: float = 5.0,
    map_temporal_scope: str = "current",
    map_target_date: str | None = None,
    launch_netedit_after_build: bool = True,
    key_edge_queries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return run_osm_cleanup_workflow(
        output_dir=Path(output_dir),
        bbox=bbox,
        place_name=place_name,
        confirmed_area=confirmed_area,
        prefix=prefix,
        source_osm_path=Path(source_osm_path) if source_osm_path else None,
        highway_classes=resolve_highway_classes(highway_classes),
        historical_date=historical_date,
        overpass_url=overpass_url,
        timeout_seconds=timeout_seconds,
        max_tile_area_km2=max_tile_area_km2,
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        map_temporal_scope=map_temporal_scope,
        map_target_date=map_target_date,
        launch_netedit_after_build=launch_netedit_after_build,
        key_edge_queries=key_edge_queries,
    )
```

- [ ] **Step 5: Register MCP tool**

Modify `plugins/torii-sumo/src/torii_sumo/server.py` import block to include `sumo_osm_cleanup_workflow`:

```python
from .tools.osm_tools import (
    sumo_network_routeability_probe,
    sumo_osm_build_network,
    sumo_osm_cleanup_workflow,
    sumo_tls_audit,
)
```

Register it before the low-level OSM build tool:

```python
    server.tool(description="Run the OSM cleanup hard-gate workflow: area confirmation, OSM build, TLS map audit, connectivity check, and Netedit launch.")(
        sumo_osm_cleanup_workflow
    )
```

- [ ] **Step 6: Update MCP expected tool list**

Modify `tests/test_imports.py` to include the new tool:

```python
        "sumo_osm_cleanup_workflow",
```

Place it before `"sumo_osm_build_network"` in `EXPECTED_TOOL_NAMES`.

- [ ] **Step 7: Run workflow and MCP registration tests**

Run:

```powershell
python -m pytest tests/test_osm_network_tools.py::test_osm_cleanup_workflow_blocks_unconfirmed_place_name tests/test_osm_network_tools.py::test_osm_cleanup_workflow_runs_build_tls_connectivity_and_netedit tests/test_osm_network_tools.py::test_osm_cleanup_workflow_preserves_historical_user_target tests/test_imports.py::test_server_registers_expected_tool_names -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/osm_workflow.py plugins/torii-sumo/src/torii_sumo/tools/osm_tools.py plugins/torii-sumo/src/torii_sumo/server.py tests/test_osm_network_tools.py tests/test_imports.py
git commit -m "feat: add OSM cleanup hard-gate workflow"
```

## Task 5: Update Skill Routing and Public Docs

**Files:**
- Modify: `skills/simulation-helper-skill-for-eclipse-sumo/SKILL.md`
- Modify: `skills/simulation-helper-skill-for-eclipse-sumo/references/model-osm-detectors.md`
- Modify: `skills/simulation-helper-skill-for-eclipse-sumo/references/mcp-tool-routing.md`
- Modify: `plugins/torii-sumo/skills/simulation-helper-skill-for-eclipse-sumo/SKILL.md`
- Modify: `plugins/torii-sumo/skills/simulation-helper-skill-for-eclipse-sumo/references/model-osm-detectors.md`
- Modify: `plugins/torii-sumo/skills/simulation-helper-skill-for-eclipse-sumo/references/mcp-tool-routing.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `README.de.md`
- Modify: `docs/codex-plugin-install.md`
- Modify: `docs/skill-integration.md`
- Modify: `docs/index.html`
- Modify: `tests/test_bundled_sumo_skill.py`
- Modify: `tests/test_docs_plugin_install.py`

- [ ] **Step 1: Extend doc tests first**

Add assertions to `test_plugin_install_doc_explains_marketplace_and_new_thread` in `tests/test_docs_plugin_install.py`:

```python
    assert "sumo_osm_cleanup_workflow" in doc
    assert "area confirmation" in doc
    assert "Netedit" in doc
```

Add assertions to `test_skill_routes_osm_source_patterns_and_google_maps_temporal_baseline` in `tests/test_bundled_sumo_skill.py`:

```python
    assert "sumo_osm_cleanup_workflow" in model_reference
    assert "area confirmation" in model_reference
    assert "Netedit" in model_reference
    assert "user's stated historical target controls the baseline" in model_reference
```

- [ ] **Step 2: Run doc tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_docs_plugin_install.py::test_plugin_install_doc_explains_marketplace_and_new_thread tests/test_bundled_sumo_skill.py::test_skill_routes_osm_source_patterns_and_google_maps_temporal_baseline -q
```

Expected: FAIL because docs do not yet mention the new workflow and hard gates.

- [ ] **Step 3: Update skill routing text**

In both `skills/.../SKILL.md` and `plugins/torii-sumo/skills/.../SKILL.md`, update the row for paper-area OSM modeling to point to `references/model-osm-detectors.md` and mention hard gates. Use this wording in the expected-output cell:

```text
OSM cleanup hard-gate workflow, area confirmation, Google Maps/current-or-user-targeted TLS audit, connectivity check, Netedit launch, and claim boundary.
```

In both `model-osm-detectors.md` files, add this section after "Construction Plan Gate":

```markdown
## OSM Cleanup Hard Gates

For OSM-to-SUMO network construction, default to the high-level `sumo_osm_cleanup_workflow` when the Torii MCP tools are available. Do not treat `netconvert` success as enough evidence that the SUMO network is real.

Hard gates:

1. If the user gives only a place name, produce an OSM preview checkpoint and ask the user to confirm the area before construction.
2. After construction, run TLS candidate extraction and Google Maps review-link generation by default.
3. For current-network modeling, Google Maps is the default reality baseline. If the user asks for a historical network, the user's stated historical target controls the baseline; use time-aligned Google Maps evidence, OSM history, dated imagery, Street View history, or agency inventory where available.
4. Run passenger connectivity checks before making stronger claims.
5. Open the cleaned network in Netedit and report launch evidence.

If any gate is incomplete, keep the claim at `diagnostic-demo`, `construction-invalid`, or `blocked`. GUI inspection, Google Maps links, and clean SUMO loading do not prove timing, phasing, demand realism, or controller readiness.
```

In both `mcp-tool-routing.md` files, add this row before the `sumo_osm_build_network` row:

```markdown
| Need OSM cleanup from place name, bbox, or extract with mandatory gates | `sumo_osm_cleanup_workflow` | Enforce area confirmation, OSM build, Google Maps/current-or-user-targeted TLS audit, passenger connectivity, optional routeability probes, Netedit launch, and claim boundary |
```

Also update the "current OSM tools cover..." paragraph to include:

```text
The high-level cleanup workflow coordinates these tools and blocks or demotes claims when area confirmation, map/TLS review, connectivity, or Netedit inspection evidence is missing.
```

- [ ] **Step 4: Update README and install docs**

In `README.md`, update the "What You Can Ask" table:

```markdown
| "Build a SUMO network from this OSM area." | Use the OSM cleanup hard-gate workflow: area confirmation when needed, bounded OSM import, TLS map audit, passenger connectivity check, and Netedit launch evidence. |
| "Clean this Dresden core network." | If a bbox or extract is supplied, run the hard-gate workflow directly. If only a place name is supplied, produce an OSM preview checkpoint and ask the user to confirm the area before construction. |
```

In `README.md`, add a tool row before `sumo_osm_build_network`:

```markdown
| `sumo_osm_cleanup_workflow` | High-level OSM cleanup workflow with area confirmation, OSM build, TLS map audit, connectivity check, and Netedit launch evidence. |
```

In `README.md`, update "Current Boundaries" bullets:

```markdown
- It can build SUMO networks from supplied bbox/extract inputs and can block on unconfirmed place-name areas; fully automatic place-name geocoding remains a workflow checkpoint rather than a silent construction step.
- It can assist OSM cleanup with road-class selection, deduplication, TLS candidates, Google Maps/current-or-user-targeted review artifacts, connectivity checks, routeability probes, and Netedit launch evidence; it does not certify a whole city network automatically.
- It uses Google Maps as the default current-network reality baseline. If the user requests a historical network, the user's stated historical target controls the baseline and requires time-aligned evidence.
```

Apply equivalent content to `README.zh-CN.md`:

```markdown
| “用这块 OSM 区域构建 SUMO 路网。” | 使用 OSM 清洗硬门槛流程：必要时先确认区域，再执行受限 OSM 导入、TLS 地图审计、客车路网连接性检查和 Netedit 打开证据。 |
| “清洗德雷斯顿核心区路网。” | 如果给了 bbox 或 extract，就直接运行硬门槛流程；如果只有地名，就先生成 OSM 预览检查点并让用户确认区域。 |
| `sumo_osm_cleanup_workflow` | 高层 OSM 清洗流程，包含区域确认、OSM 构网、TLS 地图审计、连接性检查和 Netedit 打开证据。 |
```

Apply equivalent content to `README.de.md`:

```markdown
| "Ein SUMO-Netz aus diesem OSM-Gebiet bauen." | Nutzt den OSM-Cleanup-Hard-Gate-Workflow: Gebietsbestaetigung bei Bedarf, begrenzter OSM-Import, TLS-Kartenpruefung, Pkw-Netz-Konnektivitaet und Netedit-Startnachweis. |
| "Dieses Dresdner Kernnetz bereinigen." | Bei bbox oder Extract wird der Hard-Gate-Workflow direkt ausgefuehrt. Bei nur einem Ortsnamen erzeugt Torii zuerst einen OSM-Vorschaupunkt und fragt nach Bestaetigung. |
| `sumo_osm_cleanup_workflow` | High-Level-Workflow fuer OSM-Cleanup mit Gebietsbestaetigung, OSM-Netzaufbau, TLS-Kartenpruefung, Konnektivitaetscheck und Netedit-Startnachweis. |
```

In `docs/codex-plugin-install.md`, add `sumo_osm_cleanup_workflow` to the implemented OSM/network tools list:

```markdown
- `sumo_osm_cleanup_workflow`: run the hard-gate OSM cleanup workflow, including area confirmation when needed, network construction, TLS map audit, passenger connectivity summary, routeability probes when supplied, and Netedit launch evidence.
```

In `docs/skill-integration.md`, update the OSM routing bullets:

```markdown
- OSM cleanup from place name, bbox, or extract => `sumo_osm_cleanup_workflow`, then inspect area confirmation, Google Maps/current-or-user-targeted TLS audit artifacts, connectivity status, Netedit launch evidence, and claim boundary.
```

- [ ] **Step 5: Update docs site text**

In `docs/index.html`, replace the English `painThree`, `scopeText`, and `futureText` values with:

```javascript
painThree: "OSM cleanup needs area confirmation, map/TLS reality review, connectivity checks, and Netedit inspection before stronger claims.",
scopeText: "Current tools cover bounded environment checks, config preflight, smoke runs, evidence bundles, hard-gate OSM cleanup, TLS audit candidates, connectivity checks, routeability probes, and Netedit launch evidence.",
futureText: "Fully automatic place-name geocoding, full city-scale certification, max-pressure controller generation, and controller-log inspection are roadmap tools, not finished promises.",
```

Replace the Chinese values with:

```javascript
painThree: "OSM 清洗需要先确认区域，再做地图/TLS 现实审查、连接性检查和 Netedit 人工检查入口，之后才能升级结论。",
scopeText: "当前工具覆盖环境检查、配置预检、冒烟运行、证据包、OSM 清洗硬门槛流程、TLS 候选审计、连接性检查、路线可达性 probes 和 Netedit 打开证据。",
futureText: "完整自动地名解析、整城级自动认证、max-pressure 控制器生成和控制器日志审查仍是路线图工具，不是已完成承诺。",
```

Replace the German values with ASCII-safe text:

```javascript
painThree: "OSM-Cleanup braucht Gebietsbestaetigung, Karten/TLS-Realitaetspruefung, Konnektivitaetschecks und Netedit-Inspektion, bevor staerkere Aussagen moeglich sind.",
scopeText: "Aktuelle Werkzeuge decken Umgebungstests, Konfigurationspruefung, Smoke Runs, Evidenzpakete, OSM-Cleanup-Hard-Gates, TLS-Kandidaten, Konnektivitaetschecks, Erreichbarkeitsproben und Netedit-Startnachweise ab.",
futureText: "Vollautomatische Ortsnamen-Geokodierung, vollstaendige Stadtzertifizierung, Max-Pressure-Controller-Erzeugung und Controller-Log-Pruefung sind Roadmap-Werkzeuge, keine fertigen Versprechen.",
```

- [ ] **Step 6: Run doc tests**

Run:

```powershell
python -m pytest tests/test_docs_plugin_install.py tests/test_bundled_sumo_skill.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add skills/simulation-helper-skill-for-eclipse-sumo/SKILL.md skills/simulation-helper-skill-for-eclipse-sumo/references/model-osm-detectors.md skills/simulation-helper-skill-for-eclipse-sumo/references/mcp-tool-routing.md plugins/torii-sumo/skills/simulation-helper-skill-for-eclipse-sumo/SKILL.md plugins/torii-sumo/skills/simulation-helper-skill-for-eclipse-sumo/references/model-osm-detectors.md plugins/torii-sumo/skills/simulation-helper-skill-for-eclipse-sumo/references/mcp-tool-routing.md README.md README.zh-CN.md README.de.md docs/codex-plugin-install.md docs/skill-integration.md docs/index.html tests/test_bundled_sumo_skill.py tests/test_docs_plugin_install.py
git commit -m "docs: route OSM cleanup through hard gates"
```

## Task 6: Full Verification and Release-Boundary Check

**Files:**
- No new source files
- Verify all changed files

- [ ] **Step 1: Run full tests**

Run:

```powershell
python -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 3: Check public/private boundary**

Run:

```powershell
rg -n "AgiMo|huqio|Documents\\\\|E:\\\\|docs/superpowers|superpowers/plans|superpowers/specs" README.md README.zh-CN.md README.de.md docs plugins/torii-sumo/skills skills
```

Expected: no hits in public docs/skills except the command output may show internal plan/spec files when searching `docs/superpowers`; rerun the command without `docs/superpowers` if needed:

```powershell
rg -n "AgiMo|huqio|Documents\\\\|E:\\\\|docs/superpowers|superpowers/plans|superpowers/specs" README.md README.zh-CN.md README.de.md docs/codex-plugin-install.md docs/skill-integration.md docs/index.html plugins/torii-sumo/skills skills
```

Expected: no output.

- [ ] **Step 4: Inspect final diff**

Run:

```powershell
git diff --stat HEAD~5..HEAD
git status --short --branch
```

Expected: branch is ahead by the implementation commits and working tree is clean.

- [ ] **Step 5: Handle verification-only edits**

If Task 6 reveals a typo or test expectation bug, return to the task that owns that file, apply the concrete fix there, rerun that task's test command, and use that task's commit command. If no files changed, do not create an empty commit.

## Self-Review

Spec coverage:

- Area confirmation is covered by Task 4 tests and workflow behavior.
- Google Maps/current-or-user-targeted baseline is covered by Task 4 historical test and Task 5 docs updates.
- Connectivity gate is covered by Task 2 helper and Task 4 workflow integration.
- Netedit launch is covered by Task 3 launcher and Task 4 workflow integration.
- Public/private boundary and docs sync are covered by Tasks 1, 5, and 6.

Placeholder scan:

- No unresolved placeholder text is intentionally present.
- All test commands and commit commands are explicit.

Type consistency:

- The public tool name is consistently `sumo_osm_cleanup_workflow`.
- The core function name is consistently `run_osm_cleanup_workflow`.
- The connectivity function is consistently `summarize_passenger_connectivity`.
- The Netedit function is consistently `launch_netedit`.
