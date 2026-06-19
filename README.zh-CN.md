<p align="center">
  <img src="docs/assets/banner.png" alt="Eclipse SUMO 仿真助手横幅">
</p>

# <img src="docs/assets/app-logo.png" width="42" alt="应用图标"> Eclipse SUMO 仿真助手技能

<div align="center">

**思辨。计划。构造。纠错。检验。报告。**

**由 Codex 和 Claude 引导的完整 SUMO/TraCI 实验工作流。**

<img src="https://img.shields.io/badge/SUMO%2FTraCI-%E4%BF%A1%E5%8F%B7%E6%8E%A7%E5%88%B6-blue" alt="SUMO/TraCI 信号控制">
<img src="https://img.shields.io/badge/%E5%8A%A9%E6%89%8B-Codex%2FClaude-6f42c1" alt="Codex 和 Claude">
<img src="https://img.shields.io/badge/%E6%8A%80%E8%83%BD%E6%96%87%E4%BB%B6-2-1d8e57" alt="两个技能文件">
<img src="https://img.shields.io/badge/%E5%8F%82%E8%80%83%E6%A8%A1%E5%9D%97-12-c98a05" alt="十二个参考模块">

<a href="https://tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO/"><strong>项目网站</strong></a> |
<a href="examples/01_fixed_time_audit/task.md"><strong>示例</strong></a> |
<a href="docs/common-sumo-signal-control-failures.md"><strong>常见失败清单</strong></a> |
<a href="LICENSE-DOCS"><strong>CC BY 4.0</strong></a>

[英文版](README.md) | [简体中文](README.zh-CN.md) | [德语版](README.de.md)

</div>

> [!IMPORTANT]
> 当前版本聚焦于 **SUMO/TraCI 交通信号控制实验**。它还不是覆盖所有 Eclipse SUMO 用途的通用审计包。

> [!NOTE]
> 这是一个独立的学术工作流资源。它不隶属于 Eclipse Foundation、Eclipse SUMO 项目或 DLR，也不代表这些组织的认可、赞助或维护。

## 🔥 为什么需要它

SUMO 能顺利跑完，并不代表实验结果已经可以作为有效证据。

这个技能针对的是那些经常到最后才暴露的问题：

- 路线或需求在对照方法之间悄悄改变
- TLS 相位索引和预期通行方向不一致
- `tripinfo`、`summary` 或 `edgeData` 缺失或被覆盖
- 控制器对比没有按随机种子、仿真时长、需求和输出配对
- 仿真在需求完成前就停止
- 只统计已到达车辆，掩盖未完成车辆
- 论文或报告中的结论超过了结果证据能支持的范围

## 🧠 它做什么

```text
它是什么：     面向 Codex 和 Claude 的可复用 SUMO 技能，聚焦完整 SUMO/TraCI 信号控制实验工作流。
面向谁：       使用 Eclipse SUMO 研究定时控制、感应控制、最大压力控制、NEMA、数据辅助控制或 MPC 类控制器的研究者。
如何工作：     精简的 SKILL.md 先作为场景路由器，只在需要时加载对应参考模块。
信息来源：     SUMO 官方文档、SUMO 常见问题和论坛经验、公开交通仿真代码模式，以及作者自己的实验实践。
能发现什么：   破损路线、不安全 TLS 相位、未配对对照方法、被覆盖输出、无效指标、不可复现实验批次。
```

这个仓库目前不是 Python 验证器。它是一个 **工作流协议和助手技能**：把它复制到 Codex 或 Claude，让助手围绕 SUMO 实验仓库进行结构化检查，并用这些记录来计划、纠错、检验和报告有证据边界的结论。

## ⚡ 快速开始

对于 **Codex**，把技能文件夹复制到仓库级技能目录：

```text
.agents/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

对于 **Claude Code**，把同样的文件夹复制到：

```text
.claude/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

然后在助手中调用：

```text
请使用 $simulation-helper-skill-for-eclipse-sumo，在我报告结果之前审计这个 SUMO/TraCI 交通信号控制实验。
```

如果是失败或可疑的运行：

```text
请使用 $debugging-helper-skill-for-eclipse-sumo，诊断为什么这个 SUMO/TraCI 运行无效或不可复现。
```

技能应当先询问缺失的实验细节。SUMO 没有崩溃，不等于结果可以被认可。

## 🧩 技能列表

| 技能 | 什么时候用 | 主要输出 |
|---|---|---|
| `simulation-helper-skill-for-eclipse-sumo` | 规划、审计、对比、代码修改、发布检查，以及为 SUMO/TraCI 信号控制实验撰写有证据边界的结论。 | 项目控制筛查记录、实验就绪记录、SUMO 实验计划、证据等级、结论边界、下一步计划。 |
| `debugging-helper-skill-for-eclipse-sumo` | SUMO/TraCI 路线、需求、检测器、TLS、输出、随机种子、完成度、可复现性或运行时失败。 | 故障类别、下一步诊断检查、证据、修复/重跑/降级决策。 |

两个 `SKILL.md` 都保持精简。助手会先判断使用场景，再只加载相关参考模块。

## 🗺️ 场景路由

| 场景 | 加载内容 | 预期输出 |
|---|---|---|
| 新机器、新克隆、缺少 SUMO 运行证据或环境可疑 | `preflight-sumo-environment.md` | 环境前置检查记录和冒烟测试通过/失败路径 |
| OSM/导入路网清理、路网细致程度选择、Google Maps/外部地图信号核查、检测器映射或实测数据对齐 | `model-osm-detectors.md` | 建模计划、道路等级阶梯、TLS 审计、检测器对齐门槛和可视化边界 |
| 进行中项目、进度不清、或不知道下一步 | `route-project-workflow.md` | 项目控制筛查记录和下一步计划 |
| 新实验或模糊实验想法 | `plan-experiment.md` | 实验就绪记录，然后生成 SUMO 实验计划 |
| 失败或可疑运行 | `debugging-helper-skill-for-eclipse-sumo` | 根因、下一步检查、修复/重跑/降级 |
| 控制器、解析器、运行器、验证器或审计代码修改 | `develop-and-verify-code.md` | 红灯/绿灯/重构记录，或明确的 `test-after` 记录 |
| 控制器/TLS/NEMA/TraCI 边界问题 | `audit-sumo-controllers.md` | 控制器身份、API 边界和缺失证据 |
| 固定范围走廊扰动或控制器信息对比 | `compare-corridor-perturbations.md` | 配对扰动逻辑、负向对照和结论边界 |
| SUMO 语义、官方/论坛经验或公开代码模式 | `learn-sumo-knowledge.md` | 有来源边界的经验和所需证据 |
| 结果、指标、对照方法比较或论文/报告结论 | `evaluate-and-report-results.md` | 证据等级，以及允许/禁止的结论表述 |
| 用户发现了技能没覆盖的新解决路径 | `capture-field-lesson.md` | 脱敏后的现场经验候选条目 |
| 公开发布前检查 | `release-project.md` | 发布清单和剩余风险 |

## 🔗 技能结构

这个包采用“精简入口 + 深层参考”的结构。`SKILL.md` 保持足够短，方便 Codex 和 Claude 快速加载；聚焦的参考文件负责承载详细的 SUMO/TraCI 实验工作流。

```text
skills/
├─ simulation-helper-skill-for-eclipse-sumo/      # 主工作流技能
│  ├─ SKILL.md                                    # 场景路由和启用规则
│  │  ├─ 什么时候使用这个技能
│  │  ├─ 思辨 -> 计划 -> 构造 -> 纠错 -> 检验 -> 报告
│  │  ├─ 必要输出和结论边界
│  │  └─ 指向聚焦参考模块的链接
│  ├─ agents/
│  │  └─ openai.yaml                             # Codex/OpenAI 元数据
│  └─ references/                                # 深层工作流文档
│     ├─ route-project-workflow.md               # 按场景路由并筛查项目状态
│     ├─ preflight-sumo-environment.md           # SUMO/Python 工具链证据
│     ├─ plan-experiment.md                      # 苏格拉底式追问和 SUMO 实验计划
│     ├─ develop-and-verify-code.md              # 红灯/绿灯/重构和完成证据
│     ├─ model-osm-detectors.md                  # OSM/导入路网、信号核查和检测器对齐
│     ├─ learn-sumo-knowledge.md                 # 官方、论坛和公开代码经验
│     ├─ audit-sumo-controllers.md               # NEMA/TLS/TraCI 控制器边界
│     ├─ compare-corridor-perturbations.md       # 固定范围扰动对比
│     ├─ evaluate-and-report-results.md          # 输出、指标、对照和结论
│     ├─ capture-field-lesson.md                 # 自我进化的现场经验捕获
│     └─ release-project.md                      # 发布、商标、隐私和传播
│
├─ debugging-helper-skill-for-eclipse-sumo/       # 聚焦调试子技能
│  ├─ SKILL.md                                    # 调试启用规则和工作流
│  ├─ agents/openai.yaml                          # Codex/OpenAI 元数据
│  └─ references/
│     └─ debug-sumo-traci.md                      # 观察、分类、检查、降级
│
└─ examples/                                      # 可直接作为提示使用的审计场景
   ├─ 01_fixed_time_audit/
   ├─ 02_max_pressure_audit/
   └─ 03_data_informed_signal_control_audit/
```

<details>
<summary><strong>仿真助手参考模块</strong></summary>

- [`route-project-workflow.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/route-project-workflow.md) - 场景路由和项目状态筛查。
- [`preflight-sumo-environment.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/preflight-sumo-environment.md) - SUMO/Python 环境证据和最小冒烟测试门槛。
- [`plan-experiment.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/plan-experiment.md) - 苏格拉底式追问、实验就绪记录和确认后的 SUMO 实验计划。
- [`develop-and-verify-code.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/develop-and-verify-code.md) - SUMO/TraCI 代码修改的红灯 -> 绿灯 -> 重构流程和完成证据。
- [`model-osm-detectors.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/model-osm-detectors.md) - OSM/导入路网建模、路网细致程度选择、Google Maps/外部信号核查、冗余 TLS 清理、检测器映射和实测数据对齐。
- [`learn-sumo-knowledge.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/learn-sumo-knowledge.md) - 来源层级、官方语义、论坛经验和公开代码模式。
- [`audit-sumo-controllers.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/audit-sumo-controllers.md) - NEMA/TLS/TraCI 控制器身份和 API 边界检查。
- [`compare-corridor-perturbations.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/compare-corridor-perturbations.md) - 固定范围扰动对比、信息对照和结论边界。
- [`evaluate-and-report-results.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/evaluate-and-report-results.md) - 输出、指标、完成度、对照方法、验证阶梯和结论表述。
- [`capture-field-lesson.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/capture-field-lesson.md) - 对用户实际发现的修复方法做脱敏、抽象和复用。
- [`release-project.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/release-project.md) - 发布、商标、隐私和传播检查。

</details>

<details>
<summary><strong>调试参考模块</strong></summary>

- [`debug-sumo-traci.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/debug-sumo-traci.md) - 闭环诊断、症状检查和结论降级规则。

</details>

## 🧪 示例

每个示例都可以直接作为提示使用：

```text
examples/
  01_fixed_time_audit/
    task.md
    expected_audit_report.md
    bad_case/
    fixed_case/
  02_max_pressure_audit/
    task.md
    expected_audit_report.md
    bad_case/
    fixed_case/
  03_data_informed_signal_control_audit/
    task.md
    expected_audit_report.md
    bad_case/
    fixed_case/
```

可以这样试：

```text
请使用 $simulation-helper-skill-for-eclipse-sumo 处理 examples/02_max_pressure_audit/task.md，并生成有证据边界的审计报告。
```

## ✅ 它审计什么

- 路网、路线、配置、检测器和附加文件
- TLS 相位、通行方向放行、黄灯、全红和 NEMA 证据
- 配对随机种子、需求、输出、仿真时长和对照方法
- `tripinfo`、`summary`、`edgeData`、TLS 切换输出、控制器日志、警告、车辆传送和未完成车辆
- 行程时间、延误、停车次数、通过量、队列、排放、公平性和完成度感知报告
- 定时控制、感应控制、最大压力控制、NEMA、数据辅助控制和 MPC 类控制器对比
- SUMO/TraCI 控制器、指标解析器、运行器、验证器和审计代码修改的测试驱动记录
- 用户发现的新修复方法，可以沉淀成可复用指导

更完整的失败案例见 [`docs/common-sumo-signal-control-failures.md`](docs/common-sumo-signal-control-failures.md)。

## 🛠️ 设计原则

- **逐步揭示：** `SKILL.md` 保持紧凑，只在需要时路由到聚焦的参考模块。
- **苏格拉底式追问：** 模糊实验先变成实验就绪记录，再开始执行。
- **实验代码先测试：** 会改变行为的代码应尽量从失败测试或可复现检查开始。
- **结论前先过硬门槛：** 输出、警告、完成度和对照配对必须支撑结论。
- **完成前先有证据：** 没有新的命令、产物、测试和剩余风险记录，就不能声称完成。
- **闭环调试：** 观察 -> 分类 -> 检查 -> 比较 -> 更新。
- **自我演化：** 技能没覆盖的真实修复方法可以变成脱敏后的现场经验候选条目。

## 🧭 项目状态

当前版本：**仅包含指令型技能和检查清单包**。

本仓库包含基于 Markdown 的助手技能、审计清单、示例、文档和发布材料。它目前还不包含可执行 SUMO 验证器或 Python 审计脚本。

### 发展路线

- 持续增强信号控制审计覆盖范围
- 添加更多错误案例/修复案例示例
- 当模式稳定后，添加可选 Python 验证器
- 未来扩展到其他 SUMO 方向，例如路线与需求、排放与能耗、公共交通、行人与多模式场景、自动驾驶/网联自动驾驶与联合仿真、校准、安全分析和仿真模式比较

## ❓ 常见问题

**我需要手动调用技能吗？**

通常需要。想要明确走审计路径时，使用 `$simulation-helper-skill-for-eclipse-sumo`。

**它能认证我的 SUMO 实验正确吗？**

不能。它提供审阅支持，不是形式化验证，也不是官方认证。

**为什么 `SKILL.md` 要保持短？**

因为助手上下文有限。技能应该先路由到正确的证据规则，而不是一次性加载所有检查清单。

**它能调试失败的 SUMO 运行吗？**

可以。路线、TraCI、TLS、输出、随机种子、完成度和可复现性失败使用 `$debugging-helper-skill-for-eclipse-sumo`。

**它能从用户后续发现的修复方法中学习吗？**

可以。现场经验流程会抽象可复用诊断路径，去除私人细节，并在持久化更新前请求确认。

## ⚠️ 限制

本仓库提供助手指令、检查清单和审计流程。它不能认证一个 SUMO 实验一定正确。

这些技能不能替代人工审阅、SUMO 文档、控制器专项验证或独立复现。审计输出应被视为审阅支持，而不是形式化验证结果。

## ™️ 商标说明

Eclipse SUMO 是 Eclipse Foundation 的商标。本项目是独立项目，不隶属于 Eclipse Foundation、Eclipse SUMO 项目或 DLR，也不代表这些组织的认可、赞助或维护。

本项目支持使用 Eclipse SUMO 的学术和研究工作流。它不使用官方 Eclipse 或 Eclipse SUMO 标志。

## 📚 引用 Eclipse SUMO

如果你的研究使用 SUMO，请引用 SUMO 项目推荐的官方参考文献：

- Pablo Alvarez Lopez, Michael Behrisch, Laura Bieker-Walz, Jakob Erdmann, Yun-Pang Floetteroed, Robert Hilbrich, Leonhard Luecken, Johannes Rummel, Peter Wagner, and Evamarie Wiessner. "Microscopic Traffic Simulation using SUMO." IEEE Intelligent Transportation Systems Conference, 2018. DOI: `10.1109/ITSC.2018.8569938`。

Eclipse SUMO 介绍页面还说明，从 SUMO 1.2.0 起，已提供版本专属 DOI。

## 📄 许可证

本仓库中的技能文件、文档、检查清单和协议文本使用 Creative Commons Attribution 4.0 International (`CC BY 4.0`)。见 [`LICENSE-DOCS`](LICENSE-DOCS)。

如果未来加入 Python 审计脚本或其他源代码，应添加单独的代码许可证，例如 MIT，并清楚区分 `LICENSE-CODE` 和 `LICENSE-DOCS`。

## 🔗 参考资料和相关资源

这些链接提供背景资料，不代表对本仓库的认可。

- Eclipse SUMO 文档和许可页面：[Eclipse SUMO 介绍](https://eclipse.dev/sumo/about/)、[SUMO 常见问题](https://sumo.dlr.de/docs/FAQ.html)、[SUMO 下载与许可说明](https://sumo.dlr.de/docs/Downloads.html)。
- Eclipse Foundation 商标使用政策：[Eclipse Foundation 商标使用政策](https://www.eclipse.org/legal/logo-guidelines/)。
- 公开助手技能示例和约定：[Anthropic 公开技能仓库](https://github.com/anthropics/skills)。

## ⭐ 支持

如果这个检查清单帮你避免了一个破损的 SUMO/TraCI 实验，欢迎给这个仓库加星，并把示例改造成你自己的研究工作流。

## 🔖 存档

版本发布已在 Zenodo 存档：https://doi.org/10.5281/zenodo.20627976
