# 渴求与盛宴的攻击后吸血组件（2026-10-26）

新增 `lab/trait_attack_hooks.py`、`data/rules/reviewed-trait-attack-hooks-1.json` 和4项定向测试。没有修改原特性主模块、效果/机制执行器或回合集成文件。

## 直接来源

- 渴求200139的BWIKI及安装技能文本均为“入场时获得50%吸血”。技能引用20540030，BUFF描述明确造成伤害的50%转为生命；base2054003的opcode54、第5项参数5000。`Enum`明确`BFT_BLOOD=54`。
- 盛宴280030的文本明确低于50%生命时吸血100%。21530030→2153003保留阈值参数`[3,5000]`及20540012引用；20540012描述100%吸血，包含10个2054001，每项参数1000。原始重复位置保留，不简化成凭空默认层数。
- 贪得无厌280032还含“每过量回复5%生命转化为10%物攻”。本模块明确拒绝完整特性，因为余量累计、阈值及跨事件层数算法尚未恢复；不会只编译50%吸血而把整项标成支持。

配置绑定上述原始记录、形态→特性映射、BWIKI行hash和三个安装配置表/Enum文件hash，加载、入场、攻击绑定时复核来源。

## 实际伤害与研究时序

采用命名策略`trait_lifesteal_actual_damage_sum_floor_once_action_hp_snapshot_v1`：生命条件在本次HP费用支付后、技能效果执行前采样一次；同次技能各段已经提交的物理/魔法直接攻击实际HP损失合计后，仅取整一次并在整次技能后回复。这与现有机制吸血按整次实际损失合计的研究策略一致，不宣称等于服务端每段即时吸血。

只采纳共用执行器生成的`damage/damage.hit`且目标为opponent、kind为physical/magical的事件，并验证整数`damage=before-after`。印记、毒、烧伤及其他间接伤害排除；不拿威力或名义伤害充当损失。非零重复事件拒绝。回复交给既有`execute_effects`的`hp.restore`，复用精确有理数、floor、maxHP封顶及overflow记录，不另建伤害/回复公式。

技能自带`hp.drain`、奉献lifesteal或同一攻击已经发生其他吸血时阻断，因为可加/取最大/先后顺序没有确定来源。绑定action token后同一hook重试不会再回复。力竭成员不被吸血复活。盛宴支付模块另行处理5%生命代能；本hook读取并核验完整支付quote后以`hp-paid_hp`判断50%边界，避免在实际扣款后再次减一次。

## 接入接口

1. fragment context合入`research_context()`。
2. 初始活动成员调用`initialize(prepared,state)`。它保留原模拟器初始`entered_turn=0`并将aura.entry_turn绑定为0，不修改脱离免疫条款；普通`on_entry(prepared,state,side)`仍要求实际入场回合≥1，须在Swift之前调用。
3. 扣款及技能执行前，以带队伍奉献字段的relative actor调用`prepare_attack(prepared,member,program,context,token=...)`，保存binding。渴求需要匹配当前入场的aura来源记录。
4. 技能成功并写回full state后，调用`after_skill(prepared,state,side,program,fragment_events,binding,context=context)`，附加返回事件。该hook本身以副本事务提交，失败不会暴露部分回复；外层已完成技能是否保留由既有post-hook事务策略负责。

## 验证

4项定向用例通过，1.611秒：渴求入场与幂等、3+3实际多段只floor一次回复3、间接伤害排除；盛宴180/350经缺1能支付17后163触发100%吸血，恰好175/350不触发；吸血叠加及贪得无厌拒绝；封顶/overflow；伪造或重复实际损失拒绝并保持hook输入状态不变。随后扩展同一初始化用例验证0回合初始aura保留、普通on_entry拒绝0；单项重跑通过，1.408秒。

未新增长时试战或实战校准。服务端每段阈值刷新、吸血叠加、BUFF解除/驱散和过量回复转属性仍未宣称还原；训练资格保持false。
