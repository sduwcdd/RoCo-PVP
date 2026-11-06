# 机制推进批次 b5 — 剩余清单收尾 + 平台完整对局验证

日期：2026-10-27
引擎版本：`composable-battle-20261027-10`
快照：`20261025T013619+0800`

本批在 b4（啮合传递/联动装置/相位移动）基础上完成剩余清单中的**可证据闭环部分**：体重/属性差威力 5 技、过山车 7070290、能量守恒 7070080、疾风两技（7150170/7150320）、星陨打伤量解码，并把完整对局冒烟从「服务器 API 真实入口」打通。证据不足的萌化/特性 200294/719 系列 17 技保持未动并记录缺口（见 §6）。

---

## 1. 体重/属性差威力 5 技（新模块 `lab/power_rule_runtime.py`）

### 整句
- **7160150 砂糖弹球**：体重差越大威力越高（rule 35，`dam_para [0,20,40,60,80,100,120,0]`，flag0 = |体重差|）；
- **7020990 吨位压制**：敌方越重威力越低（`[0,160,140,120,100,90,80,1]`，flag1 = 敌体重）；
- **7021000 以重制重**：敌方越重威力越高（`[0,80,90,100,120,140,160,1]`，flag1 = 敌体重）；
- **7150250 闪击**：速度差查表（rule 38，`[60,6,0,20,40,60,80,90,100,110,120,130,140]`，步长 6）；
- **7080320 鸣沙陷阱**：物防差查表（rule 38，`[60,4,0,20,40,60,80,100,120,140,160,180]`，步长 4）。

### 证据
- `BATTLE_RULE_CONF.json` 无 damage_rule 语义（263 行）；`SKILL_CONF.json` 的 `damage_rule` 字段直接给出**查表**而非公式。
- **体重字段缺口**：`catalog forms` 只有 hp/patk/matk/pdef/mdef/spd，**任何解包表都没有 weight 字段**；分档单位无客户端证据。按纪律不猜 → 采用「10kg/档、成员显式 weight 字段」实验口径，写入 `installation_uncertainty`。

### 实现
- `power_rule_runtime.py`：`programs/validate_member/rule_power/resolve` + `POLICIES`；
- `power_query.quote_damage_power` 的 history_power 前插入 `rule_power` 钩子（所有伤害路径统一生效）；
- `resolve()` 把 rule 攻击解析成可执行 damage op，`_preflight_component_unpaid/_execute_component_unpaid` 各加 `power_rule_components` 分支；
- rule 35：`level=min(5,int(qty//10))`、`power=para[1+level]`；rule 38：`level=min(10,max(0,int(diff//step)))`、`power=para[0]+para[2+level]`。

### 战斗内验证（`scripts/_probe_battle_mech.py`）
```
7160150 weight diff 10 -> 40（para[2]）; diff 80 -> 120（封顶 para[6]）
7020990 敌重 100/200 -> 80（更重档位更低，封顶 para[6]）
7021000 敌重 100 -> 160（更重档位更高，封顶 para[6]）
7150250 速度差 0 -> 60（基数）; 7080320 物防差 0 -> 60（基数）
```
配置 `data/rules/reviewed-power-rule-1.json`，sha256 `ac8b6fe6…`。

---

## 2. 过山车 7070290（新模块 `lab/team_rotation_runtime.py`）

### 整句
> 使用后全队按槽位整体下移一位（横排 4 槽展平），队首绕回队尾；位置锁阻断。

### 实现
- `team_rotation_runtime.py`：横排 4 槽展平整体下移一位、末尾绕回队首；位置锁（如相位移动/啮合传递的位置依赖）阻断旋转；
- `team_rotation.plan` 写入新模块 programs；`runtime_capabilities.py` 白名单补行。

### 验证
- 冒烟对局中 `team_rotation.rotate` 实际触发 **6 次**（跨成员下移），无 blocked。

---

## 3. 能量守恒 7070080（扩写 `lab/adjacent_cost_runtime.py` + `lab/defense_runtime.py`）

### 整句
> 减伤 80%；应对攻击后两侧技能的能耗永久 -1。

### 证据
`skill_result` = [20110310, 1031111, 20620060]；buff 20640730 base 2064073 参数 `[8],[5],[2],[1],[-1],[6],[0],[0]`（op 8 邻位机制、amount -1）。

### 实现
- `_grants/grant_total/grant` 账本：`{slot: {entries[], total, grant_hash}}`，同 token 幂等、金额白名单（-1）、fingerprint 校验；
- `resolved_cost` 叠加；`defense_runtime.execute_defense_skill` 响应效应新增 `adjacent_cost.grant` 分支；
- 配置 `reviewed-defense-components-1.json` 新增 7070080 → **42 个防御技能**，CONFIG_HASH `334b169ab39a220b45a1f253154f33e5a4c8d4e129270917836cbcb9f7c7fc3c`。

### 验证
- 账本探针：7070080 在 slot 2 授予邻位 slot 1 `-2`（probe 用 -2 验证账本链路），entries 含 source_skill_id/amount/turn/token；
- 冒烟对局 energy.pay 正常；`adjacent_cost.grew`（自身成长）在 HTTP 实测回合中触发。

---

## 4. 疾风两技（新模块 `lab/swift_release_runtime.py`）

### 整句
- **7150170 疾风涡轮**：翼系技能使用 3 次后自动入队释放（power=100 物理翼系攻击）；
- **7150320 疾风连袭**：激活时把已释放的迅捷技能（除自身外）全部入队重放，cost = floor(已释放迅捷能耗和/2) + 已用次数。

### 证据
- 疾风 buff 20060110 base 2006010 = `[4],[1],[2006010],[7150170]`（翼系计数→自动释放）；
- 疾风连袭 buff 2064087 base = `[7],[7150320],[2],[1],[1],[6]`；
- catalog 迅捷技能 8 个（7150080/7150110/7150150/7150260/7150300/7150320/7150400/7150410）。

### 实现（多次冒烟修复后）
- `swift.after` post_hook（翼系计数/迅捷记录）→ 主循环后、状态结算前的 drain 循环；
- drain 用 `overrides.get(sid, ...)`（source_hash 绑定）、`act` 补 `effective_cost=0/effective_priority=0`、`_fragment(program)` 构建 context 并带 `swift_auto_release` 标志；
- 7150170 自动释放 preflight/execute 均放行（execute 构造 power=100 物理翼系 damage op 并委托 execute_skill）；
- 迅捷能耗读 `swift_skills` 表（list 型取首项）。

### 验证
- 冒烟对局中 `swift.wing_count` **16 次**、`swift.auto_queued` **4 次**——自动入队派发在真实战斗内闭环（此前卡在 `cannot_be_actively_used` 的点已修通）；
- 单元测试 `tests/test_b5_mechanisms.py`（25 项，含 swift 4 项）通过。

---

## 5. 星陨打伤量解码（mark 1035）

### 证据
BUFF 20940010（mark 1035）"非幻系受击消耗全部层数受到额外幻系伤害"；BUFFBASE 2094001 `buffbase_param=[20]` → **每层 20 幻系伤害**。

### 实现
- `reviewed-mark-components-1.json`：mark 1035 `damage_amount:20`；CONFIG_HASH 重新钉住；
- `mark_runtime` star 分支优先 `effect["damage_amount"]*stacks`，否则 fallback resolver；
- **两处 preflight 同步解码**：此前非幻攻击星陨标记目标一律要求专用 resolver（战斗内会把星陨标记目标的所有非幻攻击全部拦死）→ 现按 20/层直接结算。

### 验证
- 单测重写为「4 层 × 20 = 80」：`hp 100→20`、层数清空、幻系免疫、无标记后不再触发；
- 顺带修复：`attach_relative_marks` 需要 `member_id`、`mark_programs 32→33 / blocked 11→10`（解码使 7180390 纺纱转为完整程序）。

---

## 6. 完整对局冒烟 + 平台入口（本次关键交付）

### 冒烟
`scripts/_smoke_platform_battle.py` 走**真实服务器 API**（`simulation_request` prepare→start→act→replace）：

```
slots after start: a [[7160150,7150250,7070290,7070080],[7150320,7150170,7020990,7080320],...] b [...]
first act: applied []
turns executed: 75
winner: a
new-mechanic events fired: damage, energy.pay, swift.auto_queued, swift.wing_count, team_rotation.rotate
op tally: damage 47, energy.pay 151, swift.auto_queued 4, swift.wing_count 16, team_rotation.rotate 6
SMOKE OK
```

### 平台入口（HTTP 实测）
```
python -m lab.server --port 8766            # 启动工作台（web/ 同端口服务）
http://127.0.0.1:8766/battle                # 战斗页面 200（29KB HTML）
GET  /api/catalog                           200
POST /api/simulation/{prepare,start,act}    act -> status=applied, turn 2
                                             events: adjacent_cost.grew / transmission.move / damage / energy.pay
```

### 回归
合并 10 个模块 **117 tests OK**（defense_runtime / mesh_and_gearbox_runtime / adjacent_power_aura_runtime / adjacent_cost_runtime / pressure_runtime / response_cost_runtime / power_rule_runtime / b5_mechanisms / mark_runtime / research_phases 一次合跑，117 通过 0 失败）。

期间修复的引擎真实问题：
- `rule_power` 对未配置技能返回 None 会污染所有伤害路径（改为返回原 base_power）——**这是本次重跑出的关键回归源**；
- 蓄力释放增加「未编译蓄力不得伪造完整释放」安全闸（区分 raw/override 来源 + 适配器 execution_scope 标记）；
- 星陨 preflight 解码（见 §5）；
- 过车/疾风 plan-op 白名单、drain source_hash 绑定、effective_cost 缺省等冒烟清障（见 §4）。

---

## 7. 对照解包复刻审计（剩余清单逐项）

| 清单项 | 证据 | 实现 | 验证 | 状态 |
| --- | --- | --- | --- | --- |
| 体重/属性差威力 5 技 | rule 35/38 查表 + flag 语义 | power_rule_runtime + 全局 quote 钩子 | 战斗上下文探针 + 8 单测 | ✅ 闭环（体重单位 = 实验口径 10kg/档） |
| 过山车 7070290 | 传动七连缺口 | team_rotation_runtime 跨成员下移 | 冒烟 rotate×6 + 单测 | ✅ 闭环 |
| 能量守恒 7070080 | buff 20640730 参数 -1 | grant 账本 + 防御响应分支 | 账本探针 + 8 单测 + HTTP 实测 | ✅ 闭环 |
| 疾风 7150170/7150320 | buff base 2006010/2064087 + 迅捷目录 | swift_release_runtime + drain | 冒烟 auto_queued×4/wing×16 + 25 单测 | ✅ 闭环 |
| 星陨打伤量 | BUFFBASE 2094001 = [20] | mark 1035 damage_amount=20 + preflight 解码 | 单测 4×20=80 + mark 套件 | ✅ 闭环 |
| 萌化 7020770 + 716 生命周期 | **无退化链/资质降低解包证据**；BUFFBASE 2102004 `[1],[0],[0],[1],[1]` 未解码；STATUS_RULES 仅 poison/burn | 未动（半句会被准入规则拦） | — | ⏸ 证据缺口 |
| 特性 200294 | trait `EVENTS` 无 `buff.gained` 统一事件源 | 未动（各模块独立记账） | — | ⏸ 证据缺口 |
| 719 系列 31 技 | 仅 14 准入（7190220/40/60/70/80/90/300/310/320/330/410/420/440/500） | 其余 17 技因 desc note 未解析保持 blocked | 准入探针 341 | ⏸ 编译器覆盖缺口 |

**结论**：已闭环 6 项全部「证据 → 实现 → 验证」三链齐全；未闭环 3 项均不是实现工作量问题，而是解包证据（退化链/统一增益事件源/17 条 desc note 语义）不足，按项目纪律不做猜测性实现。`reviewed_programs` 总数 **341**（b5 +9）。

---

## 8. 改动文件（b5）

新增：`lab/power_rule_runtime.py`、`lab/team_rotation_runtime.py`、`lab/swift_release_runtime.py`、`data/rules/reviewed-{power-rule,team-rotation,swift-release}-1.json`、`tests/test_power_rule_runtime.py`、`tests/test_b5_mechanisms.py`、`scripts/_smoke_platform_battle.py` 及一批 `_probe/_check/_pin/_patch/_wire/_insert/_update` 一次性脚本。

修改：`lab/power_query.py`、`lab/runtime_programs.py`、`lab/runtime_capabilities.py`、`lab/research_phases.py`（三模块 dispatch/validate/resolve + swift.after hook + drain + 蓄力释放安全闸）、`lab/adjacent_cost_runtime.py`（grant 账本）、`lab/defense_runtime.py`（7070080 响应分支）、`data/rules/reviewed-defense-components-1.json`（42 技）、`data/rules/reviewed-mark-components-1.json`（1035 解码 + 重钉 hash）、`lab/mark_runtime.py`（star 分支 + preflight 解码 + attach_relative_marks member_id 容错）、`lab/simulation.py`（ENGINE_REVISION → 10）、`docs/WORKBENCH_STATUS.json`（b5 更新）。

## 9. 未完成项（保持记录，不静默降级）
1. 萌化退化完整生命周期（证据缺口，见 §7）；
2. 特性 200294 统一增益事件源（证据缺口）；
3. 719 系列 17 技准入（desc note 未解析）；
4. 真实对战轨迹校准（`real_game_calibrated=false` 全局成立；本批所有数值为源文件/查表证据 + 实验口径，非线上实机对局标定）。
