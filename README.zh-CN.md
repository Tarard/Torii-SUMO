<p align="center">
  <img src="docs/assets/banner.png" alt="Torii 面向 SUMO 的 agent plugin 横幅">
</p>

# <img src="docs/assets/app-logo.png" width="42" alt="Torii 图标"> Torii

<div align="center">

**Task-Oriented Road Infrastructure Intelligence**

**Agent plugin for SUMO**

<p><strong>Codex / Claude agent plugin</strong> · SUMO/TraCI 工作流 · OSM-to-SUMO 清洗 · 本地 MCP tools</p>

<a href="https://tarard.github.io/Torii-SUMO/"><strong>项目网站</strong></a> |
<a href="docs/codex-plugin-install.md"><strong>安装</strong></a> |
<a href="examples/01_signal_control_audit/task.md"><strong>信号控制审计</strong></a> |
<a href="examples/02_one_prompt_osm_network/README.md"><strong>One-Prompt Demo</strong></a> |
<a href="LICENSE"><strong>许可证</strong></a>

[English](README.md) | [简体中文](README.zh-CN.md) | [Deutsch](README.de.md)

</div>

## Evidence-Aware OSM-to-SUMO Construction

Torii 面向 SUMO 路网构建工作：一句简短的自然语言 prompt 可以变成一个有边界、证据驱动、可与参考路网对比的 OSM-to-SUMO 工作流，包含构建证据、路线可达性检查、审查 artifacts 和清晰的结论边界。

插件现在从 workflow router 开始：`torii_auto_workflow` 会分类用户请求、选择 skill、制定计划，并运行安全的 MCP 步骤来为你生成或修改 SUMO 路网。

Torii 有两层：

| 层级 | 作用 |
|---|---|
| 推理层 | SUMO expert skills 负责提出正确问题、选择工作流并限定结论边界。 |
| 执行层 | 本地安全 stdio MCP tools 负责运行有边界的 SUMO 检查，并返回结构化观察。 |

架构说明见 [`ARCHITECTURE.md`](ARCHITECTURE.md)：router、planner、executor 和 reviewer。

当前 MCP tools 覆盖 `torii_auto_workflow` router、环境检查、配置预检、smoke run、证据包、OSM 路网构建、TLS 候选、多源 TLS 复核表、TLS aggregation review variant、代码原生的全网及原网到候选 Connection Mode 差分审计、严格的标准三/四叉口 NEMA 相位绑定候选、连接性检查、connected-core 提取、路线可达性 probe、completion-aware routeability audit、overlapping top-level junction audit、reference join audit、junction aggregation review variant 和可选的 NetEdit 打开证据。

### 当前走廊级验收边界

已经实现的晋级契约以走廊为尺度：接受的修改会物化为独立候选网络；审核位置写入 SUMO `additional.xml`；受保护的语义或 TLS 变化必须有绑定候选 SHA-256 的精确审核决定；身份、netconvert、XML、SUMO load、routeability、topology 和 modal connectivity 证据全部通过前不会晋级。

每个物化修改现在都会生成一套审核包：`*.net.xml`、`*.map-review.json`、`*.accepted.review.add.xml`、`*.review.html`、`*.review.json` 和带哈希的 manifests。`additional.xml` 只负责展示，并且只允许 `poi`、`poly`、`param`；人工决定保存在结构化 JSON 中。Google Maps、卫星图、Mapillary、KartaView 或区域地图只是辅助证据；只有修改显式声明 `map_review_required: true`，并给出 current 或 historical 时间范围时，地图审核才成为硬门。

真实 SUMO 可复现回归覆盖四向 OSM sidewalk、SUMO 官方 pedestrian crossing/TLS 审核、五向 bicycle 和五向 ramp：

```powershell
python plugins/torii-sumo/scripts/run_corridor_contract_regression.py
```

脚本会现场重建源网络，不依赖旧的生成输出。当前架构结论和剩余债务见 [`docs/architecture-audit-2026-07-13.md`](docs/architecture-audit-2026-07-13.md)。

### 代码原生 Connection Mode 硬门

`sumo_network_connection_mode_audit` 会直接从 `.net.xml` 重建 NetEdit Connection Mode；OSM 清洗流程默认执行这项审计，而面向用户的 NetEdit 自动打开默认关闭。它逐路口核对直接 `fromLane -> toLane -> via`、完整 internal-lane continuation、车道与权限、request 顺序和 bitstring、转向车道顺序、lane-rank/交叉映射、机动车入口/出口车道覆盖、TLS `linkIndex` 边界、controller state-string 长度、互为 foe 却共享 signal group，以及同相位同时得到保护 `G` 的 foe movement。SUMO 运行时管理的 `rail_signal` 会被单独分类，不再误报成缺少道路 `tlLogic`。

结果分三档：XML/path/request/linkIndex 确定损坏为 `fail`；合法但存在歧义的 merge、fanout、lane drop、lane addition 或信号冲突为 `review_required`；完全无发现才是 `pass`。前两档都会阻断候选自动晋级。工具输出 JSON、仅用于显示的审核 `additional.xml` 和绑定源 SHA-256 的 manifest。这样 NetEdit 只用于被标记疑难点的可视化复核，routeability 不能再代替车道绑定证明。

`sumo_network_connection_mode_regression_audit` 是“原网 → 候选网”的差分硬门。它分别审计两个 `.net.xml`，把声明的修改范围闭包到被触及 TLS controller 的成员，再按逐路口 finding category 比较，不依赖容易变化的 internal connection 序号。目标范围内新增结构错误或审核项、范围外任何回归、以及无法解释的范围外 junction 身份变化都会阻断晋级。teacher-guided repair queue 已默认执行这道门，并在每个全网候选旁写出 JSON、仅显示的 `additional.xml` 和 SHA-256 manifest；只要候选文件存在，即使前面的 semantic/parity 已失败，也仍可执行这项诊断。

当前 Ingolstadt 同 bbox effective network 的全网审计覆盖 2,274 个路口和 13,169 条直接 movement，13,169/13,169 条 internal path 均被代码证明连续；结构失败为 0，2,164 个路口通过，110 个进入证据审核。队列包括 27 条“入口机动车车道无 junction connection”、19 条“出口机动车车道无来源 connection”、合法 merge/fanout，以及 junction `267517559` 的 1 组当前 TLS 保护绿 foe。12 个铁路隐式 controller 被正确记录为 SUMO runtime rail signal。没有 OSM、地图或车道标线证据时，系统不会从这些发现直接推断修复。

当前 Südliche Ringstraße 重建候选被明确禁止晋级。差分门先发现 plain-XML round trip 会重复应用 type 里的 `sidewalkWidth`/`bikeLaneWidth`，使 lane index 整体错位并产生 1,828 个范围外新增审核项；round-trip type 清洗已经消除这类全网污染。最新安全默认候选的范围外结构错误、审核回归和 junction 身份变化均为 0，但因为目前只映射了更复杂信号单元中的 3 个节点，目标范围内仍新增 13 个结构错误和 27 个审核项，所以继续保持阻断。完整 controller 合并的实验候选也被代码否决。对这些被阻断候选没有 routeability 成功宣称，也没有修改源网络。

### 标准三/四叉口 NEMA 相位绑定

`sumo_network_standard_nema_phase_binding` 已接入 OSM 清洗边界。不传 `junction_id` 时，它只扫描最终有效网络，输出资格队列、独立的 Connection Mode JSON 报告、仅用于显示的 review `additional.xml`、HTML、decision contract 和带哈希 manifest，不会批量修改路网。传入一个 eligible `junction_id` 后，它才会生成独立、可回滚候选，把受保护左转映射到 NEMA 奇数相位，把直行/右转映射到偶数相位，只重写目标 controller 的 `linkIndex` 信号组和 `tlLogic`，然后强制通过 netconvert、SUMO load 和 routeability 三道门。

标准四叉口采用跨环归属：主路一侧左转/直行右转为 5/2，对向为 1/6；支路两侧为 7/4 与 3/8，因此支持官方定义的 1+5、1+6、2+5、2+6 及支路对应组合。三叉口按 SUMO NEMA 规则使用缺相 `0` 占位，并在第二道 barrier 的空侧重复 phase 4。在写出任何候选前，Connection Mode 硬门会沿完整 internal-lane 链追踪每个 `fromLane -> toLane -> via`，检查右侧通行的转向车道顺序和 lane-rank 跳变，验证 request/foes 矩阵，并阻断任何“canonical NEMA 可能并发、但 SUMO 标为 foes”的 movement 对。joined controller、人行/internal 或铁路 link、纯自行车 movement、掉头、`linkIndex2`、几何歧义、arm-to-arm movement 不完整、左转车道不专用也都会 fail-closed。即使所有运行门通过，候选仍保持 `review_required`，因为默认 90 秒方案不是现场标定配时。

phase/ring 契约遵循 SUMO 官方 [NEMA controller 文档](https://sumo.dlr.de/docs/Simulation/NEMA.html)，signal group 遵循官方 [`linkIndex` state-string 语义](https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html)，request/foe 索引遵循官方 [SUMO 路网格式](https://sumo.dlr.de/docs/Networks/SUMO_Road_Networks.html)。routeability 运行已开启 SUMO junction collision 检查；单纯图可达不再被视为 Connection Mode 证据。

本机 SUMO 1.27.1 已重新验收标准四叉和 T 型三叉：两者的 Connection Mode、candidate validation、netconvert round trip、SUMO load 和 12/12 routeability 全部通过，并开启 junction collision 检查，collision/teleport 均为 0。四叉验证 12 条内部 movement path 并绑定到 phases 1–8；三叉验证 6 条 path，使用 phases 1/2/4/6，以及 rings `1,2,0,4`、`0,6,0,4`。当前 Ingolstadt 同 bbox 扫描绑定到可被 SUMO 加载的 effective TLS-cleaned network，共生成 249 条 TLS-junction 审核记录，其中几何上有 24 个三叉和 4 个四叉，但严格自动资格为 0。1,617 条 request-bound movement path 全部结构有效：221 个 TLS 路口通过 Connection Mode 证明，28 个为 `review_required`，结构失败为 0；28 个标准几何路口中为 15 个通过、13 个需要证据审核。审核发现表示机器还不能自动证明安全，不等于被标记 link 必然错误。统一 display-only 审核层把 28 个 connection-review 位置与 221 个仅因其他 NEMA 范围条件被阻断的位置分开，并且没有修改 effective network。

### Ingolstadt 教师走廊切片

第一个同 bbox 教师切片已经可以端到端执行：

```powershell
python plugins/torii-sumo/scripts/run_ingolstadt_corridor_teacher.py
```

它会下载当前 OSM bbox，构建 raw visual-detail 路网，只应用边界严格、证据充分的结构修复，然后运行 SUMO load、completion-aware routeability，并把 junction `267517510` 与 TUM 人工清洗单元对照。结构修复始终写入独立候选：本次只从一条已经是无控制状态的人行内部连接删除了 1 个陈旧 TLS identity，58 个内嵌 `tlLogic` 和 12 个铁路隐式控制器保持不变，源文件哈希确认未变，同时生成逐项回滚计划和仅用于显示的 review `additional.xml`。

最新本机 SUMO 1.27.1 验收中，候选成功加载，随机生成的 10/10 行程全部完成，collision 和 teleport 均为 0。教师迁移仍是 `review_required`：当前 OSM 已支持信号灯控制，并明确包含 3 个信号控制 crossing 节点；候选剩余差异是人行内部结构和 movement signatures。因此 Torii 不会机械重放旧教师 TLS。生成的 run manifest 和 HTML 用 SHA-256 绑定精确 OSM、source、candidate、地图证据和审核产物。

在线获取完成后，可以同时传入 `--candidate-net` 和 `--source-osm` 做确定性离线重放；runner 会跳过 Overpass，但仍把精确 OSM 证据写入教师对照和 manifest。下载失败会保留为 blocked run，不会静默复用缓存冒充在线成功。

## Example

可以用这个 prompt 测试 Torii：

```text
Use Torii to clean the Ingolstadt city-center network from OSM, compare it with the TUM-VT/sumo_ingolstadt cleaned network for the same bbox, run the code-native Connection Mode audit, and open only flagged junctions in NetEdit if visual review is needed.
```

这个 demo 使用 Ingolstadt 市中心，用来测试 Torii 的 OSM-derived workflow 是否比单纯导入更可审计，并且是否更接近人工清洗参考路网。目前已经证明的验收结论是上面的单走廊切片；下面较早的全 bbox 表格仍是诊断证据，不代表城市级自动等价已经完成。

![TUM bbox reference 与 Torii 5.5 TLS 聚合 visual-detail 对比](examples/02_one_prompt_osm_network/assets/tum_vs_torii_5_5_tls_aggregated_overview.png)

| 证据 | 结果 |
|---|---:|
| Torii vehicle core | connected-core 提取后，对比 bbox 内 2,493 条 edge、3,045 条 lane、1,220 个 junction |
| Torii reference visual-detail | 对比 bbox 内 6,126 条 edge、6,695 条 lane、2,997 个 junction |
| TUM 人工清洗参考子集 | 同一 bbox 内 3,577 条 edge、4,955 条 lane、1,752 个 junction |
| 信号灯 junction | Torii visual-detail raw 217；TLS aggregation review variant 34 vs TUM 29 |
| 剩余清洗目标 | 对多出的 TLS 候选做 Google Maps 复核，并继续做可复用的物理交叉口聚合 |
| claim status | `diagnostic-demo` |

详见 [`examples/02_one_prompt_osm_network`](examples/02_one_prompt_osm_network/README.md)。这次 5.5 对比用的关键路网和截图已提交到 example；生成的 OSM extract、route 和完整 log 仍然作为可重建产物保留。

## Quick Start

从 GitHub 安装：

```powershell
codex plugin marketplace add Tarard/Torii-SUMO --ref main
codex plugin add torii-sumo@torii-sumo
```

安装后开启一个新的 Codex 或 Claude Code 对话，让插件里的 skills 和 MCP tools 被发现。

完整安装说明见：[Codex Plugin Installation](docs/codex-plugin-install.md)。

## What You Can Ask Me

| Prompt | Torii 会做什么 |
|---|---|
| "Use Torii to clean the Ingolstadt city-center network from OSM and compare it with TUM-VT/sumo_ingolstadt." | 从 OSM 构建路网，检查连接性、路线可达性和代码原生车道绑定，将拓扑/TLS 证据与参考路网对比并生成审核队列；NetEdit 只在疑难点需要时打开。 |
| "Audit this TraCI signal controller before I compare it with fixed-time or max-pressure." | 在任何性能结论前检查 controller identity、成对 demand/seeds/horizon、TLS 映射、输出和完成度。 |
| "This SUMO run finishes, but tripinfo and summary disagree." | 诊断输出一致性、未完成车辆、teleport、route error 和结论边界。 |

## Boundaries

Torii 可以构建和审计 SUMO artifacts，但不会认证模型一定正确。

- OSM 导入在道路级别、连接性、路线可达性、TLS 现实性和地图基线证据完成前仍然只是诊断结果。
- `connected-core` 路网适合做 smoke test，但被丢弃的碎片和拓扑 warning 仍然属于结论边界。
- 它不能证明信号灯 timing、phasing、demand realism、controller correctness 或完整实验有效性。

## License and Notices

源代码使用 PolyForm Noncommercial 1.0.0。Skill 文件、文档、检查清单、示例和协议文本使用 CC BY-NC 4.0。商业使用需要另行取得书面许可。两个授权范围都写在 [`LICENSE`](LICENSE)。

Eclipse SUMO 是 Eclipse Foundation 的商标。OSM demo 中的地图数据 © OpenStreetMap contributors，并基于 Open Database License (ODbL) 提供。

早期 skill-only 版本已归档在 Zenodo：https://doi.org/10.5281/zenodo.20627976
