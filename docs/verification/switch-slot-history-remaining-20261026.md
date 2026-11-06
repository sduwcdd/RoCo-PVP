# 当前换人、槽位与历史剩余项

运行 `python scripts/audit_switch_slot_history.py` 可按当前合并程序刷新。标签仅用于离线审计，不参与运行时句子识别。

原始准入扫描：全目录 83 项，本范围 24 项；排除借用/取念/复写原技能后分别为 80 / 21 项。其他组并发修改可能使快照随后变化。

| 技能 | 分类 | 具体依据或缺口 |
|---|---|---|
| 7020840 借用 | dynamic_original_excluded | Runtime-generated candidate is checked after draw; original generator is not an unimplemented ordinary executable skill. |
| 7020850 取念 | dynamic_original_excluded | Runtime-generated candidate is checked after draw; original generator is not an unimplemented ordinary executable skill. |
| 7020860 复写 | dynamic_original_excluded | Runtime-generated candidate is checked after draw; original generator is not an unimplemented ordinary executable skill. |
| 7070060 轴承支撑 | slot_modifier_composition | Persistent growing adjacent discount needs source-bound per-target-slot modifiers and edge-neighbor selector; existing global skill-ID discounts differ. |
| 7070070 联动装置 | slot_modifier_composition | Adjacent slot power+20/+30 needs per-slot source target identity across movement and the edge selector. |
| 7070080 能量守恒 | slot_modifier_composition | Defense response adjacent permanent cost-1 requires the same per-slot modifier target contract. |
| 7070250 减压阀 | slot_modifier_composition | Growing adjacent power aura plus transmission needs per-slot modifier target contract and edge selector. |
| 7070290 过山车 | cross_member_identity_gap | Cross-member one-slot rotation splits original bundles; current original-owner identity supports whole bundles only. Requires per-slot origin migration, not dropping histories. |
| 7100250 龙血 | charge_action_admission | Defense usable during charge requires selected-action admission without discarding pending charge; cannot be replaced by next-charge bypass alone. |
| 7100300 龙守望 | charge_choice_stun_composition | During-charge alternate action, choice, defense interrupt and next-turn stun all need the full composite contract. |
| 7110350 双联脉冲 | whole_release_dispatch_gap | 20930100/93 ->21080090/108; historical108 says consecutive skill release+1, not hit+1. See release-count-sources. |
| 7110360 过载回路 | whole_action_dispatch_gap | 20171061/17 ->20150070/15 says next extra cast and historical15 says act twice; return is reusable but cannot admit only that prefix. |
| 7110380 感电 | whole_release_dispatch_gap | 20730110/73 ->20640560/64 ->21080091/108; departure growth source known, release payment/hooks dispatch still missing. |
| 7110420 电磁偏转 | whole_action_dispatch_gap | Defense response grants next-turn selected skill extra use; same15 dispatch boundary as overload. |
| 7110460 踏雷 | burst_history_copy_gap | Requires actual previously-triggered burst effect history and copied-effect replay pool, not just first-action predicate or return. |
| 7130220 掩护 | incoming_defense_composition | Response21120010/base2112001 opcode112 parameter791337 matches BATTLE_GLOBAL_CONFIG.yanhu_buff112; the new-entry transfer algorithm/window remains unread, not a missing ordinary guard buff. |
| 7150320 疾风连袭 | whole_release_dispatch_gap | Replay actual past Swift releases plus sum-cost/2 and own cost growth; whole-skill release queue and retained Swift source trace needed. |
| 7160170 示弱 | external_menghua_formula | Menghua conversion lifecycle/source semantics intentionally remain unresolved; outside slot/history implementation. |
| 7160180 赤子之心 | external_menghua_formula | Same Menghua lifecycle boundary; do not admit only cost prefix. |
| 7160250 撒娇 | external_menghua_formula | Same Menghua lifecycle boundary; do not admit only three-hit prefix. |
| 7160400 做好事 | choice_random_history_composition | Count committed choice uses, three random stat layers per use, then reset; random-stat/choice owners. |
| 7170310 吃独食 | choice_random_history_composition | Same choice-use count/reset with opponent random debuffs; random-stat/choice owners. |
| 7190310 超新星馈赠 | external_starmark_formula | Star-mark lifecycle/numeric trigger boundary; permanent grant-stack history alone cannot admit whole skill. |
| 7190490 观测者效应 | external_form_transition | Next entrant forced Moonfall state needs complete form/stat/skill/source transition; no partial form-name substitution. |
