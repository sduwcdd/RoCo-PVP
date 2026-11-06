# 魔镜补丁 2：直接字段证据接入候选图

2026-10-25。本次仅读取既有提取物，未执行 Lua、未修改游戏。基础包及补丁 3 的旧产物未被覆盖。

## 已确认的配置与字节

- 补丁 2 技能 `SKILL_CONF[7170280]`“魔镜”的原始 `skill_result[0]` 引用 `BUFF_CONF[20010080]`，后者引用 `BUFFBASE_CONF[2001008]`。
- 第一槽 `buff_group_level` 由 schema 声明为 `EUint32`。`SKILL_CONF.bytes` 的文件内偏移 **333410**，长度 4，原始字节 **05000000**，解码值 **5**。此值直接来自字节，未由描述比例推算。
- 第一槽另保留 `result_target_type=2`、`cast_moment=11`、`success_rate=10000`。`buff_level_rule` 在 schema 中声明、在该记录中缺失，保持 `absent_in_record`。
- 第二槽为 `EFFECT_CONF[1019013]`，`buff_group_level=1`，对应偏移 338169、原始字节 `01000000`；效果参数首项为 `[-3]`。此槽保持 `result_reference`，不是状态引用，也不生成基础状态链。
- 状态原值保留 `add_max=99`、`buff_base_ids=[2001008]`、描述“魔防-10%”；基础状态原参数为 `[[36],[0],[1000]]`。不据此推导完整属性结算公式。

## 每份资源的来源

`game-mirror-patch2-20261025.resources.json` 是显式选择清单；`game-mirror-patch2-20261025.json` 保存完整逐资源 archive、资源路径、payload SHA-256、提取 manifest SHA-256、schema 选择依据与图中原始字段。构建器只接受清单中精确匹配的资源，不自动寻找先前或更新版本。

| 表 | schema | binary data | localization |
|---|---|---|---|
| SKILL_CONF | 补丁 2 | 补丁 2 | 补丁 2 |
| BUFF_CONF | 补丁 0，显式先前 schema 候选 | 补丁 2 | 未选择 |
| BUFFBASE_CONF | 补丁 0，显式先前 schema 候选 | 补丁 2 | 未选择 |
| EFFECT_CONF | 补丁 2 | 补丁 2 | 未选择 |

技能表的 schema、data 与 localization 同包；状态和基础状态的 schema 与 data **不同包**。后两者是既有 `status_chain_manifest.json` 指定的有限跨包解析候选，不构成当前游戏实际挂载顺序的证明。全部选择资源重新检查 payload 和 manifest 哈希，全部解析记录重新检查长度。

## 独立新产物与验证

候选图：`artifacts/game_layer_references_mirror_patch2_20261025/layer_references.json`

SHA-256：`b70b11bc24423fa7f8e8e795614366ac08dccb6fe684f7460bf5e0816b5195aa`

补丁 2 来源 ID：`resource-group-c40d72d37c3c43a12b3f`。新图同时保留基础包 `archive-a45a57add3edf933f964` 与补丁 3 `archive-7eaa655a5d7950b7d58a` 的独立候选；补丁 2 共 1894 条技能、6239 个效果槽、2513 个显式层数操作数，其中 1759 个解析为状态引用。效果槽层数计数包含 EFFECT，不可等同于状态应用数。

构建命令：

```powershell
python scripts/build_game_layer_references.py --manifest artifacts/strength_buff_probe_20261025/historical_table_manifest.json --manifest artifacts/layer_reference_probe_20261025/manifest.json --resource-group docs/verification/game-mirror-patch2-20261025.resources.json --output artifacts/game_layer_references_mirror_patch2_20261025/layer_references.json
```

验证命令：`python -m unittest tests.test_game_layer_references -v`。原 12 项回归与新增 6 项补丁 2 来源测试均通过，共 18 项。验证覆盖直接字节、两个原始槽、BUFF/EFFECT 区别、逐资源 archive/哈希、严格同包 API 继续拒绝混包、显式选择无法自动回退、来源伪造在重解析时被拒绝。临时测试文件由临时目录清理。

## 结论边界

已确认：保留的补丁 2 配置为魔镜第一状态槽显式写入 `buff_group_level=5`，且该字段的原字节和来源均可复核。

待核实：当前线上实际加载资源版本、此配置是否仍适用、该字段的完整运行时解释与属性结算公式。原图继续保持 `effective_stack_count=null`、`per_stack_formula=null`、`runtime_executable=false`、`training_eligible=false`，未把历史值写入基础包或补丁 3 缺失字段。

疑似编造：无。可信度：已确认的配置与字节证据 10/10；运行时与线上适用性未确认。
