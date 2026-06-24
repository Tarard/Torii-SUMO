<p align="center">
  <img src="docs/assets/banner.png" alt="Torii 面向 SUMO 的 agent plugin 横幅">
</p>

# <img src="docs/assets/app-logo.png" width="42" alt="Torii 图标"> Torii

<div align="center">

**Task-Oriented Road Infrastructure Intelligence**

**Agent plugin for SUMO**

<p><strong>Codex / Claude agent plugin</strong> · SUMO/TraCI 工作流 · OSM-to-SUMO 清洗 · 本地 MCP tools</p>

<a href="https://tarard.github.io/Torii-SUMO/"><strong>项目网站</strong></a> |
<a href="docs/codex-plugin-install.md"><strong>Codex 插件安装</strong></a> |
<a href="examples/01_signal_control_audit/task.md"><strong>示例</strong></a> |
<a href="docs/common-sumo-signal-control-failures.md"><strong>失败清单</strong></a> |
<a href="LICENSE"><strong>许可证</strong></a>

[English](README.md) | [简体中文](README.zh-CN.md) | [Deutsch](README.de.md)

</div>

> [!IMPORTANT]
> Torii 不是单纯的提示词或说明文档。它把 SUMO expert skill 和本地 stdio MCP 工具打包在一起，让 Codex/Claude 这类 coding agent 能够执行有限、可验证的 SUMO 检查。当前版本已经包含环境检查、配置预检、冒烟运行、证据包、OSM 清洗硬门槛流程、OSM-to-SUMO 构网、TLS 候选审计、多源 TLS 复核表、连接性检查、Netedit 打开证据和路线可达性检查；静默完整地名解析、整城级自动认证和控制器自动生成还不是已经完成的 MCP 工具。

Torii 现在优先从 workflow router 开始：`torii_auto_workflow` 会先理解用户的一句话，选择工作流 recipe，只追问阻塞问题，并在证据足够时自动运行安全的 MCP 步骤。

> [!NOTE]
> 本项目是独立项目，不隶属于 Eclipse Foundation、Eclipse SUMO、DLR、OpenAI、Anthropic、Google 或任何外部 OSM 工具项目，也不代表这些项目的认可、赞助或维护。

## Torii 是什么

Torii 的含义是 **Task-Oriented Road Infrastructure Intelligence**。它的目标是让 coding agent 在 SUMO 项目里像一个更有经验的工程师那样工作：先理解用户真正要的结果，再观察当前模型和输出，最后根据反馈做最小、可解释的修改。

| 层级 | 作用 |
|---|---|
| 推理层 | SUMO expert skill 负责理解意图、选择工作流、追问缺失证据、解释坏指标反映的建模问题。 |
| 执行层 | 本地 MCP server 负责运行受限工具，返回文件、日志、警告、指标、TLS 候选、路线和证据包等结构化观察。 |

默认入口是 `torii_auto_workflow`。它会把一句自然语言请求路由到 OSM 构网、TLS 复核、路线可达性、坏指标诊断或实验审计工作流。

安装 Torii 后，Codex 会同时获得 **skills and MCP tools**。它的目标不是盲目优化某个数字，而是把指标当作反馈信号：这个指标为什么坏、它反映了网络/需求/控制器/实验设计的什么问题、下一步最小修改是什么。

## 你可以怎么问

| 用户一句话 | Torii 应该怎么处理 |
|---|---|
| “用这块 OSM 区域构建 SUMO 路网。” | 使用 OSM 清洗硬门槛流程：必要时先确认区域，再执行受限 OSM 导入、TLS 地图审计、客车路网连接性检查；如果原始路网有小碎片，会提取连通核心路网，再给出 Netedit 打开证据。 |
| “清洗德雷斯顿核心区路网。” | 如果给了 bbox 或 extract，就直接运行硬门槛流程；如果只有地名，就先生成 OSM 预览检查点并让用户确认区域。 |
| “把所有信号灯先按 Google Maps 基线审查，再加 OSM、Mapillary、KartaView、官方清单、信号方案和现场照片做一张复核表。” | 提取 SUMO TLS 候选点，保留 Google Maps 作为当前路网基线 gate，生成多源复核字段，并报告还缺什么人工确认证据。 |
| “检查这几条路/桥能不能通。” | 生成 named-road routeability probes，报告缺失关键边、路线生成证据和剩余 SUMO 完成风险。 |
| “指标变差了，帮我改。” | 把坏指标作为反馈，先诊断路线、需求、路网、TLS、控制器、输出、仿真时长或完成度问题，再提出修改。 |
| “给路网加最大压力控制。” | 使用内置 skill 和公开控制器模式给出计划、测试和验证路径；完整控制器生成仍是路线图工具。 |

## 快速开始

从 GitHub 安装：

```powershell
codex plugin marketplace add Tarard/Torii-SUMO --ref main
codex plugin add torii-sumo@torii-sumo
```

安装或重新安装后，开启一个新的 Codex 对话，让插件里的 skill 和 MCP tools 被重新发现。

本地开发时，可以从仓库根目录或指定路径添加 marketplace：

```powershell
codex plugin marketplace add <path-to-this-repo>
codex plugin add torii-sumo@torii-sumo
```

如果只想手动安装 skill，也可以复制根目录里的 skill：

```text
.agents/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

然后这样调用：

```text
Use Torii to build and audit this SUMO network. Treat bad metrics as feedback about the model, not as the optimization target itself.
```

如果优先使用 MCP 工具，可以把一句话请求和输出目录直接交给 `torii_auto_workflow`。

## 仓库结构

```text
plugins/
  torii-sumo/
    .codex-plugin/plugin.json
    .mcp.json
    scripts/run_torii_sumo.py
    src/torii_sumo/
    skills/simulation-helper-skill-for-eclipse-sumo/

skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

原来的 `Simulation Helper Skill for Eclipse SUMO` 没有被丢掉。它现在是 Torii 的推理层，同时也被打包进可安装插件。

## 已实现的 MCP 工具

| 工具 | 当前范围 |
|---|---|
| `torii_auto_workflow` | 理解一句自然语言 SUMO 请求，选择工作流 recipe，只追问阻塞问题，并运行安全的 MCP 步骤。 |
| `sumo_preflight` / `sumo_get_environment` | 检查 SUMO、Python、TraCI 和本机工具链证据。 |
| `sumo_config_pair_preflight` | 检查一组 `.sumocfg` 的输入缺失和输出冲突。 |
| `sumo_run_config` / `sumo_run_minimal_smoke` | 运行受限 SUMO 配置或最小冒烟测试，返回日志和输出观察。 |
| `sumo_compare_outputs` / `sumo_collect_evidence` | 以完成度优先的方式比较结果并写出证据包。 |
| `sumo_osm_cleanup_workflow` | 高层 OSM 清洗流程，包含区域确认、OSM 构网、TLS 地图审计、连接性检查、连通核心路网提取和 Netedit 打开证据。 |
| `sumo_osm_build_network` | OSM 下载或复用、Overpass 分块、重试、XML 去重、道路筛选和 `netconvert`。 |
| `sumo_tls_audit` | 提取 TLS 候选、聚类路口审查组，并附加地图审查字段。 |
| `sumo_tls_multisource_review` | 生成多源 TLS 人工复核表，包含 OSM、Google Maps、Mapillary、KartaView、官方清单、信号方案和现场证据字段。 |
| `sumo_network_connected_core` | 从已有 SUMO `.net.xml` 中提取最大 passenger component，生成可复用的 `connected-core` 路网，并报告被丢弃的小碎片。 |
| `sumo_network_routeability_probe` | 生成指定道路/桥的路线可达性 probes 和受限 `.sumocfg`。 |

OSM 设计参考了 OSMnx、OSMNet、pyrosm、SUMO `osmGet/osmBuild` 和 osm-to-xodr 的架构思路，但不直接拷贝或 vendoring 外部源码。

## 反馈诊断原则

Torii 不把“指标最优”当作唯一目标。它会先问：

```text
用户想要什么结果
-> 当前 SUMO 输出、警告、指标和日志是什么
-> 指标反映的真实问题是什么
-> 问题属于路网、需求、路线、控制器、代码还是实验设计
-> 最小下一步修改是什么
-> 重新运行哪些检查来观察反馈
```

例如，低到达率可能是路线断开、车辆插入失败、仿真时长不够或信号阻塞；高等待时间可能是相位-车道映射错误、TLS 合并错误、需求范围错误或控制策略不适合；teleport 是构建或控制反馈，不能被隐藏。

## 当前边界

- 可以构建 bbox/extract 输入的 SUMO 路网，也可以在只有地名且区域未确认时阻塞；完整自动地名解析仍是工作流检查点，不是静默构网步骤。
- 可以做道路筛选、OSM 去重、TLS 候选、多源 TLS 复核材料、连接性检查、连通核心路网提取、路线可达性、warning 观察和 Netedit 打开证据；不能声称自动认证整个城市路网。
- 如果原始 OSM 导入包含少量不连通碎片，Torii 会保留原始路网作为审计证据，并把后续检查切换到由最大 passenger component 生成的 `connected-core` 路网。
- 如果提取连通核心之后严格连通性仍然失败，Torii 会标为 `partial-main-component`：可以做诊断 smoke test，不能当作实验就绪路网。
- Google Maps 仍然是当前路网/TLS 清洗的必需基线 gate。OSM 标签、Mapillary、KartaView、官方清单、信号方案和现场照片可以增强复核；如果用户要求历史路网，则以用户声明的历史目标为准，并需要时间对齐的证据。
- 可以借助 SUMO Lights 等公开模式指导控制器实现；完整控制器生成和 controller-log inspection 仍是后续工具。
- 可以支持有证据边界的结论；不能认证实验一定正确。

## 许可证

源代码使用 MIT 许可证。

skill、文档、检查清单、示例和协议文本使用 Creative Commons Attribution 4.0 International (`CC BY 4.0`)。两个授权范围都写在 [`LICENSE`](LICENSE)。

## 商标说明

Eclipse SUMO 是 Eclipse Foundation 的商标。本项目只支持使用 Eclipse SUMO 的研究和工程工作流，不使用官方 Eclipse 或 Eclipse SUMO 标志。

Google Maps 只作为外部地图审查基线被引用。Torii 与 Google 无隶属关系，地图审查必须尊重用户指定的时间范围。
