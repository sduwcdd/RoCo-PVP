# BWIKI 机制候选审计

快照：`20261025T013619+0800`；对照：`bwiki-declarative-6`。

完整扫描 579 个技能和 246 个特性。
词法命中仅用于安排人工审查与组件开发，不是完整解析、可执行覆盖或新增技能数量；否定句、历史引用和条件中的提及同样会命中。主描述、effect_details 和文字备注按独立字段扫描，表格标签不会拼接成虚构语句；未匹配的文字从未删除。

## 按机制的候选收益

技能／特性分别去重；机制之间有重叠，不可直接求和。‘未结构化’仅指旧编译器未完整表达该描述，不表示只缺本项机制。单机制独占解锁数量无法从词法扫描可靠确定，JSON 中明确为 null。

| 机制 | 维度 | 技能候选 | 其中未结构化 | 特性候选 | 旧组件边界 |
|---|---|---:|---:|---:|---|
| damage | effect | 365 | 212 | 21 | experimental |
| target_opponent | target | 288 | 160 | 79 | experimental |
| target_self | target | 160 | 137 | 99 | experimental |
| response_success | condition | 131 | 130 | 6 | partial |
| power_modifier | modifier | 105 | 104 | 39 | partial |
| stack_count | special | 81 | 72 | 40 | partial |
| condition_explicit | condition | 69 | 66 | 41 | partial |
| cost_modifier | modifier | 63 | 63 | 43 | missing |
| stat_change | effect | 69 | 56 | 53 | experimental |
| shield_defense | effect | 53 | 52 | 0 | partial |
| multihit | special | 68 | 50 | 11 | partial |
| duration_permanent | duration | 48 | 48 | 14 | missing |
| mark | effect | 43 | 43 | 19 | partial |
| duration_turns | duration | 35 | 35 | 11 | missing |
| type_relation | modifier | 35 | 35 | 74 | partial |
| status | effect | 43 | 34 | 30 | partial |
| switching | special | 34 | 34 | 19 | partial |
| condition_history | condition | 28 | 28 | 7 | missing |
| healing | effect | 29 | 26 | 18 | experimental |
| hit_count_modifier | modifier | 25 | 25 | 9 | missing |
| choice | special | 21 | 21 | 6 | missing |
| target_slot | target | 20 | 20 | 29 | partial |
| trigger_attack | trigger | 21 | 20 | 33 | missing |
| energy_restore | effect | 31 | 17 | 20 | experimental |
| target_team | target | 16 | 16 | 16 | missing |
| dispel | effect | 15 | 15 | 1 | missing |
| relay | special | 14 | 14 | 4 | missing |
| evolution | special | 12 | 12 | 9 | missing |
| team_magic | special | 12 | 12 | 14 | missing |
| priority | modifier | 11 | 11 | 2 | partial |
| randomness | special | 11 | 11 | 8 | missing |
| target_random | target | 11 | 11 | 10 | missing |
| type_transform | special | 11 | 11 | 3 | missing |
| charge | special | 9 | 9 | 4 | partial |
| field_weather | special | 9 | 9 | 5 | missing |
| trigger_exhaustion | trigger | 9 | 9 | 17 | missing |
| condition_health | condition | 8 | 8 | 2 | missing |
| interrupt | special | 8 | 8 | 1 | missing |
| trigger_turn_end | trigger | 8 | 8 | 22 | partial |
| burst | special | 7 | 7 | 4 | missing |
| swift | special | 8 | 7 | 6 | partial |
| trigger_receive | trigger | 7 | 7 | 14 | missing |
| copy_transform | special | 5 | 5 | 3 | missing |
| energy_reduce | effect | 6 | 5 | 3 | experimental |
| trigger_entry | trigger | 5 | 5 | 51 | partial |
| named_special_state | special | 4 | 4 | 2 | missing |
| condition_energy | condition | 6 | 3 | 10 | partial |
| condition_first | condition | 3 | 3 | 3 | missing |
| cooldown | cooldown | 3 | 3 | 4 | partial |
| energy_transfer | effect | 3 | 3 | 4 | missing |
| condition_last | condition | 1 | 1 | 1 | missing |
| execution_limit | restriction | 1 | 1 | 12 | partial |
| trigger_exit | trigger | 1 | 1 | 12 | partial |
| trigger_turn_start | trigger | 0 | 0 | 4 | missing |

旧组件边界：experimental=已有显式隔离实验操作；partial=有部分片段或资格检查；missing=旧框架没有通用执行组件。任何一项都不代表完整对战可执行。

## 实现顺序

1. 统一来源绑定的结构化配置、目标/数值/条件 AST 和静态校验；将现有操作迁移为数据，先保证旧行为等价。
2. 统一事件调度、执行预算和来源链；先手度、应对成功、先/后手条件和入场事件分别建模。其覆盖收益跨技能和特性，不按单条技能增加分支。
3. 修正项生命周期（持续、叠层、驱散、冷却）及选择器，之后批量表达状态/印记、能耗/威力/连击数修正。
4. 历史条件与回合事件、入离场生命周期，再处理力竭替换、复制与形态等专用机制。
数值公式、取整、低能量边界及未知事件顺序作为版本政策/显式实验配置，缺少这些政策就返回组件路径上的阻断原因。

## 基础组件触达（未结构化记录并集）

以下是依赖标注对应的审查候选并集，不是实现该组件便能立刻执行的记录数。

- `target_selector`：379 技能、211 特性。
- `numeric_expression`：369 技能、202 特性。
- `modifier_lifecycle`：318 技能、165 特性。
- `event_dispatch`：272 技能、185 特性。
- `predicate`：233 技能、124 特性。
- `action_order`：143 技能、12 特性。
- `switch_lifecycle`：42 技能、64 特性。
- `duration`：34 技能、30 特性。
- `execution_limits`：18 技能、23 特性。
- `battle_history`：28 技能、7 特性。
- `form_change`：23 技能、12 特性。
- `explicit_choice`：21 技能、6 特性。
- `replacement_lifecycle`：9 技能、17 特性。
- `team_resource`：12 技能、14 特性。
- `seeded_randomness`：11 技能、10 特性。
- `skill_usage_history`：7 技能、4 特性。
- `rule_reference`：5 技能、3 特性。

另逐项审计 54 个 BWIKI 命名术语，以正文提及或 desc_notes 引用分别留证。术语文本匹配不等于该记录调用了该机制；例如引用先前迅捷技能不会自动取得迅捷。

JSON 保留全部原文、原始备注、来源模块/网址/哈希、命中字符区间、机制候选 ID 和两两重叠计数。未命中的记录也保留，不冒充无机制或合法配置。
