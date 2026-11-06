# 纯蓄力伤害的加载时适配

接口：`lab.charge_program_adapter.load_charge_program_overrides(catalog)` 返回 `{int skill_id: program}`，传入既有研究回合的 `program_overrides`。不修改 active 规则文件，不在战斗运行时解析自然语言。`validate_charge_program_overrides` 可在加载边界重新绑定整个映射。

版本 `bwiki-pure-charge-release-1`。固定 BWIKI Skills revision 18764，原始内容 SHA-256 为 `f6a9ab91a71575d5a03f6ba0e61dacad7add7a551f0c735e499ee4ead17dcbb0`，标准化技能表另验完整 hash；再通过既有 `load_phase_config` 校验配置文件清单、快照和每技能 hash。蓄力术语1007经 `ActionRules` 完整核验。不是从一句技能描述中删除“蓄力”后交给普通编译器。

当前快照5个蓄力技能中，仅升龙咆哮7100150符合完整纯伤害结构：

- BWIKI 完整句：“蓄力，对敌方造成魔法伤害。”，仅关联术语1007，没有补充效果；威力200、能量3、魔法、龙系。完整记录 hash `9aac80749c16ea34aef01a29b4c8206d2214ec4ff4e5afc490ae2be55b0c85d9`。
- 游戏表 `dam_para=[200]`、`energy_cost=[3]`、`damage_type=3`、`skill_feature=4`、`cd_round=[0,0]`；技能结果是 `20880010/cast_moment25`。这些是数字/结构对照，不是正式伤害公式或调度证据。
- 游戏状态20880010引用18个基础状态，包括2088001/opcode88、2017078/opcode17及多条opcode3免疫项。2088001参数为 `[[1],[0],[20010800]]`；Enum 对88仅给出 `BFT_EIGHTY_EIGHT`。因此**没有声称整个游戏状态图已解释**。完整状态行、18个base、opcode17所引用的效果原行都保留在 `charge_adapter_evidence`。

整个 BWIKI 语义由两部分承载：既有 source-bound `phase_config + ActionRules.charge_transition` 负责蓄力准备、下一回合释放与离场免疫；overlay只提供标准 `damage` 释放负载。研究回合仍显式选择蓄力准备0费、释放支付一次的实验政策，伤害继续使用外部研究 resolver。`execution_scope` 明确该负载需要外部蓄力阶段。游戏buff图完整性、正式伤害公式及当前版本实战准确度均未声明已确认。

适配按完整句型与结构工作，不用技能名称分派效果；当前固定快照只有7100150被接受。吹炎的应对状态翻倍、怨力打击的受击威力转换、龙之利爪的50%吸血、龙吟的双攻百分比及固定速度都保留不支持，不截掉未知后缀。

检查：4项专项测试通过，包括真实来源7100150的两回合组合、源文本/程序变更拒绝、游戏文件漂移拒绝、完整原图保留。组合测试证明准备回合不支付且不产生200威力攻击，下一回合统一执行器恰好收到一次200威力魔法攻击、支付3点并清除蓄力记录。测试resolver为固定17伤害；该测试不证明正式伤害数值。
