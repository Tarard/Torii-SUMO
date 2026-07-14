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
| 6. 多城市走廊 | 进行中 | 30 个走廊、6 个城市、左右侧通行和 8 类形态已预注册；目前只完成 Sydney OSM 快照试跑。 |
| 7. 城市级运行 | 未开始 | 阶段 6 未退出前不得启动自动语义扩张。 |

## 已冻结的真实 held-out 语料

- 30 个走廊，Berlin、Amsterdam、Paris、London、Melbourne、Sydney 各 5 个。
- 左右侧通行分开；目标覆盖 pedestrian、bicycle、ramp、rail、bridge、tunnel。
- 城市源使用 BBBike 发布的 OSM PBF；provider MD5、HTTP identity、下载字节数和本地 SHA-256 均进入 manifest。
- 裁剪使用 reference-complete writer，并保留被引用交通信号灯和 crossing 节点标签。
- feature targets 是预注册待验证目标，不是事后真值；冻结快照不支持时必须报告 review/replacement。
- OSM 派生物明确记录 `© OpenStreetMap contributors` 和 ODbL。

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
- certification applicability：out-of-domain。
- 三档机器分类：ambiguous（安全覆盖不足不是已确认 defect）。
- 自动晋级：blocked。
- 人工标签：不存在；不得把机器结果描述为人工确认 defect 或 acceptable。
- reviewer-visible 包已物化：盲化 HTML、候选 `.net.xml`、可直接加载的
  `.sumocfg` 和只含 POI 的 display-only `additional.xml`；真实 candidate ID、
  review case ID 和机器标签均未泄漏到 HTML。
- 盲化候选与数据集声明的 SHA-256 一致，package manifest 的 7 个 artifact
  哈希全部闭合；盲化 `.sumocfg` 已由 SUMO 1.27.1 实际加载通过。
- 两次相同输入生成的原始 `.net.xml` 只因 netconvert 注释中的生成时间而
  字节哈希不同；去除注释并规范化 XML 后，两者 SHA-256 均为
  `dd0ae52b3059f63a27b8210a000c0cbc139311ff28d4e8ccfd3a989dc8a45a29`。

## 真实样本发现并修复的架构缺陷

首轮 Sydney 构建被 canonicalizer 阻断：审核输入声明 left-hand traffic，
但 OSM→SUMO builder 未把通行侧传给 `netconvert`，实际仍生成 right-hand 网络。

修复后：

- 通行侧成为显式构建输入；
- left-hand 输入使用 `netconvert --lefthand`；
- 构建报告和 command record 记录 traffic side；
- 左右侧矛盾继续 fail closed；
- 同一冻结 Harbour Bridge 样本可进入后续审核。

## 最近的硬阻断项

1. 其余 5 个城市的 hash-pinned 快照和 29 个机器走廊证据尚未全部完成。
2. normalized replay identity 尚未进入真实 held-out runner 的强制 gate；当前只完成了人工复核，两次语义哈希一致。
3. 需要两名真实独立审核者逐案作答；分歧由第三名 adjudicator 裁决。机器不得代填。
4. Stage 1 的 raw agreement、Cohen's kappa、attention precision/recall、AutoPrecision 和 review time 尚无真实数值。
5. pedestrian-aware independent conflict model 尚未完成，因此多模式 TLS 不可自动认证。

只有以上项目关闭并满足预注册阈值后，Stage 1 才能退出。
