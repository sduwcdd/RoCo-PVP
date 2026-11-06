# 能量条件技能独立复核（2026-10-25）

结论：本次限定范围内未发现阻断问题。此结论只涉及来源文本翻译与显式实验解释器，不表示技能已完成真实游戏校准，也不批准正式训练。

## 来源与范围

使用项目 BWIKI 快照 `20261025T013619+0800`；重新编译得到的规范化来源哈希为 `d9ef77081b18e35fddfc04e2ecaa6c00941602c007ff3813ce3d08355b8d8e97`。这不是原始 catalog 文件字节哈希。本次报告核对固定快照及其来源链接，不宣称网页当前版本与快照必然一致。

| ID | 来源 | 快照效果 | 正确保留的差别 |
| --- | --- | --- | --- |
| 7020440 | [触底强击](https://wiki.biligame.com/nrc/触底强击) | 造成魔伤，使用后若能量耗尽，本次技能威力+120。 | 基础威力 95；条件成立时威力 215，伤害倍率仍为 1；`source_timing=after_use` |
| 7020530 | [穿膛](https://wiki.biligame.com/nrc/穿膛) | 造成物伤，若敌方能量小于等于2，造成5倍伤害。 | 基础威力始终 65；满足条件时伤害倍率 5；`source_timing=unspecified` |
| 7170110 | [背袭](https://wiki.biligame.com/nrc/背袭) | 造成魔伤，若敌方能量等于0，造成20倍伤害。 | 基础威力始终 40；满足条件时伤害倍率 20；`source_timing=unspecified` |

“使用后”不足以证明实际游戏在支付费用之后读取能量；另外两项原文没有明确时点。程序保留这个缺口，只有调用者明确提供 `conditional_policy={"timing":"after_payment_before_damage_experiment"}` 和 `resolved_energy_cost`（包括零）时才能进行实验。

## 实现检查

- 编译器只新增上述三段完整文本；v3 与 v4 编译结果差集恰为这三个 ID。v4 为 579 技能中 170 compiled、409 unsupported；246 特性仍全部 unsupported。训练许可、可执行和真实游戏验证标记均为 false。
- 条件对象、比较符、目标、数值、修正对象和时序策略在运行前验证；缺少费用或策略不进行伤害回调，不保留支付和部分事件。
- 执行条件时读取当前状态：支付之后、前面操作之后；不会复用验证阶段的能量值。双行动测试覆盖先手支付及回复后的能量，再供后手条件读取。
- `power_add` 修改传入回调的威力；`damage_multiply` 单独通过 `damage_multiplier` 传入。回调契约是返回最终整数生命损失，解释器只扣除一次，不在回调返回后再次乘倍数。
- 回调拿到独立副本；其修改不会污染原始输入、后续状态或记录下来的条件、倍率和时序策略。
- 双行动预检覆盖后手缺少条件策略时在先手伤害回调之前阻断；已有事务测试覆盖第二行动失败时整体回滚。

## 独立执行证据

运行 `E:/miniconda3/python.exe -m unittest tests.test_skill_programs tests.test_effect_runtime tests.test_action_runtime -q`：**98 tests，44.075 秒，OK**。

另用直接传给 Python 的内存脚本执行 **540 个条件组合**：三个技能，自身能量 0～12，每个能量值选择去重后的费用 `{0, energy, max(0, energy-1)}`，敌方能量 `{0,1,2,3,7}`。每个组合独立断言条件命中、最终威力、倍率、费用后能量、事件，以及回调固定返回 7 时只损失 7 生命。回调故意修改其参数、状态及策略副本，原始输入仍完全一致。全部通过；没有留下临时冒烟文件。

这些是构造状态、构造费用和构造伤害的解释器测试，不能充当真实游戏对局或伤害公式标定证据。

## 复核文件 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `lab/skill_programs.py` | `D29F4D6FD7AA53B3B3078A0974AC02402272EF0C482AD940EA475EBA43359D73` |
| `lab/effect_runtime.py` | `0E1D0B1C96DF2124D3CC0EA252040A33FB2555D43B04C0BDACFEF9A5E1CACAEA` |
| `lab/action_runtime.py` | `E0743F1A04275A7F89F05EA7D71E94F049E2FE3850CA8856CDF334A893234E19` |
| `tests/test_skill_programs.py` | `15587C0316F9E5A73AAF4E93AC6572A20D9AE231E74AF2DBAD4BB1202CB53952` |
| `tests/test_effect_runtime.py` | `4A1CCDF4113BCDF3B2E9711E0508D29A788469A5FBE7E768EA4147DD71DDAD3E` |
| `tests/test_action_runtime.py` | `22B1E1C2071C6D6D7CCEF0EA1D3579A5D31AC59D02692045E6D98600777484B4` |

可信度：98/100（限定为上述实现与测试结果）。已确认：三技能来源翻译、实验依赖门禁、实时条件读取、倍率契约、隔离和回归结果。待核实：真实游戏条件读取时点、完整伤害公式、被排除的钩子及完整回合机制；缺少真实对局校准，不能由这些构造测试确认。疑似编造：无。
