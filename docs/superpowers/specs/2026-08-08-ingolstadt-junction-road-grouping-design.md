# Ingolstadt 路口与道路分组设计

## 目标

先对同一 Ingolstadt 范围内的全部适用路口和相关道路建立可复现分组。再从每组选择代表路口，真实运行当前 Torii 教学、重建和验证流程。按照覆盖量和失败根因修复共用流程。最后把通过的规则组合回全城候选，并恢复逐分区视觉门、结构门、SUMO 载入和全局可达性检查。

分组是全城目标的第一阶段，不缩小最终完成条件。8070 个空间分区只负责调度、恢复和视觉视窗。分区不是道路或路口类型。

## 已有能力

仓库已经有单路口、只读、证据绑定的组合分类器：

- `plugins/torii-sumo/src/torii_sumo/intersection/archetype_profile.py`
- `plugins/torii-sumo/src/torii_sumo/intersection/road_detail.py`
- `plugins/torii-sumo/src/torii_sumo/tools/intersection_tools.py`
- `plugins/torii-sumo/src/torii_sumo/intersection/candidate_dag.py`

现有分类器已经保存以下独立维度：支路数、角度形态、交互关系、单体或组合结构、环形结构、车行道组织、道路功能、车道组织、渠化、通行方式、管控方式、内部连接和移动关系。常见的 T3、Y3、X4 和环岛只是派生名称，不是唯一分类依据。

全城分组必须复用这些维度和 `classification_id`。不得再写一套只按 SUMO 节点度数分类的平行实现。

## 参考依据

分组采用多维描述，不采用单一外形标签。依据如下：

- FHWA 将支路数、管控方式、车道数和道路是否分隔分别记录。见 [Complete Streets Safety Analysis](https://highways.fhwa.dot.gov/sites/fhwa.dot.gov/files/FHWA-HRT-24-074.pdf)。
- 路口形态研究常使用 T、Y、十字、X、错位、环岛、匝道和不规则形态。见 [Wei et al. (2021)](https://doi.org/10.1109/ITSC48978.2021.9564518) 和 [Zhou and Li (2015)](https://doi.org/10.1111/tgis.12077)。
- ASAM OpenDRIVE 按交叉、汇入驶出、连续主路支路和仅交叉等车辆关系区分路口。它也单独标记复杂路口、互通和环岛。见 [ASAM OpenDRIVE 1.9](https://publications.pages.asam.net/standards/ASAM_OpenDRIVE/ASAM_OpenDRIVE_Specification/v1.9.0/specification/12_junctions/12_01_introduction.html)。
- SUMO 使用 `priority`、`right_before_left`、`traffic_light`、`zipper`、`rail_crossing` 等节点类型。见 [SUMO PlainXML](https://sumo.dlr.de/docs/Networks/PlainXML.html)。
- OSM 的 `highway=*` 表示道路功能和路网重要性，不直接表示几何质量。见 [OSM highway](https://wiki.openstreetmap.org/wiki/Key%3Ahighway)。
- 德国 RIN 将道路类别组与连接功能等级组合。见 [FGSV RIN](https://www.fgsv-verlag.de/pub/media/pdf/121_E.v.pdf)。
- 路网分类前必须区分真实路口与道路形状点。见 [Boeing (2017)](https://doi.org/10.1016/j.compenvurbsys.2017.05.004)。

这些资料提供稳定的道路和路口描述。Torii 的失败类型来自本项目的真实运行证据，不由文献替代。

## 当前全城基线

当前清单为：

`outputs/ingolstadt_citywide_native_visual_v59_target427_gate50m_probe/city-manifest.json`

教师网包含 8771 个适用路口。只读统计得到：

- 管控方式：5994 个 `priority`、2625 个 `right_before_left`、125 个 `traffic_light`、18 个 `zipper`、9 个 `unregulated`。
- 初步支路数：4568 个三支路、1255 个四支路、407 个五支路以上、1104 个两支路、1437 个单支路。
- 结构：7888 个单节点标识，883 个组合标识。
- 当前对应状态：6697 个 `ready`、1654 个 `blocked`、290 个教师独有、130 个对应不确定。

初步支路数只用于估算。正式值必须来自现有 physical-cell 和 semantic-arm 逻辑。道路形状点、短走廊和组合路口不能被重复计数。

## 分组模型

分组使用两个相互独立的轴。

### 轴一：真实道路与路口

直接复用现有 `archetype_profile` 和 `road_detail`：

- `grade_relation`
- `interaction_kind`
- `cell_structure`
- `arm_count_class`
- `derived_alias`
- `angular_form`
- `circulation_form`
- `carriageway_organization`
- `control_rule`
- `controller_topology`
- `movement_graph_status`
- `road_classes`
- `network_roles`
- `lane_organization`
- `channelization_types`
- `facility_modes`

每项保留来源、证据等级和 `unknown`。缺失证据不得用最近类别代替。

### 轴二：Torii 当前处理结果

第二轴记录当前候选相对教师网的状态：

- `ready`
- `registration_blocked`
- `teacher_only`
- `candidate_only`
- `ambiguous`
- `not_run`
- `pass`
- `fail`
- `review_required`

失败项再记录一个根因族：

- `registration`
- `physical_cell_or_split_merge`
- `approach_boundary_or_geometry`
- `lane_mapping_count_or_permission`
- `movement_connection_or_right_of_way`
- `crossing_walkingarea_or_mode`
- `tls_controller_or_link_index`
- `sumo_load_or_routeability`
- `netedit_visual_mismatch`
- `unknown`

失败根因必须来自运行报告。文件名、截图印象或教师路口类型不能单独确定根因。

## 分组键

完整分类保存在每个路口记录中。运行调度只使用较短的分组键：

```text
mapping-status
  / cell-structure
  / control-rule
  / arm-count-class
  / special-feature
```

`special-feature` 只取一个主标记：`roundabout`、`rail`、`link_or_ramp`、`multimodal` 或 `ordinary`。完整道路等级、车道组织和渠化仍保存在记录中，不进入首版分组键。这样可以防止类别组合爆炸。

如果同组代表路口出现两个不同根因，先按已经存在的完整维度拆组。只有现有维度无法解释差异时，才增加一个新字段。

## 代表路口

每组最多选择三个代表路口。选择必须确定且可重复：

1. 按证据完整度从高到低排序。
2. 再按车道和移动数量从低到高排序。
3. 取最小值、中位值和最大值。
4. 数量不足三个时，不补重复样本。

第一轮先处理覆盖量最大的组。信号灯、铁路、环岛、五支路以上和组合路口即使数量较少，也各保留至少一个代表项。

代表路口运行当前版本，不使用为该代表项预写的专用补丁。运行产物必须绑定教师网、候选网、OSM 和分类记录的哈希。

## 共用流程与少量规则

`junction_rebuild_candidate.py` 继续作为共用重建流程。首版不为每个分组创建文件。

只有满足以下条件时才增加规则：

1. 同组代表项重复出现同一根因。
2. 共用流程无法用一个上游修复覆盖该根因。
3. 规则有明确前置条件。
4. 规则运行后仍经过现有结构、视觉、SUMO 和可达性门。

规则先集中在一个小型分派文件中。每条规则只声明：适用条件、前置证据、一个受限动作和必须通过的后置门。只有该文件出现多个独立职责时才拆分。

路口标签只选择规则，不直接授权修改。所有自动接受条件保持严格。

## 数据流

1. 读取冻结的 OSM、教师网、候选网和全城清单。
2. 校验全部输入哈希。
3. 通过现有 physical-cell、topology、movement 和 archetype 流程分类教师路口。
4. 追加教师与候选对应状态。
5. 写入逐路口紧凑记录和分组汇总。
6. 为每组选择代表路口。
7. 对代表项运行当前 Torii。
8. 从报告中写入通过状态或根因族。
9. 按组覆盖量修复共用根因。
10. 重跑受影响组和相邻空间分区。
11. 规则稳定后恢复全城视觉门和全局检查。

空间分区 ID 保留在每条记录中，只用于恢复和定位。分类结果不得依赖分区边界。

## 产物

首版产物保持最少：

```text
outputs/.../ingolstadt-junction-groups/
  source-ledger.json
  classification.jsonl
  groups.json
  representative-queue.json
  state.json
  groups/<group-id>/representative-results.json
```

`classification.jsonl` 每行对应一个教师适用路口。候选独有项使用相同格式，但设置 `side=candidate_only`。JSONL 支持流式处理和断点恢复，不需要资料库。

`groups.json` 只存计数、分组键、成员 ID 和状态。通过截图不进入分组清单。失败截图继续由现有视觉门保存。

## 恢复与失效

每条分类记录绑定以下值：

- OSM SHA-256
- 教师网 SHA-256
- 候选网 SHA-256
- `classifier_version`
- `vocabulary_id`
- 分组规则版本

OSM 或分类器变化时，分类记录全部失效。候选网变化时，轴一可复用，轴二和代表项运行结果失效。单个规则变化时，只重跑匹配该规则的组及其相邻空间分区。

写入采用临时文件加原子替换。中断后从最后一个完整记录继续。

## 检查

### 分类检查

- 8771 个教师适用路口全部且仅出现一次。
- 教师独有、候选独有和对应不确定项不会被静默排除。
- 相同输入重复运行得到相同 `classification_id`、分组键和代表项。
- 完整分类计数与分组汇总计数一致。
- `unknown` 有明确原因。
- 分区边界变化不改变分类。

### 代表项检查

- 每个非空组有代表项。
- 代表项数量不超过三个。
- 当前 Torii 对每个代表项产生结构报告和 SUMO 载入报告。
- 需要视觉检查的项使用 NetEdit CLI Connection 模式。
- 失败根因来自报告，不来自人工命名。

### 规则检查

- 每条非平凡规则先有失败检查。
- 共用修复必须重跑所有已知受影响组。
- 单组通过不能支持全城通过结论。
- 最终仍执行逐路口视觉门、结构门、SUMO 全网载入和全局可达性检查。

## 分组阶段完成条件

分组阶段只有在以下条件全部满足时完成：

1. 教师和候选两侧的清单总数可以守恒核对。
2. 每个教师适用路口都有完整分类或带原因的 `unknown`。
3. 每个记录恰好属于一个调度组。
4. 每个非空组有确定的代表项。
5. 当前 Torii 已对全部代表项完成一次真实运行。
6. 每组都有 `pass`、明确根因或 `review_required` 状态。
7. 产物支持中断恢复，并绑定全部来源哈希。

完成分组阶段不等于完成全城路网。全城完成仍要求全部适用路口通过视觉、结构、SUMO 载入和全局可达性检查。

## 非目标

- 不按 8070 个空间分区生成规则。
- 不为每个标签组合创建代码文件。
- 不复制现有 archetype 分类器。
- 不加入资料库、任务服务或新的图像识别依赖。
- 不用分类标签跳过教师独有、候选独有或对应不确定项。
- 不把文献分类直接当作 SUMO 修改授权。

## 结论边界

分组结果属于 `diagnostic-demo` 证据。它可以证明覆盖分母、类型分布和当前 Torii 的组级表现。只有最终全城门全部通过后，才能声称 Ingolstadt 全城候选达到要求。
