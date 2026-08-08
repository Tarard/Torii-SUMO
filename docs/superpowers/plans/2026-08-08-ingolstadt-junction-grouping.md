# Ingolstadt 路口与道路分组实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对 Ingolstadt 全城清单中的每个教师适用路口和候选独有路口建立可恢复、可核对的分类与分组，并让当前 Torii 对每组代表项完成一次真实重建和验证。

**Architecture:** 保留现有 `archetype_profile`、`road_detail` 和 `junction_rebuild_candidate` 为唯一分类与重建主流程。新增一个小型分组模块和一个命令行入口。入口只读取一次 OSM、教师网、候选网和全城清单；分类模块复用一次建立的车辆图，并用清单中的已审核来源节点构造 physical cell。分类结果写入 JSONL，再按短分组键选择确定的代表项。代表项复用现有教师引导队列、重建矩阵和 NetEdit 视觉门，不另写重建器或截图器。

**Tech Stack:** Python 3.13、标准库、现有 Torii/SUMO/NetEdit 命令行、pytest、JSON/JSONL。

---

## 实施边界

- 工作分支保持为 `codex/tum-style-teach`。
- 不改写现有路口类别词表，不新增依赖，不引入资料库或任务服务。
- 优先使用 NetEdit CLI。只有 CLI 无法完成已有操作时才使用 MCP。
- 当前工作区已有改动不得混入本计划的提交。每次只暂存本任务列出的文件。
- 教师网的组合成员只作为分类证据。它们不自动授权修改候选网。
- 分组阶段完成不等于全城完成。最终仍须通过逐区视觉、结构、SUMO 全网载入和全局可达性检查。

## Task 1：让 physical-cell 推断复用全城车辆图

**Files:**

- Modify: `plugins/torii-sumo/src/torii_sumo/intersection/physical_cell.py`
- Modify: `tests/intersection/test_review_proposal.py`

- [ ] **Step 1: 写一个失败检查，证明单节点和组合来源节点都能复用同一车辆图**

在 `tests/intersection/test_review_proposal.py` 增加两个小检查：

```python
def test_signal_anchor_cell_accepts_prebuilt_vehicle_graph() -> None:
    patch = _four_arm_signal_patch()
    graph_data = build_osm_vehicle_graph(patch)

    expected = infer_signal_anchor_physical_cell(patch, seed_node_id="1")
    actual = infer_signal_anchor_physical_cell(
        patch,
        seed_node_id="1",
        vehicle_graph=graph_data,
    )

    assert actual == expected


def test_reviewed_source_cell_keeps_exact_compound_members_and_boundary_arms() -> None:
    patch = _compound_patch()
    result = infer_reviewed_source_physical_cell(
        patch,
        source_node_ids=["2", "3"],
        vehicle_graph=build_osm_vehicle_graph(patch),
    )

    assert result["reviewed_source_node_ids"] == ["2", "3"]
    assert {"2", "3"} <= set(result["path_closure_node_ids"])
    assert result["automatic_promotion_gate"] == "blocked"
    assert len(result["physical_approaches"]) == 4
```

- [ ] **Step 2: 运行检查并确认失败原因是缺少新参数和新函数**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/intersection/test_review_proposal.py -k "prebuilt_vehicle_graph or reviewed_source_cell" -q
```

Expected: FAIL，报告 `vehicle_graph` 参数或 `infer_reviewed_source_physical_cell` 不存在。

- [ ] **Step 3: 最小实现复用车辆图**

在 `physical_cell.py` 中：

1. 给 `infer_signal_anchor_physical_cell` 增加可选参数：

```python
vehicle_graph: tuple[dict[str, list[tuple[str, float, str]]], set[str], int] | None = None,
```

2. 用现有结果或一次新建结果：

```python
graph, vehicle_way_ids, max_lane_count = (
    vehicle_graph if vehicle_graph is not None else build_osm_vehicle_graph(patch)
)
```

3. 给 `shortest_paths` 增加 `maximum_distance_m: float | None = None`。从堆中取出距离超过上限时停止；准备加入的新距离超过上限时跳过。
4. 新增 `infer_reviewed_source_physical_cell(...)`。它必须：
   - 校验来源列表非空、去重后全部存在于 `patch.nodes`；
   - 单节点时不运行全城最短路；
   - 组合节点时从排序后的首节点出发，只在自适应半径内连接已审核成员；
   - 复用 `_complete_bounded_way_shapes`、`_boundary_ports`、`_group_boundary_ports` 和现有稳定摘要方法；
   - 保存 `reviewed_source_node_ids`、`path_closure_node_ids`、`physical_approaches`、风险与证据；
   - 固定 `automatic_promotion_gate="blocked"`。

不要建立新的图类。`build_osm_vehicle_graph` 的现有三元组已经足够。

- [ ] **Step 4: 运行局部和相邻检查**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/intersection/test_review_proposal.py tests/intersection/test_archetype_profile.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交本任务**

```powershell
git add plugins/torii-sumo/src/torii_sumo/intersection/physical_cell.py tests/intersection/test_review_proposal.py
git commit -m "feat: reuse physical cell graph for city grouping"
```

## Task 2：把全城清单规范成逐路口分类记录

**Files:**

- Create: `plugins/torii-sumo/src/torii_sumo/core/junction_grouping.py`
- Create: `tests/test_junction_grouping.py`

- [ ] **Step 1: 写失败检查，锁定清单守恒和来源节点解析**

测试使用最小内存清单，覆盖 `ready`、`blocked`、`teacher_only`、`ambiguous` 和 `candidate_only`：

```python
def test_manifest_records_preserve_both_sides_without_duplicates() -> None:
    records = manifest_junction_records(_manifest_fixture())

    assert [item["junction_id"] for item in records if item["side"] == "teacher"] == [
        "10", "cluster_20_21", "gneJ0", "30"
    ]
    assert [item["junction_id"] for item in records if item["side"] == "candidate_only"] == ["40"]
    assert next(item for item in records if item["junction_id"] == "cluster_20_21")["source_node_ids"] == [
        "20", "21"
    ]
    assert next(item for item in records if item["junction_id"] == "gneJ0")["unknown_reasons"] == [
        "no_osm_source_node_id"
    ]
```

同时断言：教师记录数等于
`len(junction_pairs) + len(teacher_only) + len(ambiguous)`；候选独有记录数等于 `len(candidate_only)`。

- [ ] **Step 2: 运行检查并确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_junction_grouping.py -k manifest -q
```

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现最小清单规范化函数**

在 `junction_grouping.py` 只增加：

```python
GROUPING_SCHEMA = "torii.ingolstadt-junction-groups/v1"
GROUPING_RULE_VERSION = "compact-five-axis-v1"

def source_node_ids(*junction_ids: str) -> list[str]: ...
def manifest_junction_records(manifest: Mapping[str, Any]) -> list[dict[str, Any]]: ...
```

规则：

- `cluster_20_21` 解析为 `20, 21`；纯数字 ID 保留；`gneJ...` 不猜测。
- 对应项的来源节点取教师 ID 和全部候选 ID 的数字来源并集。
- `junction_pairs[*].status` 映射为 `ready` 或 `registration_blocked`。
- 不确定项、教师独有项和候选独有项保留原状态。
- 排序固定为教师清单顺序，再按候选独有 ID 排序。
- 重复教师 ID、重复候选独有 ID或守恒不成立时直接报错。

- [ ] **Step 4: 写失败检查，证明现有分类器被直接调用**

```python
def test_classify_manifest_record_reuses_archetype_profile() -> None:
    patch = _t_junction_patch()
    record = {"side": "teacher", "junction_id": "2", "source_node_ids": ["2"], ...}

    result = classify_manifest_record(
        patch,
        record,
        vehicle_graph=build_osm_vehicle_graph(patch),
        reference_control_type="priority",
    )

    assert result["classification_status"] == "classified"
    assert result["classification_id"].startswith("intersection-classification-")
    assert result["canonical_identity"]["arm_count_class"] == "three_arm"
    assert result["reference_control_type"] == "priority"
    assert result["automatic_promotion_gate"] == "blocked"
```

再写一个无来源节点检查，要求返回 `classification_status="unknown"` 和明确原因，不调用类别猜测。

- [ ] **Step 5: 实现分类适配，不复制类别逻辑**

`classify_manifest_record` 必须只做以下工作：

1. 使用 Task 1 的 `infer_reviewed_source_physical_cell`；
2. 调用现有 `classify_osm_intersection_archetype`；
3. 从结果复制 `classification_id`、`vocabulary_id`、`classifier_version`、完整 `dimensions`、`canonical_identity` 和 `road_detail`；
4. 追加清单状态、教师控制类型、候选 ID、分区 ID 和未知原因；
5. 不产生修改授权。

教师控制类型从已解析一次的教师 `.net.xml` 节点属性取得。OSM `control_rule` 与教师 `type` 分字段保存，不能互相覆盖。

- [ ] **Step 6: 运行局部检查**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_junction_grouping.py tests/intersection/test_archetype_profile.py -q
```

Expected: PASS。

- [ ] **Step 7: 提交本任务**

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/junction_grouping.py tests/test_junction_grouping.py
git commit -m "feat: classify city manifest junctions"
```

## Task 3：生成短分组键并确定选择代表项

**Files:**

- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_grouping.py`
- Modify: `tests/test_junction_grouping.py`

- [ ] **Step 1: 写失败检查，锁定分组键**

```python
def test_group_key_uses_only_five_dispatch_axes() -> None:
    record = _classified_record(
        mapping_status="ready",
        cell_structure="compound",
        reference_control_type="traffic_light",
        arm_count_class="four_arm",
        circulation_form="nontraversable_ring",
    )

    assert group_key(record) == (
        "ready/compound/traffic_light/four_arm/roundabout"
    )
```

再分别检查特殊标记优先级：`roundabout`、`rail`、`link_or_ramp`、`multimodal`、`ordinary`。未知分类仍须得到含 `unknown` 的唯一分组键。

- [ ] **Step 2: 写失败检查，锁定代表项算法**

```python
def test_select_representatives_is_deterministic_and_capped_at_three() -> None:
    records = [_record(score=score, complexity=value) for score, value in ...]

    first = select_representatives(records)
    second = select_representatives(list(reversed(records)))

    assert first == second
    assert [item["complexity"] for item in first] == [1, 5, 9]
    assert len(first) == 3
```

分数相同时用 `side, junction_id` 作为最后排序键。两个成员只取两个，一个成员只取一个。

- [ ] **Step 3: 运行检查并确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_junction_grouping.py -k "group_key or representatives" -q
```

Expected: FAIL，分组和代表项函数不存在。

- [ ] **Step 4: 实现纯函数**

增加：

```python
def group_key(record: Mapping[str, Any]) -> str: ...
def group_records(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]: ...
def select_representatives(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]: ...
def build_representative_queue(groups: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]: ...
```

证据完整度只统计现有分类结果中非 `unknown` 且证据等级不是 `unknown` 的维度。复杂度只用已有车道数、支路数和移动数，不新增模型。代表项取排序后最小、中位和最大位置，并去重。

`groups.json` 的每组只保存：`group_id`、`group_key`、计数、成员引用、代表引用和轴二状态汇总。完整分类只留在 JSONL。

分组键的控制轴优先使用教师记录的 `reference_control_type`；候选独有记录使用现有分类器的 `canonical_identity.control_rule`。两者都缺失时明确写 `unknown`，不回填最近类别。

- [ ] **Step 5: 检查确定性和汇总守恒**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_junction_grouping.py -q
```

Expected: PASS，并且测试断言所有记录恰好进入一组、每个非空组有 1 至 3 个代表项。

- [ ] **Step 6: 提交本任务**

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/junction_grouping.py tests/test_junction_grouping.py
git commit -m "feat: group junctions and select representatives"
```

## Task 4：增加可恢复的全城分类命令

**Files:**

- Create: `plugins/torii-sumo/scripts/run_ingolstadt_junction_groups.py`
- Create: `tests/test_ingolstadt_junction_grouping_script.py`
- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_grouping.py`

- [ ] **Step 1: 写失败检查，锁定输入与命令行**

命令行只接受必要参数：

```text
--manifest PATH
--output-dir PATH
--phase classify|representatives|all
--resume
--raw-node-file PATH
--raw-edge-file PATH
--raw-connection-file PATH
--raw-type-file PATH
--raw-tllogic-file PATH
```

前三个 plain 文件只在代表项阶段检查；类型和信号文件仅在给出时使用。教师网、候选网和 OSM 路径必须来自 manifest，并验证其中已有 SHA-256。

测试必须证明：

- 分类阶段不要求 plain 文件；
- 输入哈希不符时退出且不覆盖旧产物；
- `parse_osm_xml_bytes` 每次进程只调用一次；
- 既有 `run_ingolstadt_citywide_visual_gate.py` 不被修改。

- [ ] **Step 2: 写失败检查，锁定断点恢复**

构造三条记录，在第二条后模拟中断。再次运行 `--resume` 时应只分类第三条：

```python
assert classifier.call_count == 1
assert len(read_jsonl(output / "classification.jsonl")) == 3
assert json.loads((output / "state.json").read_text())["classification_complete"] is True
```

再写一条尾部半行 JSON 的检查。恢复时只截掉最后不完整行，前面的完整行保留。

- [ ] **Step 3: 运行检查并确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_junction_grouping_script.py -q
```

Expected: FAIL，脚本和恢复函数不存在。

- [ ] **Step 4: 用标准库实现最小恢复流程**

复用 `core/artifact_io.py` 的 `write_json_atomic`。分类过程写：

```text
source-ledger.json
classification.partial.jsonl
state.json
```

每完成一行就写 UTF-8 JSON、换行、`flush()`、`os.fsync()`，再原子更新 `state.json` 的 `next_record_index`。恢复时逐行验证 JSON 和稳定记录键，只允许丢弃最后一条不完整行。有效 JSONL 行数是恢复位置的依据；若它与 `state.json` 不同，按有效行数修正 state，防止在两次写入之间中断而跳过记录。全部计数和守恒检查通过后，用 `os.replace` 改名为 `classification.jsonl`，然后原子写 `groups.json` 和 `representative-queue.json`。

`source-ledger.json` 保存：

- manifest、OSM、教师网、候选网的绝对路径和 SHA-256；
- `classifier_version`、`vocabulary_id`、`GROUPING_RULE_VERSION`；
- 教师总数、候选独有总数和预期记录总数。

失效规则：OSM、教师网、分类器或词表变化时拒绝复用分类；候选网变化时允许未来增加的轴一复用，但首版直接拒绝恢复，避免错误混合。不要实现缓存层。

- [ ] **Step 5: 运行脚本检查和相关单元检查**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingolstadt_junction_grouping_script.py tests/test_junction_grouping.py tests/test_artifact_io.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交本任务**

```powershell
git add plugins/torii-sumo/scripts/run_ingolstadt_junction_groups.py plugins/torii-sumo/src/torii_sumo/core/junction_grouping.py tests/test_ingolstadt_junction_grouping_script.py
git commit -m "feat: add resumable Ingolstadt grouping command"
```

## Task 5：复用当前 Torii 对全部代表项做真实重建

**Files:**

- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_grouping.py`
- Modify: `plugins/torii-sumo/scripts/run_ingolstadt_junction_groups.py`
- Modify: `tests/test_junction_grouping.py`
- Modify: `tests/test_ingolstadt_junction_grouping_script.py`

- [ ] **Step 1: 写失败检查，锁定教师引导报告适配**

```python
def test_representative_join_report_uses_manifest_registration_only() -> None:
    report = representative_join_report([_representative_record()])

    assert report["matched_cases"] == [{
        "reference_id": "cluster_20_21",
        "reference_joined_source_nodes": ["20", "21"],
        "matched_reference_source_node_ids": ["20", "21"],
        "matched_candidate_node_ids": ["20", "21"],
        "learned_rule_basis": "citywide_manifest_registration",
        "learned_rule": "tum_like_citywide_group_representative",
    }]
```

`teacher_only`、`candidate_only`、`ambiguous` 和没有候选 ID 的代表项不能伪造 `matched_cases`。它们使用同一次当前版本全城清单运行的注册报告，并绑定一次共享的候选网 SUMO 载入报告；状态保持 `review_required`。

- [ ] **Step 2: 写失败检查，证明每个可运行代表项调用现有队列和矩阵**

用注入的替身断言：

```python
queue_builder.assert_called_once_with(..., target_junction_ids=[representative_id])
matrix_runner.assert_called_once_with(
    ...,
    target_junction_ids=[representative_id],
    sequential_accept_passed_variants=False,
    strict_teacher_replay=True,
)
```

每个可对应代表项使用独立输出目录和同一冻结候选网，禁止前一个代表项改变后一个代表项的起点。测试还要断言不能对应的代表项写出 `run_kind="registration_diagnostic"`，且不调用重建矩阵。

- [ ] **Step 3: 运行检查并确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_junction_grouping.py tests/test_ingolstadt_junction_grouping_script.py -k representative -q
```

Expected: FAIL，代表项报告适配和执行函数不存在。

- [ ] **Step 4: 最小复用现有重建入口**

新增纯适配函数 `representative_join_report(...)` 和执行函数 `run_representatives(...)`。后者先对冻结候选网运行一次 SUMO 载入检查。然后对每个可对应代表项依次调用：

1. `build_teacher_guided_repair_queue(...)`；
2. `run_teacher_guided_repair_matrix(...)`。

不能对应的代表项写入新的逐项运行记录，引用当前版本清单中的注册证据和共享 SUMO 载入报告，不进入重建矩阵。这样每个代表项都有当前版本运行证据，但不会伪造教师到候选的对应。

不得修改 `junction_rebuild_candidate.py`。不得为分组新写重建策略。命令行默认 `sequential_accept_passed_variants=False`、`strict_teacher_replay=True`。

每组写：

```text
groups/*/representative-results.json
groups/*/teacher-* 或 groups/*/candidate_only-*
```

结果绑定四个来源哈希、分类 ID、分组 ID、队列报告路径和矩阵报告路径。

- [ ] **Step 5: 运行局部和现有重建检查**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_junction_grouping.py tests/test_ingolstadt_junction_grouping_script.py tests/test_junction_rebuild_candidate.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交本任务**

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/junction_grouping.py plugins/torii-sumo/scripts/run_ingolstadt_junction_groups.py tests/test_junction_grouping.py tests/test_ingolstadt_junction_grouping_script.py
git commit -m "feat: run Torii on grouped representatives"
```

## Task 6：从报告归纳根因，并接回 NetEdit 视觉门

**Files:**

- Modify: `plugins/torii-sumo/src/torii_sumo/core/junction_grouping.py`
- Modify: `plugins/torii-sumo/scripts/run_ingolstadt_junction_groups.py`
- Modify: `tests/test_junction_grouping.py`
- Modify: `tests/test_ingolstadt_junction_grouping_script.py`

- [ ] **Step 1: 写失败检查，锁定报告到根因族的映射**

用现有矩阵报告的明确字段和失败原因建立表驱动检查，覆盖：

```text
registration
physical_cell_or_split_merge
approach_boundary_or_geometry
lane_mapping_count_or_permission
movement_connection_or_right_of_way
crossing_walkingarea_or_mode
tls_controller_or_link_index
sumo_load_or_routeability
netedit_visual_mismatch
unknown
```

一个报告可以有多个根因族。按现有门的执行顺序保存有序去重列表，第一项为 `primary_failure_family`。无法从报告证明的情况只能是 `unknown`。

- [ ] **Step 2: 写失败检查，限制视觉检查范围**

只有结构和 SUMO 载入已通过的候选进入 `visual-review-queue.json`。队列项必须包含代表路口、分区 ID、教师网、候选产物、Connection 模式和既有视觉门所需参数。没有截图或视觉结果时，状态必须是 `review_required`，不能记为 `pass`。

- [ ] **Step 3: 运行检查并确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_junction_grouping.py tests/test_ingolstadt_junction_grouping_script.py -k "failure_family or visual" -q
```

Expected: FAIL，映射和视觉队列函数不存在。

- [ ] **Step 4: 实现一个小型映射函数和视觉队列输出**

增加：

```python
def failure_families(run_report: Mapping[str, Any]) -> list[str]: ...
def build_visual_review_queue(results: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]: ...
```

根因判断只读取报告字段和原因文本的固定标识。不要根据文件名、分组类型或截图印象推断。

脚本写 `visual-review-queue.json` 后，调用现有 `run_ingolstadt_citywide_visual_gate.py` 的公开函数或命令行，对代表项所在分区以 `max_tile_distance=0` 运行。继续使用现有 NetEdit CLI Connection 模式截图；不新增截图实现。若现有视觉入口不能唯一绑定代表项，则保留该分区内完整检查，不削弱范围。

- [ ] **Step 5: 汇总组级状态**

更新每组 `representative-results.json`：

- 所有代表项结构、SUMO 和视觉均通过才记 `pass`；
- 已运行且有报告失败时记 `fail` 并保存根因族；
- 缺少视觉证据或不能运行时记 `review_required`；
- 同组代表项出现不同根因时，只用现有完整分类维度生成拆组建议，不自动新增分组字段。

- [ ] **Step 6: 运行相关回归检查**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_junction_grouping.py tests/test_ingolstadt_junction_grouping_script.py tests/test_ingolstadt_citywide_visual_gate_script.py -q
```

Expected: PASS。

- [ ] **Step 7: 提交本任务**

```powershell
git add plugins/torii-sumo/src/torii_sumo/core/junction_grouping.py plugins/torii-sumo/scripts/run_ingolstadt_junction_groups.py tests/test_junction_grouping.py tests/test_ingolstadt_junction_grouping_script.py
git commit -m "feat: classify representative run failures"
```

## Task 7：在真实 Ingolstadt 数据上运行并核对分组阶段

**Files:**

- Create: `outputs/ingolstadt_citywide_grouping_v1/ingolstadt-junction-groups/*`（运行产物，不提交，除非仓库现有规则明确要求）
- Modify: `docs/superpowers/specs/2026-08-08-ingolstadt-junction-road-grouping-design.md`（只在实测事实与设计基线不符时修正）

- [ ] **Step 1: 先运行全套相关检查**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/intersection/test_review_proposal.py tests/intersection/test_archetype_profile.py tests/test_junction_grouping.py tests/test_ingolstadt_junction_grouping_script.py tests/test_artifact_io.py tests/test_junction_rebuild_candidate.py tests/test_ingolstadt_citywide_visual_gate_script.py -q
```

Expected: PASS。若既有脏改动造成无关失败，保存完整失败命令和报告，不覆盖用户改动。

- [ ] **Step 2: 用当前代码刷新同一范围的全城清单**

从既有基线读取同一教师网、候选网和 OSM 路径，在新目录运行，保留旧审计结果：

```powershell
$baselineManifest = "outputs/ingolstadt_citywide_native_visual_v59_target427_gate50m_probe/city-manifest.json"
$baselineData = Get-Content -Raw -Encoding UTF8 $baselineManifest | ConvertFrom-Json
$groupRun = "outputs/ingolstadt_citywide_grouping_v1"
.\.venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_citywide_visual_gate.py `
  --teacher-net $baselineData.teacher_net_file `
  --candidate-net $baselineData.candidate_net_file `
  --source-osm $baselineData.source_osm_file `
  --output-dir $groupRun `
  --phase inventory `
  --tile-size-m $baselineData.tile_size_m `
  --junction-distance-m $baselineData.junction_distance_m
$groupManifest = Join-Path $groupRun "city-manifest.json"
$groupOutput = Join-Path $groupRun "ingolstadt-junction-groups"
```

Expected: 命令返回 0，新清单的 OSM SHA-256 与旧清单相同。若对应计数变化，保留新旧计数和代码版本，后续以新清单为准。

- [ ] **Step 3: 对当前冻结清单运行分类阶段**

Run:

```powershell
.\.venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_junction_groups.py `
  --manifest $groupManifest `
  --output-dir $groupOutput `
  --phase classify `
  --resume
```

Expected invariants:

- 教师记录恰好 8771 条；
- 教师记录 = 8351 个对应项 + 290 个教师独有项 + 130 个不确定项；
- 候选独有记录恰好 4695 条；
- 每条记录唯一，每条记录恰好属于一组；
- 每个 `unknown` 都有原因；
- 每个非空组有 1 至 3 个确定代表项；
- 第二次 `--resume` 不重新分类任何完整记录。

若清单已由前序工作刷新，以新 manifest 的守恒字段为准，同时记录旧基线和新值，不能把差异静默归零。

- [ ] **Step 4: 从 manifest 指向的候选网导出 plain 文件**

用 NetEdit/Netconvert 同套 SUMO 命令行，从 manifest 指向且已通过哈希校验的候选网生成新的 plain 文件。不要复用旧探针目录中来源不明的 plain 文件：

```powershell
$manifestData = Get-Content -Raw -Encoding UTF8 $groupManifest | ConvertFrom-Json
$candidateNet = (Resolve-Path ([string]$manifestData.candidate_net_file)).Path
$plainDir = Join-Path $groupOutput "plain"
New-Item -ItemType Directory -Force $plainDir | Out-Null
$plainPrefix = Join-Path $plainDir "base"
netconvert --sumo-net-file $candidateNet --plain-output-prefix $plainPrefix
Get-FileHash -Algorithm SHA256 $candidateNet, "$plainPrefix.nod.xml", "$plainPrefix.edg.xml", "$plainPrefix.con.xml"
```

Expected: `netconvert` 返回 0，且 `base.nod.xml`、`base.edg.xml`、`base.con.xml` 存在。若 `.typ.xml` 或 `.tll.xml` 没有生成，代表项命令不传相应可选参数。

- [ ] **Step 5: 对全部代表项运行当前 Torii**

Run:

```powershell
.\.venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_junction_groups.py `
  --manifest $groupManifest `
  --output-dir $groupOutput `
  --phase representatives `
  --raw-node-file "$plainPrefix.nod.xml" `
  --raw-edge-file "$plainPrefix.edg.xml" `
  --raw-connection-file "$plainPrefix.con.xml" `
  --resume
```

如果 `.typ.xml` 和 `.tll.xml` 存在，则分别追加 `--raw-type-file "$plainPrefix.typ.xml"` 和 `--raw-tllogic-file "$plainPrefix.tll.xml"`。Expected: 每个代表项都有矩阵报告；不能运行的清单状态也有明确 `review_required` 原因。

- [ ] **Step 6: 完成 NetEdit CLI Connection 模式视觉检查**

按 `visual-review-queue.json` 对每个需要视觉检查的代表分区运行现有视觉门。每次保存教师网和 Torii 结果的成对截图及视觉报告。检查：

- 进入、离开车道是否对应；
- 转向连接是否缺失或多余；
- 车道数和通行权限是否一致；
- 组合路口是否仍残留错误节点或内部连接；
- 信号连接编号和人行设施是否明显不一致。

只有视觉报告明确通过时，代表项才可成为 `pass`。

- [ ] **Step 7: 运行分组阶段最终核对**

Run:

```powershell
.\.venv\Scripts\python.exe plugins/torii-sumo/scripts/run_ingolstadt_junction_groups.py `
  --manifest $groupManifest `
  --output-dir $groupOutput `
  --phase all `
  --raw-node-file "$plainPrefix.nod.xml" `
  --raw-edge-file "$plainPrefix.edg.xml" `
  --raw-connection-file "$plainPrefix.con.xml" `
  --resume
```

Expected completion conditions:

1. 两侧清单总数守恒；
2. 每个教师路口有完整分类或带原因的 `unknown`；
3. 每条记录恰好属于一组；
4. 每个非空组有代表项；
5. 当前 Torii 已对全部代表项真实运行；
6. 每组为 `pass`、明确根因的 `fail` 或明确原因的 `review_required`；
7. 所有产物绑定来源哈希并可恢复。

- [ ] **Step 8: 形成下一轮最小修复顺序**

按“受影响记录数 × 根因一致性”排序失败组。只有同组代表项重复出现同一根因时，才在共用流程上修复。先找所有调用方，再修改共同入口。若必须增加类型规则，先集中在一个小文件中，并为每条规则保留一个失败检查。

- [ ] **Step 9: 提交代码和必要文档，不提交体积较大的运行产物**

```powershell
git status --short
git add plugins/torii-sumo/src/torii_sumo/intersection/physical_cell.py tests/intersection/test_review_proposal.py plugins/torii-sumo/src/torii_sumo/core/junction_grouping.py tests/test_junction_grouping.py plugins/torii-sumo/scripts/run_ingolstadt_junction_groups.py tests/test_ingolstadt_junction_grouping_script.py docs/superpowers/specs/2026-08-08-ingolstadt-junction-road-grouping-design.md
git commit -m "feat: complete Ingolstadt junction grouping phase"
```

提交前确认没有暂存本计划开始前已经存在的七个脏文件，也没有暂存 `plugins/torii-sumo/src/torii_sumo.egg-info/`。

## 全城后续门

分组阶段通过后，继续按失败组覆盖量修复现有共用流程。每个修复都先重跑该组代表项，再重跑相邻空间分区。全部组稳定后，把已验证规则组合回同一候选网，并恢复现有全城命令的 `inventory -> visual -> global` 流程。只有下列检查全部通过后，才可声称 Ingolstadt 全城完成：

- 所有适用路口的结构检查通过；
- 所有视觉分区在 NetEdit CLI Connection 模式通过；
- SUMO 全网载入通过；
- 全局可达性和路径检查通过；
- 候选网、教师网、OSM、分类、规则和截图报告哈希一致。
