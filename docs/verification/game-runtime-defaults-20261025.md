# 研究试战所用的游戏配置默认值

2026-10-25，只读取已有解包结果；未改游戏目录、未执行游戏脚本、未再次大规模解包。

`lab.game_runtime_defaults.load_game_runtime_defaults(verify_sources=True)` 返回独立数据副本。版本为 `game-runtime-config-20261025-v2`；默认核对五张解析表、Enum，以及本轮新增的六份宠物能量 getter 来源文件的 SHA-256，漂移即拒绝。文件 hash、选用包名及原行都随结果返回。包名后缀选择来自此前提取清单，尚未核实实际运行时包优先级。模块不安装战斗规则、不将缺失数值补零。

## 手动恢复能量与技能蓄力

可用于执行实现的链：

- `BATTLE_GLOBAL_CONFIG.pet_common_globalskill.num = 7000010`。
- `SKILL_CONF[7000010]` 名称为“聚能”，描述为“获得5点能量。”；`energy_cost=[0]`、`skill_priority=5`、`cd_round=[0,0]`；唯一结果为 `effect_id=1019005, cast_moment=10`。
- `EFFECT_CONF[1019005]` 的操作码为19，即 Enum 的 `ET_CHANGE_ENERGY`；原参数为 `[[5],[0],[0]]`。
- 聚能的 `type=4` 对应 `SAT_GLOBAL`；Enum 另有 `SAT_CHARGE=10`。因此聚能不能与技能蓄力状态合并成同一含义。配置中聚能技能名称也不应改写成“蓄力”后称为原文。
- 模块给出 `recharge.amount=5`、`energy_cost=0`、`priority=5`，适用于显式选择的研究执行规则。`cast_moment=10` 仅保留原值；没有用表现枚举证明实际结算顺序。`cd_round_raw` 原样保留，兼容字段 `charge_rounds_raw` 也只保存同一原数组，不能据此推断充能协议。

**v2 更正：宠物上限优先读取运行时 `max_energy`，字段缺失时回退10。** `energy.pet_maximum_fallback=10` 已绑定新的 `BattlePet:GetMaxEnergy()` 源证据。`maximum_raw=9` 仅保留 `character_max_energy.num` 的原值，标记 `maximum_raw_role=character_config_only_not_pet_cap`，不再作为宠物上限默认。

已核对 `artifacts/strength_buff_probe_20261025/energy/RESULT.md`、`bytecode_check.json`、`GetMaxEnergy.disassembled.txt`。`utils/raw/pakchunk4-WindowsNoEditor_3_P/NRC/Content/ScriptC/NewRoco/Modules/Core/Battle/Entity/BattlePet.decompiled.lua:1859-1865` 的实际表达式是 `insideInfo and insideInfo.max_energy or 10`。反汇编同时显示读取 `max_energy`、测试分支、`loadi r4 10` 及返回r4。Lua数字0为真值，故运行时上限0会保留，不能用Python `value or 10` 模拟这个分支。

原始luac、标准化字节码、反编译文本及上述三份核验文件均加入固定hash。标准字节码 SHA-256 为 `7d5bb4f239bd704db9da8c1635bf2c901a7fc51341d6ea452314bc2860da0410`；反汇编为 `72df379e6d9f77a7a64916158e0d5e49c0d7bf1bf36de820c7134335ec0b7d21`，与 `bytecode_check.json` 的源和输出绑定一致。返回的 `pet_maximum_fallback_source` 保留路径、行号、字段、表达式、hash及核验标记。

`BattleDataCenter.luac.decompiled.lua:715-721` 接收 `energy_result` 和 `max_energy`，分别调用 `SetEnergy` / `SetMaxEnergy`。因此真实同步上限优先于回退10；该getter既不读取 `character_max_energy`，也不进行9加1。9的实际消费者仍待定位；服务端如何生成初始上限及特殊上限仍待核实。

未在本轮读取的 GLOBAL/RULE/PVP/BATTLE 表找到开局宠物能量的明确字段。`round_energy` 原行只有 `id=221,key=round_energy`，没有 `num`。宠物上限getter回退10不能推导为开局能量10，也不能将缺少 num 推导成每回合自动回能0。若研究试战选开局满能/自动回复0，属于需写入 profile 的实验策略。

## 回合末烧毒与条件性回能

| 状态 | 原始数据 | 直接支持与边界 |
| --- | --- | --- |
| 中毒 20070010 → 2007001 | `buffbase_order=7, trigger_type=7`；参数 `[[2],[2],[300],[0],[12],[0],[0],[30]]`；reduce `13:[999,0]` | 描述为回合结束受到3%生命的毒系伤害，毒系精灵免疫。未证明生命基数、层数乘法、属性抗性和取整。 |
| 灼烧 20070020 → 2007002 | `buffbase_order=7, trigger_type=7`；参数 `[[2],[2],[200],[0],[4],[0],[0],[20]]`；reduce `6:[1,5000]` | 描述为回合结束造成2%生命的火系伤害并衰减一半层数，火系精灵免疫。未证明先伤害或先衰减、半层取整、生命基数。 |

Enum 绑定 `buffbase_order=7 → BFT_DAM`；`reduce_type=6 → BRT_ROUND_RATIO`。现有证据可支撑“回合末百分比伤害/灼烧按比例衰减”的研究机制输入，但无法唯一确定伤害方程及调用次序。模块返回完整原状态和基础状态，没有将300/200自动替换成某个伤害基数。

另外发现两条**有条件的状态效果**：恢复能量 `20170170 → 2017017 → 1019010`，末级参数 `[[10],[0],[0]]`；能量恢复 `20350230 → 2035023 → 1019025`，末级参数 `[[9],[0],[0]]`。两条基础状态有自己的触发/过滤参数，不能把10或9推广为所有宠物每回合自动回复。当前读取结果也没有证明通用回合末魔力回复数值。

## 面板与伤害公式

`PVPRankedMatchModuleUtils.luac.decompiled.lua:211-235` 明确读取 `attribute_info` 下六个属性：`attack/defense/hp/special_attack/special_defense/speed`，以各自 `talent` 非零来加入资质列表；其导出使用前三个列表元素填入 `talent_a_name/talent_b_name/talent_c_name`。这支持六属性的资质标记结构和三个显示槽，不能单独证明服务器强制恰好三项，更不能证明0..10如何转换到 raw 面板。

Enum 的属性 ID 可直接绑定：生命1、物攻2、魔攻3、物防4、魔防5、速度6。种族值/资质/等级/性格到最终面板的计算仍需明确研究公式或用户实测面板。

本轮没有找到能够验证 arena/showdown 候选伤害公式的新计算处理器。`BattleDamagePlayer` 读取 `performInfo.damage_info` 并驱动伤害显示；`BattleDataCenter` 接收 `hp_change/hp_result/attr_result`。这些服务器结果或显示分段不能作为正式伤害公式证据。

## 检查

运行 `python -m unittest discover -s tests -p test_game_runtime_defaults.py -v`，4项通过：原链和缺失值边界、状态原值与独立副本、来源漂移默认拒绝及检查模式标注、宠物getter反汇编漂移拒绝。测试明确区分原始character值9和宠物回退10。未生成临时冒烟脚本或游戏文件。
