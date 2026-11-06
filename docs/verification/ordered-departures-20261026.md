# 双方脱离与延迟返场（研究组件）

已保留完整 BWIKI skill record、record hash，以及本地解包 SKILL/EFFECT/BUFF/BUFFBASE 原始行。它们位于 `reviewed-forced-switch-skills-1.json` 和 `reviewed-defense-components-1.json`；表根为 `artifacts/unpack_probe_20261025/battle_analysis/tables/parsed`。

- **7150270 风隐**：1能量，双方脱离，先手-1。原 skill_priority=4（通常技能5）；20480034 分别在 cast_moment11/12 安装，BUFFBASE2048003 opcode48、首参数3。priority_delta=-1 交由共同优先级流程应用一次。
- **7150420 无风**：2能量、减伤50%，应对攻击后双方脱离。1031582 指向7150421；2011003减伤-5000，20190530两条19型监听分别使用目标参数-1/0安装20480170（48型、参数3）。复用原防御应对窗口与减伤，没有新增伤害公式。
- **7110280 集中**：2能量、减伤80%，应对攻击后自身回合结束返场。1031116指向7110281，2011031减伤-8000；20171660→2017166（17型、trigger_type7）→20480098→2048009（48型、参数5）。监听 `is_clean_when_rest=1`；研究队列绑定原member/入场时刻/当前回合，离场、力竭或不同入场实例取消。

原文不确定权威服务器同回合顺序，因此顺序政策明确具名：双方脱离 `opponent_then_self_commit_each_departure_experiment_v1`；延迟返场在普通回合末效果后、回合末脱离特性前。后备选择由相应队伍所有者显式给定，双方在扣能与前段效果前完成预检；免疫与无可用替补独立沿用现有source-bound脱离规则。

`forced_switch_programs.preflight_selection(..., replacement_slot, opponent_replacement_slot=None)` 与 `after_skill(..., replacement_slot=..., opponent_replacement_slot=..., event_token=..., context=...)` 支持双方选择。共享 `forced_switch_runtime.execute_departures` 逐段提交；第二段失败返回已发生state/events及 `partial_commit=True`，上层必须采用后阻断。

防御入口签名不变，`after_defense` 对即时双方脱离同样可能返回partial_commit。`defense.end_round_departures(catalog, state, *, context)` 返回完整fragment；需 `context['defense_end_return_policy']=defense.END_RETURN_POLICY`，上层先采用state/events后检查status，再核对真实倒下。原场地、天气、特性、history、入场等共同hooks保留，无强制换人Swift。

7150270与7150420均要求两项显式选择；simulation API透传`opponent_replacement_slot`，前端现有双方独立选择控件已可复用。未把上述具名研究时序宣称为服务器实战校准。
