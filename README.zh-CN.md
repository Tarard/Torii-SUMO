<p align="right">
  <a href="README.md"><img src="https://img.shields.io/badge/lang-English-blue" alt="English"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/lang-%E4%B8%AD%E6%96%87-red" alt="中文"></a>
  <a href="README.de.md"><img src="https://img.shields.io/badge/lang-Deutsch-green" alt="Deutsch"></a>
</p>

# Simulation Helper Skill for Eclipse SUMO

网站：[tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO](https://tarard.github.io/Simulation-Helper-Skill-for-Eclipse-SUMO/)

**面向交通信号控制实验的 Agent Skill**

这是一个可复用的 Codex/Claude skill 与检查清单，用于在报告结果前审计 SUMO/TraCI 交通信号控制实验。

```text
它是什么：   用于审计 SUMO/TraCI 信号控制工作流的可复用 agent skill。
面向谁：     使用 Eclipse SUMO 研究 fixed-time、actuated、max-pressure、data-informed 或 MPC-style 控制器的研究者。
如何工作：   精简的 SKILL.md 先作为场景路由器，只在需要时加载对应的 reference 模块。
信息来源：   它把 SUMO 官方文档、SUMO 论坛和社区常见排错经验、公开交通仿真代码模式，以及作者个人实验经验整理成聚焦的审计路径。
能发现什么： 破损路线文件、不安全 TLS 相位、未配对 baseline、被覆盖输出、无效指标报告、不可复现实验批次。
```

这个仓库被设计成一个实用研究工具，而不是论文包装。把 skill 复制到 Codex 或 Claude，让它检查 SUMO 实验，并用审计报告判断哪些结论可以被支持。

## 快速开始

对于 Codex，把 skill 文件夹复制到仓库级 skill 目录：

```text
.agents/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

对于 Claude Code，把同样的文件夹复制到：

```text
.claude/skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
```

然后在 agent 中调用：

```text
Use $simulation-helper-skill-for-eclipse-sumo to audit this SUMO/TraCI traffic signal control experiment before I report results.
```

如果是在调试失败实验：

```text
Use $debugging-helper-skill-for-eclipse-sumo to diagnose why this SUMO/TraCI run is invalid or unreproducible.
```

skill 应当先询问缺失的实验细节。SUMO 没有崩溃并不等于结果可以被认可。

## 项目状态

当前版本：仅包含指令型 skill 和检查清单。

本仓库目前包含 Markdown 形式的 agent skills、审计清单、示例和发布材料。它还不包含可执行的 SUMO validator 或 Python 审计脚本。

两个 `SKILL.md` 文件被刻意设计成轻量路由器。详细审计规则保存在 `references/` 中，由 agent 根据当前场景按需加载。

## 当前范围

当前版本聚焦于 SUMO/TraCI 交通信号控制实验。它还不是覆盖所有 Eclipse SUMO 用途的通用审计 skill。

这个版本覆盖 fixed-time、actuated、max-pressure、NEMA、data-informed 和 MPC-style 信号控制工作流。未来可以继续添加面向其他 SUMO 方向的审计 skill，例如 demand and routing、emissions and energy、public transport、pedestrian and intermodal scenarios、AV/CAV and co-simulation workflows、calibration、safety analysis，以及 mesoscopic 或 microscopic simulation-mode comparisons。

## Skill 列表

| Skill | 使用场景 | 用途 | 主要输出 |
|---|---|---|---|
| `simulation-helper-skill-for-eclipse-sumo` | 新实验设计、进行中项目筛查、代码修改、结果审计、结论审阅、发布检查。 | 规划、审阅、比较或撰写 SUMO/TraCI 信号控制实验结论。 | Project Control Screen、Experiment Readiness Record、SUMO Experiment Plan、hard-gate audit、evidence class、claim boundary。 |
| `debugging-helper-skill-for-eclipse-sumo` | 运行失败、无效路线、TraCI 协议问题、缺失输出、seed/completion/reproducibility 问题。 | 调试 route、TraCI、TLS、demand、detector、output、seed、completion 和 reproducibility 问题。 | Fault class、next diagnostic probe、evidence、fix or demotion rule。 |

两个 skill 都是普通的 `SKILL.md` 包，包含 YAML frontmatter 和 Markdown references。`SKILL.md` 保持紧凑，让 Codex/Claude 先判断用户所处场景，再只加载相关 reference 文件。`agents/openai.yaml` 提供可选的 Codex UI metadata；核心指令仍然可以被读取 `SKILL.md` 的 Claude-style skill loader 使用。

包内包含的 reference 模块：

**Simulation helper references**

- [`workflow-router.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/workflow-router.md) - 顶层场景路由器，用于决定先加载哪个 reference。
- [`project-control-screen.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/project-control-screen.md) - 进行中项目的目标、状态、偏差和下一步筛查。
- [`experiment-intake-interview.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-intake-interview.md) - 执行前的苏格拉底式提问与 Experiment Readiness Record。
- [`experiment-planning-after-intake.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-planning-after-intake.md) - intake 确认后的 SUMO Experiment Plan，用于在写代码、跑仿真或写结论前再次确认计划。
- [`tdd-for-sumo-traci-code.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/tdd-for-sumo-traci-code.md) - 面向 SUMO/TraCI controller、parser、runner 和 audit code 的 RED -> GREEN -> REFACTOR 工作流。
- [`verification-and-review-gates.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/verification-and-review-gates.md) - 完成前证据、代码审阅与 artifact 隔离 gate。
- [`source-ladder.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/source-ladder.md) - 信息来源优先级与证据层级。
- [`sumo-official-semantics.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-official-semantics.md) - SUMO network、route、TLS、detector 与 TraCI 语义。
- [`sumo-official-operational-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-official-operational-lessons.md) - 来自 SUMO 官方文档的运行经验。
- [`sumo-community-faq-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-community-faq-lessons.md) - 论坛、FAQ 与社区常见排错经验。
- [`sumo-nema-controller-audit.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-nema-controller-audit.md) - NEMA ring、barrier、split、recall、detector 与 claim 检查。
- [`sumo-traci-controller-boundaries.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-traci-controller-boundaries.md) - TraCI 控制器身份与 API 边界检查。
- [`sumo-output-hard-gates.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/sumo-output-hard-gates.md) - output、warning、teleport 与 artifact hard gates。
- [`evaluation-metrics-and-completion.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/evaluation-metrics-and-completion.md) - 指标定义与 completion-aware 报告。
- [`baseline-and-ablation-design.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/baseline-and-ablation-design.md) - paired baseline、ablation 与 sensitivity 设计。
- [`experiment-validation-ladder.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/experiment-validation-ladder.md) - 实验与调试修复的验证阶梯。
- [`field-lesson-capture.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/field-lesson-capture.md) - 以隐私安全方式记录用户后来发现的修复路径和可复用诊断经验。
- [`claim-boundary-taxonomy.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/claim-boundary-taxonomy.md) - 有证据边界的结论写法。
- [`public-code-lessons.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/public-code-lessons.md) - 从公开交通仿真代码中整理的经验。
- [`public-release-checklist.md`](skills/simulation-helper-skill-for-eclipse-sumo/references/public-release-checklist.md) - 发布、商标、隐私和曝光检查。

**Debugging audit references**

- [`closed-loop-debugging.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/closed-loop-debugging.md) - observe、classify、probe、compare、update 闭环调试。
- [`symptom-to-evidence-map.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/symptom-to-evidence-map.md) - 将常见症状映射到所需证据。
- [`debugging-gates-and-claim-boundaries.md`](skills/debugging-helper-skill-for-eclipse-sumo/references/debugging-gates-and-claim-boundaries.md) - 失败或部分修复实验的结论降级规则。

## 实际使用场景

| 场景 | 示例提示词 | 调用路径 | 预期输出 |
|---|---|---|---|
| 进行中项目，不知道下一步 | “用这个 skill 看一下我当前的 SUMO 项目，告诉我下一步做什么。” | `simulation-helper` -> `workflow-router.md` -> `project-control-screen.md` -> 按偏差进入对应 gate | Project Control Screen 和 Next Step Plan。 |
| 新实验设计 | “帮我设计一个 SUMO/TraCI 信号控制实验。” | `simulation-helper` -> `experiment-intake-interview.md` -> `experiment-planning-after-intake.md` | Experiment Readiness Record，然后是确认后的 SUMO Experiment Plan。 |
| controller 或 parser 代码修改 | “实现这个 TraCI metric parser/controller 修改。” | `simulation-helper` -> `tdd-for-sumo-traci-code.md` -> `verification-and-review-gates.md` | RED/GREEN/REFACTOR 记录和验证证据。 |
| SUMO 运行失败或行为异常 | “route 能加载但 tripinfo 为空 / TraCI 连接关闭。” | `debugging-helper` -> `closed-loop-debugging.md` -> `symptom-to-evidence-map.md` | Fault class、next probe、evidence、fix or demotion。 |
| 准备报告结果 | “我能根据这些 outputs 声称 controller A 更好吗？” | `simulation-helper` -> `sumo-output-hard-gates.md` -> `evaluation-metrics-and-completion.md` -> `baseline-and-ablation-design.md` -> `claim-boundary-taxonomy.md` | Evidence class 和允许/禁止的结论写法。 |
| 用户后来发现 skill 漏掉的解决路径 | “这个 skill 没解决，但我后来换了一条路径解决了。” | `simulation-helper` -> `field-lesson-capture.md` | Field Lesson Candidate 和隐私安全的 patch proposal。 |
| 公开发布检查 | “发布前检查一下 GitHub 仓库。” | `simulation-helper` -> `public-release-checklist.md` -> `verification-and-review-gates.md` | Release checklist、缺失项和 residual risk。 |

## 它审计什么

- TLS 相位与 movement-green 一致性。
- Socratic intake 之后、执行之前已确认的 SUMO Experiment Plan。
- route、config、additional file、detector 和 network 一致性。
- fixed-time、actuated、max-pressure、NEMA、data-informed 和 MPC-style 控制器比较。
- 配对 seeds、配对 demand、配对 output interval 和配对 simulation horizon。
- `tripinfo`、`summary`、`edgeData`、TLS switch output、controller logs、warnings、teleports 和 unfinished vehicles。
- 当仿真在车辆全部离网前停止时，使用 completion-aware metric reporting。
- Baseline、ablation、sensitivity runs 和 claim wording。
- 面向 controller、metric parser、route/config generator、validator 和 batch runner 的测试驱动 SUMO/TraCI 代码修改。
- 在声称实现、实验、比较或发布完成前，检查完成证据与代码审阅 gate。
- 当用户后来解决了 skill 没有覆盖的 SUMO/TraCI 问题时，捕获 field lesson，把可复用诊断路径抽象回 skill。

## 示例

每个示例都可以直接复制到 agent prompt 中：

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

从 `task.md` 开始，然后把 agent 输出和 `expected_audit_report.md` 对比。

## 常见失败检查清单

更长的清单见 `docs/common-sumo-signal-control-failures.md`。它覆盖如下问题：

1. SUMO 能运行，但 `tripinfo.xml` 为空。
2. TLS phase index 与预期 movement 不一致。
3. Max-pressure controller 使用未配对 seeds 比较。
4. 不同 controller 的 `edgeData` interval 不一致。
5. Data-informed weights 泄漏未来结果信息。
6. Route file 在 baseline 之间悄悄改变 demand。
7. 不同方法的 yellow 和 all-red 处理不一致。
8. 仿真在 demand 完成前停止。
9. 缺少 controller runtime 或 fallback behavior 记录。

## Skill 如何设计

设计遵循七个原则：

**Progressive disclosure。** `SKILL.md` 保持紧凑，只在需要时把 agent 引导到聚焦的 reference files。

**执行前的 Socratic intake 和实验计划。** 对于信息不足的实验，skill 会先针对 network、demand、controller、outputs、baselines、seeds 和 metrics 提问，建立 Experiment Readiness Record，然后在写代码、跑 SUMO 或写结论前生成并确认 SUMO Experiment Plan。

**实验代码前的 TDD。** 对于 controller、parser、runner、validator 和 audit script 修改，skill 使用 RED -> GREEN -> REFACTOR，让代码行为先由失败测试或可复现 probe 定义，再开始实现。

**结论前的 hard gates。** 审计会分开检查 SUMO 实际加载了什么、controller 实际做了什么、写出了哪些 outputs、出现了哪些 warnings，以及证据能支持什么 claim。

**完成前必须有证据。** 在声称代码、仿真运行、控制器比较、审计或公开发布完成前，skill 要求提供新的命令、artifacts、测试、审阅发现和 residual risk。

**闭环调试。** debugging skill 使用 observe -> classify -> probe -> compare -> update，让修复基于 artifacts，而不是试错式修改参数。

**通过 field lessons 自我进化。** 当用户通过另一条路径解决了 skill 漏掉的 SUMO/TraCI 问题时，skill 可以重建证据路径、抽象可复用规则、删去私人细节，并在用户确认后提出 skill 更新。

## 限制

本仓库提供 agent 指令、检查清单和审计流程。它不能认证一个 SUMO 实验是正确的。

这些 skill 不能替代人工审查、SUMO 官方文档、controller-specific validation 或独立复现。它们的目标是减少常见工作流错误，并把 claim boundaries 显式化。

审计输出应被视为 review support，而不是 formal verification result。

## 设计来源

本仓库借鉴了更广泛的 agent-skill 生态中的模式：

- Agent Skills convention：使用包含必需 `SKILL.md`、YAML frontmatter 和可选 resources 的自包含文件夹。
- 公开 skill 仓库，例如 `anthropics/skills`：仓库级 README、skill catalog、examples 和明确免责声明。
- `skill-creator` 和 `writing-skills` 中的 skill authoring 模式：精简 frontmatter、紧凑 `SKILL.md`、单层 references 和发布前验证。
- Superpowers 风格的工程纪律，例如 `test-driven-development`、`verification-before-completion`、`requesting-code-review` 和 `receiving-code-review`：先看失败测试，再写最小实现，green 后再重构，完成前必须有证据，并且用验证来处理审阅反馈，而不是盲目同意。
- 学术工作流 skill，例如 `academic-paper`、`academic-paper-reviewer` 和 `deep-research`：intake records、source hierarchy、evidence boundaries 和 claim calibration。
- 调试与控制闭环 skill，例如 `systematic-debugging` 和 `control-theory`：明确 target、observed state、deviation、next probe、feedback 和 residual risk。

运行时不需要外部 skill。上述来源影响了结构设计；可用包已经包含在本仓库中。

## 仓库结构

```text
README.md
README.zh-CN.md
README.de.md
LICENSE-DOCS
skills/
  simulation-helper-skill-for-eclipse-sumo/
  debugging-helper-skill-for-eclipse-sumo/
docs/
  common-sumo-signal-control-failures.md
  release/
examples/
  01_fixed_time_audit/
  02_max_pressure_audit/
  03_data_informed_signal_control_audit/
```

如果从更大的本地工作区准备公开仓库，请使用 `docs/release/public-repo-manifest.md`。

## GitHub Topics

建议 topics：

```text
sumo eclipse-sumo traci traffic-simulation traffic-signal-control transportation intelligent-transportation-systems max-pressure-control reproducibility research-software agent-skills codex claude
```

## 发布材料

`docs/release/` 下包含草稿材料：

- `github-topics.txt`
- `mailing-list-announcement.md`
- `linkedin-posts.md`
- `conference-positioning.md`
- `public-repo-manifest.md`

推荐定位是 “SUMO/TraCI signal-control experiments 的 reproducibility 和 error auditing”，而不是“新的学术结果”。

## 商标声明

Eclipse SUMO 是 Eclipse Foundation 的商标。本项目是独立的学术资源，不隶属于 Eclipse Foundation、Eclipse SUMO project 或 DLR，也未得到它们的认可、赞助或维护。

本项目用于支持使用 Eclipse SUMO 的学术和研究工作流。它不使用官方 Eclipse 或 Eclipse SUMO logo。

## 无担保或认证

本资源按原样提供，不保证正确性、完整性或适用于特定目的。通过审计清单并不意味着 SUMO 实验有效、可发表或被官方认证。

## 引用 Eclipse SUMO

本项目支持使用 Eclipse SUMO 的实验。如果你的研究使用 SUMO，请引用 SUMO project 推荐的官方 SUMO reference：

- Pablo Alvarez Lopez, Michael Behrisch, Laura Bieker-Walz, Jakob Erdmann, Yun-Pang Floetteroed, Robert Hilbrich, Leonhard Luecken, Johannes Rummel, Peter Wagner, and Evamarie Wiessner. "Microscopic Traffic Simulation using SUMO." IEEE Intelligent Transportation Systems Conference, 2018. DOI: `10.1109/ITSC.2018.8569938`.

Eclipse SUMO about 页面还说明，从 SUMO 1.2.0 起，每个 release 都有 release-specific DOI。

## License

本仓库中的 skill files、documentation、checklists 和 protocol text 使用 Creative Commons Attribution 4.0 International (`CC BY 4.0`) 许可。见 `LICENSE-DOCS`。

如果未来版本加入 Python audit scripts 或其他源码，应添加单独的代码许可，例如 MIT，并清楚说明许可拆分，例如 `LICENSE-CODE` 用于源码，`LICENSE-DOCS` 用于文本。

## 参考与相关资源

这些链接仅提供上下文，不表示对本仓库的认可。

- Eclipse SUMO documentation and licensing pages: [About Eclipse SUMO](https://eclipse.dev/sumo/about/), [SUMO FAQ](https://sumo.dlr.de/docs/FAQ.html), and [SUMO Downloads and Licensing Note](https://sumo.dlr.de/docs/Downloads.html).
- Eclipse Foundation trademark usage policy: [Eclipse Foundation Trademark Usage Policy](https://www.eclipse.org/legal/logo-guidelines/).
- Public agent-skill examples and conventions: [Anthropic public skills repository](https://github.com/anthropics/skills).
