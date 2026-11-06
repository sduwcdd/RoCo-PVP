# 游戏层数引用关系：独立只读复核（2026-10-25）

## 已确认的配置证据

力量增效 `7020620` 在基础包 `SKILL_CONF` 中明确写入 `buff_group_level=10`，并引用 `BUFF_CONF[20010010] → BUFFBASE_CONF[2001001]`。本次重新解析原始提取数据并记录每个标量的字节位置，与旧 `strength_binary_evidence.json` 一致。

| 核验项 | 独立复核值 |
|---|---|
| 数据文件内记录偏移 | 46792 |
| 记录声明/实际消耗长度 | 106/106 |
| skill_result 常量结构偏移/长度 | 253686/21 |
| presence mask | `f4` |
| buff_group_level 绝对字节偏移 | 253703 |
| 原始小端字节/类型/值 | `0a000000` / `EUint32` / 10 |
| buff_level_rule | schema声明，但本记录未序列化；不得自动解释成0 |

这里的偏移是提取后的 `SKILL_CONF.bytes` 文件内偏移，不是 PAK 压缩文件的物理偏移。schema 中 `Offset=20` 是结构字段布局描述，不可直接替代压缩数据中的实测偏移。

## 基础包全量扫描

| 统计口径 | 数量 |
|---|---|
| SKILL_CONF 技能 | 1378 |
| skill_result 槽位（含缺引用的槽位） | 2675 |
| 显式含 buff_group_level 或 buff_level_rule 的槽位 / 技能 | 1257 / 909 |
| 层数字段槽位引用同版 BUFF_CONF | 1117 |
| 层数字段槽位引用同版 EFFECT_CONF | 138 |
| 层数字段槽位缺 effect_id | 2 |
| 全部槽位引用同版 BUFF / EFFECT / 缺 effect_id | 1118 / 780 / 777 |

两条缺引用的层数字段槽位：`200030`“再生”第2槽、`7300004`“测试buff4”第1槽；均只有字段缺失，不能生成一个数值为0的虚构引用。没有发现“已给出数值ID但两张同版表都找不到”的引用。

基础包 `buff_group_level` 显式出现1257次，缺失1418次；其中1057项为1，27项为10。`buff_level_rule` 只显式出现1次：`299905`“赋予效果用技能”引用 `20010010`，`buff_level_rule=1`、`buff_group_level=40`。现有表格证据不能给 rule=1 自行命名语义。138个指向 EFFECT 的显式字段条目也说明：不能仅凭字段存在就把所有结果统一当成可叠加 BUFF。完整分布和逐项引用在同名 JSON。

## 指定技能链与版本边界

| 技能 | 基础包 | 补丁3同版表 |
|---|---|
| 力量增效7020620 | BUFF20010010 → BASE2001001；显式10层 | 相同BUFF/BASE引用；层数schema字段不存在 |
| 魔法增效7020630 | BUFF20010020 → BASE2001002；显式7层 | 相同BUFF/BASE引用；层数schema字段不存在 |
| 魔镜7170280 | 无此技能记录 | BUFF20010080 → BASE2001008；另引用EFFECT1019013，参数首项[-3] |
| 魔法增效7880001 | 无此技能记录 | BUFF20010020 → BASE2001002；cast_moment=23（7020630为11） |

魔镜的技能文本写“魔防-50%、失去3能量”，BUFF文本写“-10%”；补丁3没有技能层数字段，基础包又没有该技能。不能按文本算出5后将其记为二进制已证实5层。`7880001` 与 `7020630` 同名、同BUFF、同“+70%”文本，也不能因此复制基础包7020630的7层作为7880001的直接配置证据。

补丁3 `skill_result` schema 只有 `effect_id:EUint32` 和 `cast_moment:EInt32`。基础包另有 `result_target_type`、`success_rate`、`buff_level_rule`、`buff_group_level`。这是版本schema差异，不是当前解析器漏读schema字段。

## 来源与完整性

本次对所有复用的历史提取清单与新增层数关联清单逐项重新计算payload SHA256，均一致；所有实际解析表通过完整行、嵌套结构与数组消耗检查。基础包与补丁3分别使用同包 BUFF、BUFFBASE、EFFECT 分类，未跨版本拼接。

同版表记录数：基础包 SKILL 1378、BUFF 1925、BUFFBASE 1879、EFFECT 956；补丁3 SKILL 1988、BUFF 3309、BUFFBASE 2810、EFFECT 1257。

旧 `unpack_probe_20261025/battle_analysis/effect_table_manifest.json` 实为补丁3 schema + 补丁26 EFFECT数据，共1259行，不能标记成“同版补丁3 EFFECT”。本报告已改用 `layer_reference_probe_20261025` 的真正补丁3数据1257行。

基础包关键payload SHA256：

| 文件 | SHA256 |
|---|---|
| `artifacts/strength_buff_probe_20261025/raw/pakchunk4-WindowsNoEditor/NRC/Content/ScriptC/Data/Bin/BinConf/SKILL_CONF.non` | `017da9f5818226a1cff81f84beb3851a66329f844ddf16dbc2ecfe7601a249ad` |
| `artifacts/strength_buff_probe_20261025/raw/pakchunk4-WindowsNoEditor/NRC/Content/ScriptC/Data/Bin/BinDataCompressed/SKILL_CONF.bytes` | `a5c2ddc25d5a50789c2749acd43c2f969a719ed23120202fe69aed6deb21a824` |
| `artifacts/strength_buff_probe_20261025/raw/pakchunk4-WindowsNoEditor/NRC/Content/ScriptC/Data/Bin/BinLocalize/dev_CN/SKILL_CONF.bytes` | `68a0f426056b75bff675ea7a682e3513364ff18fa1ec39e44ba8e26f2dbbc66d` |
| `artifacts/strength_buff_probe_20261025/raw/pakchunk4-WindowsNoEditor/NRC/Content/ScriptC/Data/Bin/BinConf/BUFF_CONF.non` | `52e4399ec0488a1381f3c9783364449c2f09c9978052fe43422a17ed88366a8f` |
| `artifacts/strength_buff_probe_20261025/raw/pakchunk4-WindowsNoEditor/NRC/Content/ScriptC/Data/Bin/BinDataCompressed/BUFF_CONF.bytes` | `1c86ba36ab78f4306aae717a03171ce742410352919d38467b76ff372df3db68` |
| `artifacts/layer_reference_probe_20261025/raw/pakchunk4-WindowsNoEditor/NRC/Content/ScriptC/Data/Bin/BinConf/EFFECT_CONF.non` | `e16bbe02f298e820fbbdc6e733184246edbb12be89e89b77dbdbfa2692a0353c` |
| `artifacts/layer_reference_probe_20261025/raw/pakchunk4-WindowsNoEditor/NRC/Content/ScriptC/Data/Bin/BinDataCompressed/EFFECT_CONF.bytes` | `df8d2ef895522c36a233c8883b0b66b8a838168ca3ce5dcde997757abcb2eede` |
| `artifacts/layer_reference_probe_20261025/raw/pakchunk4-WindowsNoEditor/NRC/Content/ScriptC/Data/Bin/BinConf/BUFFBASE_CONF.non` | `7e20a6aaf8fe9af6824585c8bbbc858a3b1c4519f9a2bb09f8bfb20f2dd7cd23` |
| `artifacts/layer_reference_probe_20261025/raw/pakchunk4-WindowsNoEditor/NRC/Content/ScriptC/Data/Bin/BinDataCompressed/BUFFBASE_CONF.bytes` | `1c59c84b86456ff96f3d51c659e05bff0e5493e629871b45a02628ff835b5737` |

原始PAK目录是 `E:/WeGameApps/rail_apps/洛克王国：世界(2002304)/Win64/NRC/Content/Paks/`。本次未重新计算整个PAK的SHA256；JSON保留所读payload与原包物理source-range的SHA256、偏移及原包stat/source-range只读不变检查。不能把payload hash冒称整个PAK文件hash。

## 解释边界

已确认：历史配置中的数字、引用、schema字段、字节偏移、局部SHA256与表行完整消耗。待核实：当前线上执行器是否沿用历史层数，缺字段默认值、rule枚举含义、层数与属性的实际结算公式。未执行Lua、未修改游戏或模拟器、未将历史值补入线上快照。

可信度：直接配置与完整性核验 0.99；当前线上层数行为未验证。疑似编造：无。
