# 团队能量目标与来源（2026-10-26）

新增 `lab/team_target_programs.py`、`data/rules/reviewed-team-targets-1.json` 及3项定向测试。程序先通过既有技能执行器完成正常费用和普通伤害前段，然后由whole-state post-hook选择来源指定的队伍/位置；每名接收者的能量增减仍调用既有`execute_effects` primitive。

| 技能 | 完整原文 | 研究执行的目标与数值 |
| --- | --- | --- |
| 7030510 富养化 | 为场下每个精灵回复3能量。 | 己方存活后备各+3；己方active和敌方均不处理 |
| 7170330 小型打劫 | 敌方队伍中所有精灵失去1能量。 | 敌方存活全员各-1，包含active |
| 7030560 养分回流 | 造成魔伤，为场下所有精灵回复1能量。 | 正常75魔伤/费用3前段一次，然后己方存活后备各+1 |

## 场下范围的确切依据

“场下所有”不从自然语言猜成双方。在独立历史补丁2的`SKILL_CONF`中，7030510的1019003和7030560的1019001能量效果都明确保留`result_target_type=5`；已提取`Enum.ResultTargetType`明确`RTT_UNDER_ALLY=5`。两者因此选择己方后备。配置保留补丁2原行和文件hash，原版本不回填当前补丁3缺失字段。7030560的补丁0/1还保留过旧占位文本，未被当成当前机制。

当前安装配置的7170330原文明确“敌方队伍中所有精灵”，`target_type=3`与`Enum.SkillTargetType.STT_ALL_ENEMY=3`一致。其`skill_result`重复两次1019011，但当前表缺少这两槽的result_target字段。实现保留两槽原文，不虚构每槽分别对应active/reserve，也不把重复槽执行成每人-2；按完整来源文本每人-1。active与后备的全队范围依据完整文本，不能声称已恢复缺失的每槽服务端目标语义。

`EFFECT_CONF`能量操作opcode19参数分别是+3、-1、+1；1081001是opcode81，Enum映射为`ET_ANIMATION`，没有将其当成另一段战斗能量收益。BUFF/目标枚举、原始效果、技能记录、历史目标操作数及hash均保留在配置。

## 命名研究策略

`whole_state_team_energy_after_committed_skill_living_targets_v1`使用技能成功后、下一行动前的现有队伍状态选目标。HP=0的成员跳过，不回血、不复活；回复按每名成员自己的max_energy封顶，减少最低0。原技能伤害/费用由上游负责，本模块既不重复扣费，也不向接收者发出普通`skill.use`或`skill.after`来源事件；所有事件记录原施法者、源skill id/hash、目标side/slot/member id、请求值和实际变化。

目标资源和来源程序在普通前段之前预检。post-hook本身以副本事务应用全部目标，任何接收者异常都返回原状态及空events；上游已完成技能的保留策略沿用既有post-hook规则。唯一action token防止同次技能重复应用。死者是否可接受增减、精确服务器时序、历史补丁覆盖顺序和当前线上行为尚未实战确认，训练资格保持false。

## 接入

- `programs(prepared)`加入现有reviewed overrides/cache（缓存stamp纳入CONFIG）。
- fragment context合入`research_context()`；状态技的空普通前段沿已有component-sequence payment通道，许可`team_target_components`并设置`component_sequence_payment=reviewed_component_sequence_v1`。
- 支付/普通伤害前调用`preflight_targets(prepared,state,side,program,context=...)`。
- 成功提交原技能后调用`after_skill(...,event_token=...,context=...)`，按其fragment结果提交state/events。

## 定向验证

`python -m unittest tests.test_team_target_programs -q`：3项通过，1.410秒。覆盖己方后备范围、active/敌方不受益、能量封顶、死者跳过、原来源事件与token幂等；敌方active及后备每人仅-1、零能量下限、重复原槽不造成-2；养分回流75威力伤害一次和费用3只支付一次，后续后备+1；修改目标组件程序拒绝且hook状态不变。没有新增长时试战或实战校准。
