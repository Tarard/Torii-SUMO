<p align="center">
  <img src="docs/assets/banner.png" alt="Torii 面向 SUMO 的 agent plugin 横幅">
</p>

# <img src="docs/assets/app-logo.png" width="42" alt="Torii 图标"> Torii

<div align="center">

**Task-Oriented Road Infrastructure Intelligence**

**Agent plugin for SUMO**

<img src="https://img.shields.io/badge/Agent%20Plugin-Codex%20%2F%20Claude-6f42c1" alt="Codex 和 Claude agent plugin">
<img src="https://img.shields.io/badge/SUMO%2FTraCI-%E4%BA%A4%E9%80%9A%E4%BB%BF%E7%9C%9F-blue" alt="SUMO 和 TraCI">
<img src="https://img.shields.io/badge/OSM%20to%20SUMO-%E8%B7%AF%E7%BD%91%E6%B8%85%E7%90%86-1d8e57" alt="OSM 到 SUMO 路网清理">
<img src="https://img.shields.io/badge/MCP%20Tools-local%20stdio-c98a05" alt="本地 stdio MCP tools">

<a href="https://tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO/"><strong>项目网站</strong></a> |
<a href="docs/codex-plugin-install.md"><strong>Codex 插件安装</strong></a> |
<a href="examples/01_fixed_time_audit/task.md"><strong>示例</strong></a> |
<a href="docs/common-sumo-signal-control-failures.md"><strong>失败清单</strong></a> |
<a href="LICENSE-CODE"><strong>MIT 代码许可</strong></a> |
<a href="LICENSE-DOCS"><strong>CC BY 4.0 文档许可</strong></a>

[English](README.md) | [简体中文](README.zh-CN.md) | [Deutsch](README.de.md)

</div>

> [!IMPORTANT]
> Torii 不是单纯的提示词或说明文档。它把 SUMO expert skill 和本地 stdio MCP 工具打包在一起，让 Codex/Claude 这类 coding agent 能够执行有限、可验证的 SUMO 检查。当前版本已经包含环境检查、配置预检、冒烟运行、证据包、OSM-to-SUMO 构网、TLS 候选审计和路线可达性检查；完整地名解析、整城级全自动 OSM 清洗和控制器自动生成还不是已经完成的 MCP 工具。

> [!NOTE]
> 本项目是独立项目，不隶属于 Eclipse Foundation、Eclipse SUMO、DLR、OpenAI、Anthropic、Google 或任何外部 OSM 工具项目，也不代表这些项目的认可、赞助或维护。

## Torii 是什么

Torii 的含义是 **Task-Oriented Road Infrastructure Intelligence**。它的目标是让 coding agent 在 SUMO 项目里像一个更有经验的工程师那样工作：先理解用户真正要的结果，再观察当前模型和输出，最后根据反馈做最小、可解释的修改。

| 层级 | 作用 |
|---|---|
| 推理层 | SUMO expert skill 负责理解意图、选择工作流、追问缺失证据、解释坏指标反映的建模问题。 |
| 执行层 | 本地 MCP server 负责运行受限工具，返回文件、日志、警告、指标、TLS 候选、路线和证据包等结构化观察。 |

安装 Torii 后，Codex 会同时获得 **skills and MCP tools**。它的目标不是盲目优化某个数字，而是把指标当作反馈信号：这个指标为什么坏、它反映了网络/需求/控制器/实验设计的什么问题、下一步最小修改是什么。

## 你可以怎么问

| 用户一句话 | Torii 应该怎么处理 |
|---|---|
| “用这块 OSM 区域构建 SUMO 路网。” | 使用 bbox 或本地 OSM extract，执行 tiled Overpass、重试、XML 去重、道路等级筛选和 `netconvert`。 |
| “清洗慕尼黑核心区路网。” | 如果给了 bbox 或 extract，就走已实现的 OSM-to-SUMO 工具链；如果只有地名，就先追问范围或进入 geocoding 工具开发路径。 |
| “把所有信号灯拿 Google Maps 对一下。” | 提取 SUMO TLS 候选点，聚类成物理路口审查组，生成 Google Maps 链接，并确认用户要对比当前地图还是历史目标日期。 |
| “检查这几条路/桥能不能通。” | 生成 named-road routeability probes，报告缺失关键边、路线生成证据和剩余 SUMO 完成风险。 |
| “指标变差了，帮我改。” | 把坏指标作为反馈，先诊断路线、需求、路网、TLS、控制器、输出、仿真时长或完成度问题，再提出修改。 |
| “给路网加最大压力控制。” | 使用内置 skill 和公开控制器模式给出计划、测试和验证路径；完整控制器生成仍是路线图工具。 |

## 快速开始

从 GitHub 安装：

```powershell
codex plugin marketplace add Tarard/Simulation-Helper-Skill-for-Eclipse-SUMO --ref main
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
| `sumo_preflight` / `sumo_get_environment` | 检查 SUMO、Python、TraCI 和本机工具链证据。 |
| `sumo_config_pair_preflight` | 检查一组 `.sumocfg` 的输入缺失和输出冲突。 |
| `sumo_run_config` / `sumo_run_minimal_smoke` | 运行受限 SUMO 配置或最小冒烟测试，返回日志和输出观察。 |
| `sumo_compare_outputs` / `sumo_collect_evidence` | 以完成度优先的方式比较结果并写出证据包。 |
| `sumo_osm_build_network` | OSM 下载或复用、Overpass 分块、重试、XML 去重、道路筛选和 `netconvert`。 |
| `sumo_tls_audit` | 提取 TLS 候选、聚类路口审查组，并附加 Google Maps 时间基线字段。 |
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

- 可以从 bbox/extract 构建 SUMO 路网；自然语言地名解析还不是完成的 MCP 工具。
- 可以做道路筛选、OSM 去重、TLS 候选、路线可达性和 warning 观察；不能声称自动认证整个城市路网。
- 可以把 Google Maps 当外部现实基线，但必须先确认用户要当前地图还是历史目标日期。
- 可以借助 SUMO Lights 等公开模式指导控制器实现；完整控制器生成和 controller-log inspection 仍是后续工具。
- 可以支持有证据边界的结论；不能认证实验一定正确。

## 许可证

源代码使用 MIT 许可证，见 [`LICENSE-CODE`](LICENSE-CODE)。

skill、文档、检查清单和协议文本使用 Creative Commons Attribution 4.0 International (`CC BY 4.0`)，见 [`LICENSE-DOCS`](LICENSE-DOCS)。

## 商标说明

Eclipse SUMO 是 Eclipse Foundation 的商标。本项目只支持使用 Eclipse SUMO 的研究和工程工作流，不使用官方 Eclipse 或 Eclipse SUMO 标志。

Google Maps 只作为外部地图审查基线被引用。Torii 与 Google 无隶属关系，地图审查必须尊重用户指定的时间范围。
