# Torii-SUMO 走廊级人类建模闭环实施状态

更新时间：2026-07-14

本文件只记录可复现的实施证据，不改变
`torii-corridor-human-modeling-research-plan.md` 的验收门。

## 阶段状态

| 阶段 | 状态 | 当前证据或阻断项 |
|---|---|---|
| 0. 规范冻结 | 完成 | schema、稳定语义 ID、工具链、manifest、source/candidate 身份和 CI 已冻结。 |
| 1. Audit-only | 进行中 | 合成单故障、复合故障、SUMO 官方场景和 OOD 适用域测试已建立；30/30 真实 held-out 走廊已完成首次机器尝试，27 个形成完整审核包、3 个因 netconvert 重放不确定性 fail-closed；两名独立人工审核和第三方裁决尚未发生。 |
| 2. 认证 micro-repair | 未完成 | 不得以现有候选契约或旧局部修复代替逐编辑类型的 held-out 认证。 |
| 3. Physical-cell hypotheses | 未完成 | split/shared-controller、merge、partial 三假设尚未完成统一 held-out 比较。 |
| 4. Local geometry solver / MGE-1 | 未完成 | 当前 arclength blend 仍仅是消融基线；boundary-port solver 尚未达到预注册退出条件。 |
| 5A/5B. NEMA 与行人安全 | 未完成 | vehicle-only 严格扫描存在，但行人、自行车、共享 controller 和实际 timing 均未认证。 |
| 6. 多城市走廊 | 进行中 | 30 个走廊、6 个城市及左右侧通行快照已全部物化并通过身份/引用闭包；首次全语料机器运行已结束并保持 blocked，修正后的 Connection Mode 尚待全量重跑，且尚无人审。 |
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

## 首次 30 走廊机器运行

在 commit `8ca462b` 上启动的首次全量运行已经结束：

- 30/30 走廊均被尝试；所有冻结 OSM 源哈希保持不变。
- 27 个走廊完成 netconvert、机器审核流水线并生成绑定哈希的 review case；
  3 个走廊在 netconvert 双重重放门被阻断。
- 机器标签为 0 acceptable、2 ambiguous、28 defect；这些不是人工标签。
- 22 个 SUMO load pass、5 fail、3 not-run；14 个 routeability pass、
  13 fail、3 not-run。
- 13 个 Connection Mode 为 review-required、14 fail、3 not-run；
  independent safety 在 30 个走廊上均未完成认证。
- 顶层 manifest 绑定 497 个 artifact，缺失 0、SHA-256 复核失败 0。
- 27 个盲化审核 case 已生成；真实人工 review decision 和 adjudication 仍均为 0。
- 最终 automatic promotion gate 与 evidence build status 均为 blocked。

3 个 replay failure 不是时间戳或 XML 排版误报：

- London Kings Cross 的同一 junction 在两次构建中分别成为
  `right_before_left` 和 `priority`，request/foes、internal lane 和 connection
  均发生变化。
- Melbourne Royal Parade 与 Sydney Cross City Tunnel 的 edge、junction、TLS
  和 connection multiset 相同，但 `<roundabout>` 分组不同。SUMO 官方文档说明
  roundabout 记录会参与重新导入并可能影响 lane-changing，不能把分组差异忽略为格式。
- 对 London 显式添加 `--seed 42` 后双重重放仍不一致；随机种子必须进入工具链
  身份，但仅锁 seed 不能解决该不确定性。

进一步检查 SUMO 1.27.1 源码（tag `v1_27_1`，commit
`7717f2379d9e314a0c81c5cec748444de06a2a91`）后，已定位到
`NBEdgeCont::extractRoundabouts()`：它以 `std::set<NBEdge*>` 的指针顺序选择
起始边，并在多条候选 outgoing edge 中取第一个匹配项。不同进程因而可能把
同一组 OSM `junction=roundabout` 边切成不同 `EdgeSet`。后续
`markRoundabouts()` 又按该分组设置优先权和删除外部回转连接，所以这是真实语义
不确定性，不是序列化噪声。

现已建立隔离的 PlainXML 确定性输入实验：

- 第一段锁定 `seed=42`、`--no-turnarounds`、`--roundabouts.guess false`、
  `--plain-output.lanes` 和通行侧；
- source PlainXML 从不原地修改，blocked 时删除陈旧 candidate；
- OSM 标记边只有在形成单一有向闭环，或按完整 edge/lane permission contract
  能唯一分解成若干有向闭环时，才生成规范化 bundle；
- open component、特殊节点、未知环岛记录或权限分解不完整均 fail closed；
- 回转连接只记录、不删除，其合法性留给后续 Connection Mode 和证据审核。

三例结果：

- London 两次均因 Percy Circus 的 6-edge/7-node 断裂环岛和 dead-end 节点阻断；
- Sydney 两次均因一个 1-edge/2-node 环岛断片阻断；
- Melbourne 的 7 个物理组件可确定分解为 8 个循环，两次规范化 PlainXML bundle
  SHA-256 均为
  `01e36eaed20927d696287ce4f11345074a28790b256789eb8c27be79e5f2b406`，
  两次重建网络的规范化语义 SHA-256 均为
  `ceb8d397c23b936f553f3b04885654f04405633e47c053a0378615aaae44adba`，
  且 SUMO load pass。

该实验没有进入现有 v1 晋级路径。Melbourne 的确定性两段式网络相对旧的一步式
网络仍产生 141,141 个稳定实体 delta，说明全网 PlainXML 重建只能作为新的、版本化
初始 source 协议评估，不能作为局部 candidate repair，也不能替换冻结 v1 source。
完整机器证据保存在
`benchmarks/corridor_human_modeling_v1/evidence/netconvert_plainxml_determinism_probe_20260714.v1.json`。

首次运行报告 SHA-256 为
`565c9e11b22d6d0dc3e3dd0ff950fb7c292341c3911f6bb626042d7d43b68b3c`，
manifest SHA-256 为
`7dd11c45dd45090a0fe58e1fa9d4af3b9467fd5fb3320729a87f6da01e8cd794`。

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

Berlin Alexanderplatz 还暴露了一个审核口径错误：79 个旧
`path_endpoint_gap` 全部来自 1.0 m bicycle internal lane 与较宽混合 lane
之间的宽度过渡，原始中心线偏移最大 3.706009 m，但按相邻 lane tangent
扣除半宽差后的有效 gap 最大仅 0.11767 m。现已：

- 同时保存 raw gap、width-transition offset 和 effective gap；
- 只对横向宽度过渡扣除半宽差，等宽或纵向断裂继续 hard fail；
- 将超过显示阈值但道路带仍连续的情况变成精确 review finding；
- 从校准样本中排除 walkingarea→crossing 的 display-only 最近端点距离。

修正后 Berlin 校准使用 8,919 条 path、18,746 个端点样本，q99.5 为
0.018742 m、最大 0.11767 m、推荐容差 0.038742 m，校准状态为 pass。
使用该严格容差仍有 31 个 non-motorized-or-mixed outlier 被 hard fail；因此
不能据此宣称 Berlin 已正确，也尚未把修正后的审核器结果外推到全语料。

## 最近的硬阻断项

1. 修正后的 Connection Mode 尚未对 30 个走廊全量重跑；实验性 v2 确定性输入协议只在 Melbourne 通过，London/Sydney 因 OSM 环岛证据不闭合而正确阻断，且该协议不得改写冻结 v1 结果。
2. 需要两名真实独立审核者逐案作答；分歧由第三名 adjudicator 裁决。机器不得代填。
3. Stage 1 的 raw agreement、Cohen's kappa、attention precision/recall、AutoPrecision 和 review time 尚无真实数值。
4. pedestrian-aware independent conflict model 尚未完成，因此多模式 TLS 不可自动认证。

只有以上项目关闭并满足预注册阈值后，Stage 1 才能退出。
