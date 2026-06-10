<p align="right">
  <a href="README.md"><img src="https://img.shields.io/badge/lang-English-blue" alt="English"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/lang-%E4%B8%AD%E6%96%87-red" alt="中文"></a>
  <a href="README.de.md"><img src="https://img.shields.io/badge/lang-Deutsch-green" alt="Deutsch"></a>
</p>

<p align="center">
  <img src="docs/assets/traffic-lights-icon.svg" width="96" alt="交通信号灯图标">
</p>

<h1 align="center">🚦 Simulation Helper Skill for Eclipse SUMO</h1>

<p align="center">
  一个面向 Codex/Claude 的轻量 skill 包，用于在结果变成结论之前审计 SUMO/TraCI 交通信号控制实验。
</p>

<p align="center">
  <a href="https://tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO/"><strong>🌐 项目网站</strong></a>
  ·
  <a href="examples/01_fixed_time_audit/task.md"><strong>🧪 示例</strong></a>
  ·
  <a href="docs/common-sumo-signal-control-failures.md"><strong>🚨 常见失败清单</strong></a>
  ·
  <a href="LICENSE-DOCS"><strong>📄 CC BY 4.0</strong></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/SUMO%2FTraCI-signal%20control-blue" alt="SUMO/TraCI signal control">
  <img src="https://img.shields.io/badge/Agent-Codex%20%2F%20Claude-6f42c1" alt="Codex and Claude">
  <img src="https://img.shields.io/badge/Skill%20Files-2-1d8e57" alt="Two skills">
  <img src="https://img.shields.io/badge/Reference%20Modules-23-c98a05" alt="23 reference modules">
</p>

> [!IMPORTANT]
> 当前版本聚焦于 **SUMO/TraCI 交通信号控制实验**。它还不是覆盖所有 Eclipse SUMO 用途的通用审计包。

> [!NOTE]
> 这是一个独立的学术工作流资源。它不隶属于 Eclipse Foundation、Eclipse SUMO 项目或 DLR，也不代表这些组织的认可、赞助或维护。

## 🔥 为什么需要它

SUMO 能顺利跑完，并不代表实验结果已经可以作为有效证据。

这个 skill 针对的是那些经常到最后才暴露的问题：

- 🚧 route 或 demand 在 baseline 之间悄悄改变
- 🚦 TLS 相位索引和预期 movement 不一致
- 🧾 `tripinfo`、`summary` 或 `edgeData` 缺失或被覆盖
- 🧪 controller 对比没有按 seed、horizon、demand 和 output 配对
- ⏳ simulation 在 demand 完成前就停止
- 📉 只统计 arrived vehicles，掩盖未完成车辆
- 📝 论文或报告中的 claim 超过了结果证据能支持的范围

## 🧠 它做什么

```text
它是什么：     面向 SUMO/TraCI signal-control workflow 的可复用 Codex/Claude skill 包。
面向谁：       使用 Eclipse SUMO 研究 fixed-time、actuated、max-pressure、NEMA、data-informed 或 MPC-style controller 的研究者。
如何工作：     精简的 SKILL.md 先作为 scenario router，只在需要时加载对应 reference 模块。
信息来源：     SUMO 官方文档、SUMO FAQ/forum 经验、公开交通仿真代码模式，以及作者自己的实验实践。
能发现什么：   破损 route、不安全 TLS phase、未配对 baseline、被覆盖 output、无效 metric、不可复现 batch。
```

这个仓库现在不是 Python validator。它是一个 **review protocol 和 agent skill**：把它复制到 Codex 或 Claude，让 agent 检查 SUMO 实验仓库，再用 audit output 判断哪些结论可以被支持。

## ⚡ 快速开始

对于 **Codex**，把 skill 文件夹复制到仓库级 skill 目录：

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

然后在 agent 中调用：

```text
Use $simulation-helper-skill-for-eclipse-sumo to audit this SUMO/TraCI traffic signal control experiment before I report results.
```

如果是失败或可疑的运行：

```text
Use $debugging-helper-skill-for-eclipse-sumo to diagnose why this SUMO/TraCI run is invalid or unreproducible.
```

skill 应当先询问缺失的实验细节。SUMO 没有崩溃，不等于结果可以被认可。

## 🧩 Skill 列表

| Skill | 什么时候用 | 主要输出 |
|---|---|---|
| `simulation-helper-skill-for-eclipse-sumo` | 规划、审计、对比、写代码、发布检查，以及为 SUMO/TraCI signal-control 实验写有证据边界的 claim。 | Project Control Screen、Experiment Readiness Record、SUMO Experiment Plan、evidence class、claim boundary、next-step plan。 |
| `debugging-helper-skill-for-eclipse-sumo` | SUMO/TraCI route、demand、detector、TLS、output、seed、completion、reproducibility 或 runtime failure。 | Fault class、next diagnostic probe、evidence、fix/rerun/demotion decision。 |

两个 `SKILL.md` 都保持精简。agent 会先判断使用场景，再只加载相关 reference 模块。

## 🗺️ 场景路由

| 场景 | 加载内容 | 预期输出 |
|---|---|---|
| 🧭 进行中项目、进度不清、或不知道下一步 | `workflow-router.md` -> `project-control-screen.md` | Project Control Screen 和 next-step plan |
| 🧪 新实验或模糊实验想法 | `experiment-intake-interview.md` -> `experiment-planning-after-intake.md` | Experiment Readiness Record，然后生成 SUMO Experiment Plan |
| 🧯 失败或可疑运行 | `debugging-helper-skill-for-eclipse-sumo` | root cause、next probe、fix/rerun/demotion |
| 🧑‍💻 controller、parser、runner、validator 或 audit-code 修改 | `tdd-for-sumo-traci-code.md` -> `verification-and-review-gates.md` | RED/GREEN/REFACTOR 或明确的 `test-after` 记录 |
| 📊 结果、metric、baseline comparison 或论文/report claim | output、metric、baseline 和 claim-boundary references | evidence class 和允许/禁止的 claim wording |
| 🧬 用户发现了 skill 没覆盖的新解决路径 | `field-lesson-capture.md` | 脱敏后的 field lesson candidate |
| 🚀 公开发布前检查 | `public-release-checklist.md` -> `verification-and-review-gates.md` | release checklist 和 residual risk |

## 📦 Reference 模块

<details>
<summary><strong>🧠 Simulation helper references</strong></summary>

- [`workflow-router.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/workflow-router.md) - 顶层 scenario router。
- [`project-control-screen.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/project-control-screen.md) - 面向进行中项目的 target、state、deviation 和 next-step screen。
- [`experiment-intake-interview.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-intake-interview.md) - 实验前 Socratic questions 和 Experiment Readiness Record。
- [`experiment-planning-after-intake.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-planning-after-intake.md) - code、simulation 或 claim 之前确认 SUMO Experiment Plan。
- [`tdd-for-sumo-traci-code.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/tdd-for-sumo-traci-code.md) - SUMO/TraCI 代码修改的 RED -> GREEN -> REFACTOR workflow。
- [`verification-and-review-gates.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/verification-and-review-gates.md) - evidence-before-completion 和 review gates。
- [`source-ladder.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/source-ladder.md) - source priority 和 evidence hierarchy。
- [`sumo-official-semantics.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-official-semantics.md) - SUMO network、route、TLS、detector 和 TraCI semantics。
- [`sumo-official-operational-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-official-operational-lessons.md) - 来自 SUMO 官方文档的 operational lessons。
- [`sumo-community-faq-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-community-faq-lessons.md) - forum、FAQ 和 community troubleshooting lessons。
- [`sumo-nema-controller-audit.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-nema-controller-audit.md) - NEMA ring、barrier、split、recall、detector 和 claim checks。
- [`sumo-traci-controller-boundaries.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-traci-controller-boundaries.md) - TraCI controller identity 和 API-boundary checks。
- [`sumo-output-hard-gates.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-output-hard-gates.md) - output、warning、teleport 和 artifact gates。
- [`evaluation-metrics-and-completion.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/evaluation-metrics-and-completion.md) - metric definitions 和 completion-aware reporting。
- [`baseline-and-ablation-design.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/baseline-and-ablation-design.md) - paired baseline、ablation 和 sensitivity design。
- [`experiment-validation-ladder.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-validation-ladder.md) - 实验和 debugging fix 的 validation ladder。
- [`field-lesson-capture.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/field-lesson-capture.md) - 对用户实际发现的 fix 做脱敏、抽象和复用。
- [`claim-boundary-taxonomy.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/claim-boundary-taxonomy.md) - evidence-bounded claim wording。
- [`public-code-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/public-code-lessons.md) - 从公开交通仿真代码中提炼的 lessons。
- [`public-release-checklist.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/public-release-checklist.md) - release、trademark、privacy 和 exposure checks。

</details>

<details>
<summary><strong>🧯 Debugging references</strong></summary>

- [`closed-loop-debugging.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/closed-loop-debugging.md) - observe、classify、probe、compare、update。
- [`symptom-to-evidence-map.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/symptom-to-evidence-map.md) - 把常见 symptom 映射到 required evidence。
- [`debugging-gates-and-claim-boundaries.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/debugging-gates-and-claim-boundaries.md) - 对失败或部分修复的 run 给出 demotion rules。

</details>

## 🧪 示例

每个示例都可以直接作为 prompt 使用：

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
Use $simulation-helper-skill-for-eclipse-sumo on examples/02_max_pressure_audit/task.md and produce an evidence-bounded audit report.
```

## ✅ 它审计什么

- 🛣️ network、route、config、detector 和 additional file
- 🚦 TLS phase、movement-green、yellow、all-red 和 NEMA evidence
- 🔁 paired seeds、demand、outputs、simulation horizons 和 baselines
- 📦 `tripinfo`、`summary`、`edgeData`、TLS switch output、controller logs、warnings、teleports 和 unfinished vehicles
- 📊 travel time、delay、stops、throughput、queue、emissions、fairness 和 completion-aware reporting
- 🧪 fixed-time、actuated、max-pressure、NEMA、data-informed 和 MPC-style controller comparisons
- 🧑‍💻 SUMO/TraCI controller、metric parser、runner、validator 和 audit-code 修改的 TDD records
- 🧬 用户发现的新 fix，可以沉淀成可复用 guidance

更完整的失败案例见 [`docs/common-sumo-signal-control-failures.md`](docs/common-sumo-signal-control-failures.md)。

## 🛠️ 设计原则

- 🧭 **Progressive disclosure：** `SKILL.md` 保持紧凑，只在需要时路由到 focused references。
- ❓ **Socratic intake：** 模糊实验先变成 Experiment Readiness Record，再开始执行。
- 🧪 **TDD before experiment code：** 会改变行为的代码应尽量从 failing test 或 reproducible probe 开始。
- 🚧 **Hard gates before claims：** output、warning、completion 和 baseline pairing 必须支撑 claim。
- 🔍 **Evidence before completion：** 没有新的 command、artifact、test 和 residual risk 记录，就不能声称完成。
- 🧯 **Debugging as a closed loop：** observe -> classify -> probe -> compare -> update。
- 🧬 **Self-evolution：** skill 没覆盖的真实 fix 可以变成脱敏后的 field lesson candidate。

## 🧭 项目状态

当前版本：**仅包含指令型 skill 和 checklist package**。

本仓库包含 Markdown-based agent skills、audit checklists、examples、documentation 和 release materials。它目前还不包含可执行 SUMO validator 或 Python audit script。

### Roadmap

- 🚦 持续增强 signal-control audit coverage
- 🧪 添加更多 bad-case/fixed-case examples
- 🧰 当模式稳定后，添加可选 Python validators
- 🌍 未来扩展到其他 SUMO 方向，例如 routing and demand、emissions and energy、public transport、pedestrian/intermodal scenarios、AV/CAV and co-simulation、calibration、safety analysis 和 simulation-mode comparison

## ❓ FAQ

**我需要手动调用 skill 吗？**

通常需要。想要明确走 audit path 时，使用 `$simulation-helper-skill-for-eclipse-sumo`。

**它能认证我的 SUMO 实验正确吗？**

不能。它提供 review support，不是 formal verification，也不是官方 certification。

**为什么 `SKILL.md` 要保持短？**

因为 agent context 有限制。skill 应该先路由到正确的 evidence rules，而不是一次性加载所有 checklist。

**它能调试失败的 SUMO run 吗？**

可以。route、TraCI、TLS、output、seed、completion 和 reproducibility failure 使用 `$debugging-helper-skill-for-eclipse-sumo`。

**它能从用户后续发现的 fix 中学习吗？**

可以。field-lesson workflow 会抽象可复用 diagnostic path，去除私人细节，并在持久化更新前请求确认。

## ⚠️ 限制

本仓库提供 agent instructions、checklists 和 audit procedures。它不能认证一个 SUMO 实验一定正确。

这些 skill 不能替代 manual review、SUMO documentation、controller-specific validation 或 independent reproduction。audit output 应被视为 review support，而不是 formal verification result。

## ™️ 商标说明

Eclipse SUMO 是 Eclipse Foundation 的商标。本项目是独立项目，不隶属于 Eclipse Foundation、Eclipse SUMO project 或 DLR，也不代表这些组织的认可、赞助或维护。

本项目支持使用 Eclipse SUMO 的学术和研究工作流。它不使用官方 Eclipse 或 Eclipse SUMO logo。

## 📚 引用 Eclipse SUMO

如果你的研究使用 SUMO，请引用 SUMO 项目推荐的官方参考文献：

- Pablo Alvarez Lopez, Michael Behrisch, Laura Bieker-Walz, Jakob Erdmann, Yun-Pang Floetteroed, Robert Hilbrich, Leonhard Luecken, Johannes Rummel, Peter Wagner, and Evamarie Wiessner. "Microscopic Traffic Simulation using SUMO." IEEE Intelligent Transportation Systems Conference, 2018. DOI: `10.1109/ITSC.2018.8569938`。

Eclipse SUMO about 页面还说明，从 SUMO 1.2.0 起，release-specific DOI 已经提供。

## 📄 License

本仓库中的 skill files、documentation、checklists 和 protocol text 使用 Creative Commons Attribution 4.0 International (`CC BY 4.0`)。见 [`LICENSE-DOCS`](LICENSE-DOCS)。

如果未来加入 Python audit scripts 或其他 source code，应添加单独的 code license，例如 MIT，并清楚区分 `LICENSE-CODE` 和 `LICENSE-DOCS`。

## 🔗 References and Related Resources

这些链接提供背景资料，不代表对本仓库的 endorsement。

- Eclipse SUMO documentation and licensing pages: [About Eclipse SUMO](https://eclipse.dev/sumo/about/), [SUMO FAQ](https://sumo.dlr.de/docs/FAQ.html), and [SUMO Downloads and Licensing Note](https://sumo.dlr.de/docs/Downloads.html).
- Eclipse Foundation trademark usage policy: [Eclipse Foundation Trademark Usage Policy](https://www.eclipse.org/legal/logo-guidelines/).
- Public agent-skill examples and conventions: [Anthropic public skills repository](https://github.com/anthropics/skills).

## ⭐ 支持

如果这个 checklist 帮你避免了一个破损的 SUMO/TraCI 实验，欢迎 star 这个仓库，并把 examples 改造成你自己的研究工作流。
