<p align="right">
  <a href="README.md"><img src="https://img.shields.io/badge/lang-English-blue" alt="English"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/lang-%E4%B8%AD%E6%96%87-red" alt="中文"></a>
  <a href="README.de.md"><img src="https://img.shields.io/badge/lang-Deutsch-green" alt="Deutsch"></a>
</p>

# Academic Audit for Eclipse SUMO

**面向交通信号控制实验的 Agent Skill**

这是一个可复用的 Codex/Claude skill 与检查清单，用于在报告结果前审计 SUMO/TraCI 交通信号控制实验。

```text
它是什么：   用于审计 SUMO/TraCI 信号控制工作流的可复用 agent skill。
面向谁：     使用 Eclipse SUMO 研究 fixed-time、actuated、max-pressure、data-informed 或 MPC-style 控制器的研究者。
能发现什么： 破损路线文件、不安全 TLS 相位、未配对 baseline、被覆盖输出、无效指标报告、不可复现实验批次。
```

这个仓库被设计成一个实用研究工具，而不是论文包装。把 skill 复制到 Codex 或 Claude，让它检查 SUMO 实验，并用审计报告判断哪些结论可以被支持。

## 快速开始

对于 Codex，把 skill 文件夹复制到仓库级 skill 目录：

```text
.agents/skills/
  academic-audit-for-eclipse-sumo/
  debugging-audit-for-eclipse-sumo/
```

对于 Claude Code，把同样的文件夹复制到：

```text
.claude/skills/
  academic-audit-for-eclipse-sumo/
  debugging-audit-for-eclipse-sumo/
```

然后在 agent 中调用：

```text
Use $academic-audit-for-eclipse-sumo to audit this SUMO/TraCI traffic signal control experiment before I report results.
```

如果是在调试失败实验：

```text
Use $debugging-audit-for-eclipse-sumo to diagnose why this SUMO/TraCI run is invalid or unreproducible.
```

skill 应当先询问缺失的实验细节。SUMO 没有崩溃并不等于结果可以被认可。

## 项目状态

当前版本：仅包含指令型 skill 和检查清单。

本仓库目前包含 Markdown 形式的 agent skills、审计清单、示例和发布材料。它还不包含可执行的 SUMO validator 或 Python 审计脚本。

## 当前范围

当前版本聚焦于 SUMO/TraCI 交通信号控制实验。它还不是覆盖所有 Eclipse SUMO 用途的通用审计 skill。

这个版本覆盖 fixed-time、actuated、max-pressure、NEMA、data-informed 和 MPC-style 信号控制工作流。未来可以继续添加面向其他 SUMO 方向的审计 skill，例如 demand and routing、emissions and energy、public transport、pedestrian and intermodal scenarios、AV/CAV and co-simulation workflows、calibration、safety analysis，以及 mesoscopic 或 microscopic simulation-mode comparisons。

## Skill 列表

| Skill | 用途 | 主要输出 |
|---|---|---|
| `academic-audit-for-eclipse-sumo` | 规划、审阅、比较或撰写 SUMO/TraCI 信号控制实验结论。 | Experiment Readiness Record、hard-gate audit、evidence class、claim boundary。 |
| `debugging-audit-for-eclipse-sumo` | 调试 route、TraCI、TLS、demand、detector、output、seed、completion 和 reproducibility 问题。 | Fault class、next diagnostic probe、evidence、fix or demotion rule。 |

两个 skill 都是普通的 `SKILL.md` 包，包含 YAML frontmatter 和 Markdown references。`agents/openai.yaml` 提供可选的 Codex UI metadata；核心指令仍然可以被读取 `SKILL.md` 的 Claude-style skill loader 使用。

## 它审计什么

- TLS 相位与 movement-green 一致性。
- route、config、additional file、detector 和 network 一致性。
- fixed-time、actuated、max-pressure、NEMA、data-informed 和 MPC-style 控制器比较。
- 配对 seeds、配对 demand、配对 output interval 和配对 simulation horizon。
- `tripinfo`、`summary`、`edgeData`、TLS switch output、controller logs、warnings、teleports 和 unfinished vehicles。
- 当仿真在车辆全部离网前停止时，使用 completion-aware metric reporting。
- Baseline、ablation、sensitivity runs 和 claim wording。

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

设计遵循四个原则：

**Progressive disclosure。** `SKILL.md` 保持紧凑，只在需要时把 agent 引导到聚焦的 reference files。

**执行前的 Socratic intake。** 对于信息不足的实验，skill 会先针对 network、demand、controller、outputs、baselines、seeds 和 metrics 提问，并建立 Experiment Readiness Record。

**结论前的 hard gates。** 审计会分开检查 SUMO 实际加载了什么、controller 实际做了什么、写出了哪些 outputs、出现了哪些 warnings，以及证据能支持什么 claim。

**闭环调试。** debugging skill 使用 observe -> classify -> probe -> compare -> update，让修复基于 artifacts，而不是试错式修改参数。

## 限制

本仓库提供 agent 指令、检查清单和审计流程。它不能认证一个 SUMO 实验是正确的。

这些 skill 不能替代人工审查、SUMO 官方文档、controller-specific validation 或独立复现。它们的目标是减少常见工作流错误，并把 claim boundaries 显式化。

审计输出应被视为 review support，而不是 formal verification result。

## 设计来源

本仓库借鉴了更广泛的 agent-skill 生态中的模式：

- Agent Skills convention：使用包含必需 `SKILL.md`、YAML frontmatter 和可选 resources 的自包含文件夹。
- 公开 skill 仓库，例如 `anthropics/skills`：仓库级 README、skill catalog、examples 和明确免责声明。
- `skill-creator` 和 `writing-skills` 中的 skill authoring 模式：精简 frontmatter、紧凑 `SKILL.md`、单层 references 和发布前验证。
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
  academic-audit-for-eclipse-sumo/
  debugging-audit-for-eclipse-sumo/
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
