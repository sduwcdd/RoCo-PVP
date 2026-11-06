# 层数引用链与版本隔离

2026-10-25。在现有候选架构中新增 `lab/game_layer_references.py`，批量建立每个来源内的 **SKILL_CONF.skill_result → BUFF_CONF → BUFFBASE_CONF** 引用链，并区分引用 EFFECT_CONF 的结果项。未修改已发布规则、BWIKI 或游戏文件。

后续已检查中间补丁2，魔镜7170280明确写入层数5，详见[补丁2来源报告](verification/game-mirror-patch2-20261025.md)。下面基础包/补丁3对照仍保留，但魔镜的五层已不再仅依赖用户说明。新增资源组显式记录补丁0的状态schema与补丁2数据，未把这组资源伪称同包，也未证明线上加载顺序。

## 力量增效与魔法增效

| 技能 | 基础包直接配置 | 状态链 | 补丁3 |
|---|---|---|---|
| 力量增效 7020620 | buff_group_level=10 | 20010010 → 2001001 | skill_result 结构不含层数字段 |
| 魔法增效 7020630 | buff_group_level=7 | 20010020 → 2001002 | skill_result 结构不含层数字段 |
| 魔镜 7170280 | 基础包无此技能记录；补丁2明确5层 | 补丁3：20010080 → 2001008，另引用效果1019013 | 不含层数字段；不自动继承补丁2数值 |
| 魔法增效 7880001 | 基础包无此技能记录 | 补丁3：20010020 → 2001002 | 不含层数字段，不能从同名技能复制七层 |

力量增效的层数字节在提取后的 SKILL_CONF.bytes 偏移253703，为 `0a000000`，按该基础包 schema 中 EUint32 解出10。魔法增效7020630的层数字节为 `07000000`，直接解出7；不再只是由70%/10%推断。各结果项的字段偏移、原始字节、类型和值均由重新解析过程采集，而非搜索碰巧相同的字节。力量增效的原记录106字节及引用结构21字节均通过消耗长度核验。

**这确认的是基础包配置，不是当前线上生效层数或精确属性公式。** 基础包的 buff_level_rule 在这两条记录中未序列化，未默认补零。该字段在其他记录出现时也原样保留，不擅自给编号命名。

## 通用引用组件

组件保留原技能ID、原结果槽位、effect_id、buff_group_level、buff_level_rule、result_target_type、success_rate、cast_moment，连同对应 schema、记录哈希、二进制字段位置和提取来源。每个节点ID含来源标识；两版本相同数字ID不会互相覆盖。

每个字段明确区分：

1. `not_in_schema`：该版本结构没有声明字段；
2. `absent_in_record`：结构声明了字段，但该记录没有序列化值；
3. `explicit`：有原始值，包含显式0。

`effective_stack_count` 和 `per_stack_formula` 暂为空。原始层数参数与最终生效层数分开；目标、成功率、触发编号、层数规则均不凭名称推定执行语义。状态节点保留 add_max、基础状态参数、衰减与清除字段，供后续组件绑定使用，不将 add_max 误当单次施加层数。

原结果数组全部保留，包含重复引用、空对象、缺ID和显式0。138个基础包结果项虽包含层数字段，却引用 EFFECT；不能统一转换成“添加BUFF”。两个含层数但缺effect_id的槽位保持未解析，未补成ID=0。

## 批量结果

| 范围 | 基础包 | 补丁3同包数据 |
|---|---:|---:|
| SKILL_CONF记录 | 1378 | 1988 |
| 结果槽位 | 2675 | 6485 |
| 显式层数参数 | 1257，涉及909条SKILL_CONF记录 | 0（schema未声明） |
| 显式层数且引用状态 | 1117 | 0 |
| 结构声明层数、记录缺值 | 1418 | 不适用 |

这些数量包含特性、其他玩法与测试记录，不代表可用PVP技能数量或还原率。引用链结构化不等于组件可以执行；本轮新增运行规则、完整对战及实战校准数量均为0。

补充提取基础包与补丁3各自的 EFFECT/BUFFBASE，共8个payload；原始范围哈希及前后文件属性未变，配套schema重新解析全部行。基础包四表记录数为1378/1925/1879/956，补丁3为1988/3309/2810/1257（顺序SKILL/BUFF/BUFFBASE/EFFECT）。

先前候选按路径分别选择较高补丁，不是单一包版本快照。例如旧EFFECT使用补丁3 schema和补丁26数据，共1259行；本次同包补丁3为1257行。原候选保持原样，本次禁止混用这些表来证明同包历史引用关系。

## 复现与校验

```powershell
python scripts/build_game_layer_references.py --manifest artifacts/strength_buff_probe_20261025/historical_table_manifest.json --manifest artifacts/layer_reference_probe_20261025/manifest.json --output artifacts/layer_reference_probe_20261025/layer-reference-candidates-1.json
python -m unittest tests.test_game_layer_references -q
```

输出已有但内容不同时拒绝覆盖，应使用新修订路径。保存前强制重新校验manifest/payload哈希，并按各包schema重解析；派生引用、字段证据或来源被改写都会拒绝保存。`validate_layer_references()` 默认检查结构，`verify_sources=True` 另执行原文件复核，保存入口始终启用后者。

测试覆盖力量10层的精确字节、魔法7层、版本隔离、缺失与0、重复和空槽、层数规则不默认、状态隔离、确定性、错误引用、布尔/数值篡改、伪造字节位置及输出不覆盖。未接入自动训练，也未将历史字段写回当前配置。

证据：[独立文件审计](verification/game-layer-evidence-20261025.md)、[代码审查](verification/game-layer-review-20261025.md)、[运行验证清单](verification/game-layer-references-20261025.json)。
