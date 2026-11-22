# 饮雪狂兽的暴风雪威力核查

## 规则来源

图鉴形态 3343 持有冰雪魂魄。
特性编号为 200311。
暴风雪期间，冰系技能威力增加 100%。
冰系物理技能和魔法技能均可触发。
[11 月 21 日图鉴快照](../../data/bwiki/20261121T162937+0800/catalog.json)

原生规则将暴风雪映射到天气编号 5。
特性监听器 2040094 安装状态 20231260。
该状态对应冰系威力加成。
仅看到监听器不能确认加成生效。
[天气规则](../../artifacts/weather_rules_20261025/weather_rules.json) · [原生状态记录](../../artifacts/weather_rules_20261025/dependency_records.json)

## 漏算与修复

旧预览能识别施放天气技能后的暴风雪。
入场天气和天气变更未进入伤害上下文。
单独捕获特性状态也无法触发加成。

入场包顶层字段 13 报告天气编号。
字段 19 报告到期回合。
演出项字段 29 可另行报告天气变更。
该项子字段 2、5 分别报告天气和到期回合。
客户端将到期回合计入剩余回合。
[协议表](../../vendor/rkpp/rkpp_data.sqlite) · [客户端回合计算](../../artifacts/weather_rules_20261025/scripts/pakchunk4-WindowsNoEditor_3_P/BattleRuntimeData.decompiled.lua)

伤害预览复用已有天气威力规则。
缺少天气证据时，允许采用已生效的特性状态。
预览同时核对有效特性和技能属性。
天气和特性状态同时出现时只增加一次。
已确认其他天气或清场时忽略残留状态。
仅捕获状态时，预览只恢复该特性。
缺少到期回合时，只能确认收到报文的回合。

## 构造回归

测试采用真实技能冰锥，基础威力为 40。
仅捕获特性状态时，旧预览仍显示 40。
修复后，威力为 80。
同一组面板的估计伤害从 180 变为 360。
用例也覆盖暴风雪、雨天和非冰系技能。
这些数字来自构造对局，尚无实战校准。
[伤害预览用例](../../tests/test_live_modifiers.py) · [天气回合用例](../../tests/test_weather_runtime.py)

## 验证结果

天气运行时和伤害预览的 8 项定向测试通过。
扩展检查运行 91 项，报告 3 个失败和 4 个错误。
以下两项与 11 月 21 日基线一致。

- `test_cost_only_entry_trait_does_not_hide_damage_and_status_moves_are_explicit`
- `test_snow_bear_combines_existing_stars_once_and_checks_freeze_conditions`

以下四项模拟用例仍有差异。
旧日志未覆盖这些差异。

- `test_trait_rain_drain_uses_actual_damage` 的回复值不符。
- `test_rain_affects_later_cost_power_single_payment_and_clone` 缺少逐击威力。
- `test_sand_cost_ceil_priority_and_type_change` 缺少克制跟踪。
- `test_weather_traits_modify_speed_attack_and_power` 的两个子用例缺少跟踪字段。
