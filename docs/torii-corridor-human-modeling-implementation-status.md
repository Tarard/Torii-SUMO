# Torii-SUMO 走廊级人类建模闭环实施状态

更新时间：2026-07-14

本文件只记录可复现的实施证据，不改变
`torii-corridor-human-modeling-research-plan.md` 的验收门。

## 阶段状态

| 阶段 | 状态 | 当前证据或阻断项 |
|---|---|---|
| 0. 规范冻结 | 完成 | schema、稳定语义 ID、工具链、manifest、source/candidate 身份和 CI 已冻结。 |
| 1. Audit-only | 进行中 | 合成单故障、复合故障、SUMO 官方场景和 OOD 适用域测试已建立；真实 held-out 机器语料已预注册，但两名独立人工审核和第三方裁决尚未发生。 |
| 2. 认证 micro-repair | 未完成 | 不得以现有候选契约或旧局部修复代替逐编辑类型的 held-out 认证。 |
| 3. Physical-cell hypotheses | 未完成 | split/shared-controller、merge、partial 三假设尚未完成统一 held-out 比较。 |
| 4. Local geometry solver / MGE-1 | 未完成 | 当前 arclength blend 仍仅是消融基线；boundary-port solver 尚未达到预注册退出条件。 |
| 5A/5B. NEMA 与行人安全 | 未完成 | vehicle-only 严格扫描存在，但行人、自行车、共享 controller 和实际 timing 均未认证。 |
| 6. 多城市走廊 | 进行中 | 30 个走廊、6 个城市及左右侧通行快照已全部物化并通过身份/引用闭包；目前只完成 1 个走廊的完整机器审核，尚无人审。 |
| 7. 城市级运行 | 未开始 | 阶段 6 未退出前不得启动自动语义扩张。 |

## 已冻结的真实 held-out 语料

- 30 个走廊，Berlin、Amsterdam、Paris、London、Melbourne、Sydney 各 5 个。
- 左右侧通行分开；目标覆盖 pedestrian、bicycle、ramp、rail、bridge、tunnel。
- 城市源使用 BBBike 发布的 OSM PBF；provider MD5、HTTP identity、下载字节数和本地 SHA-256 均进入 manifest。
- 裁剪使用 reference-complete writer，并保留被引用交通信号灯和 crossing 节点标签。
- feature targets 是预注册待验证目标，不是事后真值；冻结快照不支持时必须报告 review/replacement。
- OSM 派生物明确记录 `© OpenStreetMap contributors` 和 ODbL。

全量快照物化证据：

- 6/6 城市源均通过 provider MD5、下载字节数和本地 SHA-256 身份检查。
- 30/30 走廊均 reference-complete，0 个预注册 feature target 未确认。
- snapshot manifest 共绑定 40 个 artifact，逐项复核哈希失败为 0。
- 该 pass 只认证输入身份和裁剪闭包，不认证 SUMO 建模质量。

## Sydney 试跑证据

OSM 快照：

- 绑定城市 PBF SHA-256：`337d2d24e17ceed8049c1fa3e3fd7fab7b9e99911f43c87463b6133f5d39457d`。
- 5/5 走廊均为引用闭合，且各自预注册 feature targets 均在冻结 OSM 中得到标签证据。
- 全语料门仍为 blocked，因为其余 25 个走廊尚未物化。

Sydney Harbour Bridge 首个机器闭环：

- `netconvert`：pass。
- SUMO 1.27.1 load：pass。
- 20 车 routeability：pass，零未完成、碰撞和 teleport。
- Connection Mode：715 个 junction 中 703 pass、12 review-required、0 structural fail，共 29 个 review finding。
- 独立冲突审核：blocked。当前模型尚未覆盖 9 个受控 pedestrian walkingarea→crossing link，并产生其他多模式/潜在冲突审核项。
- 独立冲突 broad-phase 已从全量 2,487,565 个 movement pair 保守缩减到
  7,728 个精确几何判断（0.31%）；3,723 条 conflict 与保存的 exhaustive
  结果逐字段完全一致。该开发机上的单图计算由两分钟级降至约 0.64 秒；
  时间仅作诊断，不作为验收阈值。
- certification applicability：out-of-domain。
- 三档机器分类：ambiguous（安全覆盖不足不是已确认 defect）。
- 自动晋级：blocked。
- 人工标签：不存在；不得把机器结果描述为人工确认 defect 或 acceptable。
- reviewer-visible 包已物化：盲化 HTML、候选 `.net.xml`、可直接加载的
  `.sumocfg` 和只含 POI 的 display-only `additional.xml`；真实 candidate ID、
  review case ID 和机器标签均未泄漏到 HTML。
- 盲化候选与数据集声明的 SHA-256 一致，package manifest 的 7 个 artifact
  哈希全部闭合；盲化 `.sumocfg` 已由 SUMO 1.27.1 实际加载通过。
- 真实 held-out runner 现在强制执行同输入双重 netconvert replay；本次
  primary/replay 原始哈希因生成时间注释不同，但去除注释并规范化 XML 后
  SHA-256 均为
  `dd0ae52b3059f63a27b8210a000c0cbc139311ff28d4e8ccfd3a989dc8a45a29`。
  不一致时会在生成人工审核候选前阻断。

## 真实样本发现并修复的架构缺陷

首轮 Sydney 构建被 canonicalizer 阻断：审核输入声明 left-hand traffic，
但 OSM→SUMO builder 未把通行侧传给 `netconvert`，实际仍生成 right-hand 网络。

修复后：

- 通行侧成为显式构建输入；
- left-hand 输入使用 `netconvert --lefthand`；
- 构建报告和 command record 记录 traffic side；
- 左右侧矛盾继续 fail closed；
- 同一冻结 Harbour Bridge 样本可进入后续审核。

真实语料还暴露了两处重复全网扫描：

- Connection Mode 曾为每条 movement 重算全网 internal-lane 数量；改为 catalog
  单次预计算后，Berlin Alexanderplatz 的 2,527 个 junction、9,843 条
  movement 核心报告逐字段不变，开发机核心审核约 1.39 秒。
- canonicalizer 已有 outgoing connection 索引，却在每条 movement 内重新构建；
  改为复用索引和单次 hop bound 后，Harbour Bridge 的 16,233 个 canonical
  entity 逐字段不变，开发机约 4.12 秒。
- 以上时间只用于确认可运行性，不是质量验收指标；等价回归和冻结 schema
  仍是硬门。

## 最近的硬阻断项

1. 其余 29 个走廊的 netconvert replay、Connection Mode、独立安全、routeability 和盲化机器证据尚未全部完成。
2. 需要两名真实独立审核者逐案作答；分歧由第三名 adjudicator 裁决。机器不得代填。
3. Stage 1 的 raw agreement、Cohen's kappa、attention precision/recall、AutoPrecision 和 review time 尚无真实数值。
4. pedestrian-aware independent conflict model 尚未完成，因此多模式 TLS 不可自动认证。

只有以上项目关闭并满足预注册阈值后，Stage 1 才能退出。
