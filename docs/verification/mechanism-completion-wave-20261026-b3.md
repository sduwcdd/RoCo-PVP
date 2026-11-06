# 机制推进批次 b3 — 排气 / 气沉丹田 / 轴承支撑 / 减压阀

日期：2026-10-26
引擎版本：`composable-battle-20261026-9`
快照：`20261025T013619+0800`（catalog sha256 `161e0aa10585ceac51ba1d5679ec14dcedb54be9a6311e9e80ed35034cd9c9f9`）

本批按接续文档“八、下一步重点”的顺序推进。**本批新增 4 个技能 + 3 个新机制模块**，第 5 项（疾风涡轮 / 疾风连袭）因缺少“额外释放派发”基础设施未实施，理由见第 5 节。

---

## 1. 排气 7070260 —— 出招威力压制（新模块 `lab/pressure_runtime.py`）

### 整句结构化
> 敌方获得威力-20，自己每受到1次抵抗伤害（不含连击），敌方额外获得威力-20，使用后重置。

### 证据链（全部来自客户端解析表，未用 BWIKI 文本猜数值）
| 环节 | 表 | 事实 |
| --- | --- | --- |
| 技能→buff | SKILL_CONF 7070260 | `skill_result` = effect 20190470（cast_moment 24）；`energy_cost` [2] |
| buff→base | BUFF/BUFFBASE | buff 20190470 → base 2019047 → `param[6]` = buff **20641380** |
| 施加 -20 | BUFFBASE 2064138 | `param[4]` = [20230750, 20230750] → 两份“技能威力-10”，合计 **-20** |
| 受击再加 | BUFFBASE 2064139 | `param[4]` = effect **1004116**，`param[5]` = 12（受击触发） |
| 再加的量 | EFFECT 1004116 | `param[1]` = 20641380 → 再次施加同一对 -10（再 **-20**） |
| 单层语义 | BUFF 20230750 | `desc` = “技能威力-10”，`add_max` = 99；“伤害降低 / 威力降低” |

### 实现
- `pressure_ledger`（挂在**被减益一方**）：`entries[]` 每项 `{kind: install|resisted, amount, turn, token}`，逐项按源码金额校验，`ledger_hash` 绑定。
- `pressure_listeners`（挂在**施法者**）：使用后装一枚 armed listener。
- 插入点：`lab/power_query.py` 在 `skill_history_power` 之后调用 `pressure_runtime.modify_power(attacker, power)`，floor 0。因此只影响“该成员出招的威力”，不影响防御减伤、不写死伤害公式。
- 回合线束：`research_phases` 增加 `pressure.install`（使用后）与 `pressure.received_attack`（每次攻击结算后）两个 post_hook，并在成员校验循环里加 `pressure_runtime.validate_member`。
- 白名单：`runtime_capabilities` 对 `pressure.plan` + `pressure_components` 放行。

### 策略与不确定
- 策略：`install` / `escalation`（一次攻击动作为一个包，连击同包只计一次）/ `reset`（用前重置为基础一对）/ `resisted`（属性倍率<1 且未无视抵抗）/ `persist`。
- 未确认：buff 2023075 的 `trigger_type=12` 是否与我这套“受击抵抗”判定完全等价；退场后是否保留。已写入 `installation_uncertainty` 与事件字段。

---

## 2. 气沉丹田 7140170 —— 自重置费用账本（新模块 `lab/response_cost_runtime.py`）

### 整句结构化
> 自己回复60%生命，获得物攻+130%，每次应对后本技能能耗-3，使用后能耗重置。

### 关键取值（必须读完整表）
简化表没有 `buff_group_level`。完整表 `artifacts/strength_buff_probe_20261025/mirror/versions/pakchunk4-WindowsNoEditor_2_P/SKILL_CONF.json` 中：

```
7140170.skill_result = [
  {effect_id: 1005060,  buff_group_level: 1 },   -> 回复
  {effect_id: 20010010, buff_group_level: 13}    -> 物攻 13 层
]
BUFF 20010010.desc = "物攻+10%"，add_max 99  => 1 层 = +10%，13 层 = +130%
energy_rule 9, energy_cost [10, -3, 1, 1]
```

### 实现
- 三个 operation：`hp.restore` 60%、`stat.modify` patk `{130,100}`、`response_cost.plan`（占位）。
- `response_cost_ledgers`：按技能记录 `entries[]` + `discount`（= -3 × 次数），哈希绑定。
- 插入点：`research_phases._resolved_cost` 中 `defense.conditional_cost` 之后 `value = response_cost_runtime.resolved_cost(state, side, skill_id, value)`，floor 0。
- 回合线束：`defense` 行动且 `successful` 时 `response_cost.record_response`；本技能使用后 `response_cost.consume` 清空账本。
- **HP 取整**：客户端表未给出百分比取整方式，模块显式声明 `HP_POLICY = {declared_max_hp, floor, clamp_to_declared_max}` 并写进每个事件（`hp_policy`、`hp_policy_uncertainty`），不伪装成游戏默认。

---

## 3. 轴承支撑 7070060 —— 相邻能耗光环 + 永久自减费（新模块 `lab/adjacent_cost_runtime.py`）

### 整句结构化
> 主动：本技能被动永久额外-1能耗，被动：两侧技能能耗-1，传动1。

### 取值与版本差异（重要）
| 来源 | energy_cost |
| --- | --- |
| 当前补丁解析表 SKILL_CONF | **6** |
| catalog `energy` | **6** |
| 较旧 mirror 完整表 | 3 |

采用 **6**（当前补丁 + catalog 一致），并把差异写入 `cost_version_note`。

### 实现
- `adjacent_cost_ledgers`：本技能每次成功使用永久 -1（可叠加，floor 0，`tokens` 去重）。
- 相邻光环：按**槽位序号相邻、不环绕**，边缘槽位只有实际存在的一侧邻居；`aura_sources` 只统计配置里复核过的源技能。
- 插入点：`_resolved_cost` 中 `response_cost_runtime.resolved_cost` 之后 `value = adjacent_cost_runtime.resolved_cost(state, side, skill_id, slot, value)`。
- 回合线束：`adjacent_cost.grow` post_hook；`transmission` 只作标签记录，不进任何公式。
- 边缘与环绕规则未在客户端表中出现 → 写入 `installation_uncertainty`，不推断环绕。

---

## 4. 减压阀 7070250 —— 相邻威力光环 + 永久自增威力（新模块 `lab/adjacent_power_aura_runtime.py`）

### 整句结构化
> 主动：本技能被动永久额外+20威力，被动：两侧技能威力+10，传动1。

### 实现
- `adjacent_power_ledgers`：自身每次使用永久 +20。
- 相邻光环：每侧 +10，同一套无环绕选择器。
- 插入点：`power_query` 在 `pressure_runtime.modify_power` 之后 `adjacent_power_aura_runtime.modify_power(attacker, power, context.get('selected_skill_slot'))`。
  - 没有 slot（无法归因）时**原样返回**，不猜位置。
- 回合线束：`adjacent_power.grow` post_hook。
- 未确认：威力加总在其它修正之间的先后顺序；光环在退场/换位后的保留。

---

## 5. 未实施项及原因（不是遗漏）

### 疾风涡轮 7150170
> 造成物伤，无法主动使用，在使用3次翼系技能后会自动使用此技能。

- 证据：`dam_para` [100]、`energy_cost` [0]；buff 20060110 → base 2006010 的 param 含 `[4]`、`[1]`、`[2006010]`、`[7150170]`（自动施放指向本技能）。
- **阻塞点**：需要“额外行动派发”——管线目前只按玩家提交的 action 逐个执行，没有子行动派发入口（审计里的 `whole_release_dispatch_gap`）。要正确实现必须在 `execute_research_turn_v2` 内新增一次真实二次释放（重新走预检/支付/结算/hook），属于跨模块改动，本批未做，避免在没有完整验证的情况下改坏主循环。

### 疾风连袭 7150320
> 释放自己释放过的迅捷技能，其能耗之和的二分之一加至本技能能耗，每次使用后能耗+1。

- 证据：`energy_rule` 6、`energy_cost` [0,0,1,-5000]；buff 20640870 → base 2064087 param 含 `[7]`、`[7150320]`、`[2]`、`[1]`、`[6]`；effect 1033003 param[0]=0、param[1]=2。
- **阻塞点**：① 依赖上面的额外释放派发；② 需要“迅捷技能释放历史”的重放选择器；③ 能耗 = 历史迅捷技能能耗之和 ÷ 2（取整未定）+ 每次使用 +1。取整与“和的一半”的分母在客户端表中无直接字段。

### 其余优先级
② 槽位传动七连的其余 6 个（7070030/7070070/7070080/7070170/7070270/7070290）、③ 特性 200294 增益事件边界、④ 萌化生命周期、⑤ 星陨/连击/复活/体重/属性差威力：本批未动。其中 7070070 与 7070250 同族但带“应对防御时 +30”分支，需要响应成功标志进入威力链，尚未做。

---

## 6. 验证结果

```
python -m unittest tests.test_pressure_runtime            -> 9 tests OK
python -m unittest tests.test_response_cost_runtime       -> 6 tests OK
python -m unittest tests.test_adjacent_cost_runtime       -> 8 tests OK
python -m unittest tests.test_adjacent_power_aura_runtime -> 6 tests OK
python -m unittest tests.test_research_phases tests.test_defense_runtime
   -> Ran 43 tests, 2 failures
      test_speed_terms_floor_then_tie_and_nonpositive_rejection   (期望 blocked，得 applied)
      test_uncompiled_charge_sets_up_but_does_not_fake_complete_release (期望 blocked，得 applied)
```

两个失败为**批次前既有失败**（b2 已记录，与本批无关；b2 曾把 cost 改动整段注释掉复跑仍失败）。

新增测试覆盖：整句结构与证据金额、清单/光环金额、floor 0、同 token 幂等（连击同包只计一次）、非抵抗与无视抵抗不触发、无 listener 不触发、重复使用重置、账本篡改拒绝、隔离预检、HP 策略写入事件。

---

## 7. 改动文件清单

新增：
- `data/rules/reviewed-pressure-1.json`（file sha256 `59740a72b6aa908a98810ab683d22c8c9d8437ec16e4a592787b5a94abd10ca8`）
- `data/rules/reviewed-response-cost-1.json`（`659f4549eee201d3a4e23b4041b8ea85bce176ddffab3d840adf229f44420efd`）
- `data/rules/reviewed-adjacent-cost-1.json`（`4e80c8ebbab35e1beacb3352a55ca4015e94cc1c66a3f52128a82d128871f764`）
- `data/rules/reviewed-adjacent-power-aura-1.json`（`92dcb54424cdcc6429ee6be736f59684c3101cbae642254977f485366088fde9`）
- `lab/pressure_runtime.py`、`lab/response_cost_runtime.py`、`lab/adjacent_cost_runtime.py`、`lab/adjacent_power_aura_runtime.py`
- `tests/test_pressure_runtime.py`、`tests/test_response_cost_runtime.py`、`tests/test_adjacent_cost_runtime.py`、`tests/test_adjacent_power_aura_runtime.py`
- `scripts/build_pressure_config.py`、`scripts/build_response_cost_config.py`、`scripts/build_adjacent_cost_config.py`、`scripts/build_adjacent_power_aura_config.py`
- `scripts/_wire_pressure.py`、`_wire_pressure2.py`、`_wire_pressure3.py`、`_wire_response_cost.py`、`_wire_adjacent_cost.py`、`_wire_adjacent_power_aura.py`、`_fix_pressure_test.py`（一次性补丁脚本，可删）

修改：
- `lab/power_query.py`（pressure + adjacent power aura 两个插入点）
- `lab/research_phases.py`（4 个模块的 import / context / validate / preflight / execute 分支 + 6 个 post_hook + `_resolved_cost` 两处）
- `lab/runtime_programs.py`（4 个模块并入 reviewed programs）
- `lab/runtime_capabilities.py`（4 个 op 白名单）
- `lab/simulation.py`（`ENGINE_REVISION` → `composable-battle-20261026-9`）
- `docs/WORKBENCH_STATUS.json`

---

## 8. 下一步（接续点）

1. **额外释放派发**：在 `execute_research_turn_v2` 加“队列化二次释放”，先只服务 7150170（自动使用、固定 3 次翼系技能计数），验证后再接 7150320 的迅捷历史重放。
2. 7070070 联动装置：同族相邻威力，加“响应成功 → +30”分支（`response_success` 进 `power_query` context）。
3. 7070080 能量守恒：减伤 80%（`defense_runtime` 已有减伤）+ 应对后相邻永久 -1（复用 `adjacent_cost_runtime` 的账本，但方向是给邻居而不是自己）。
4. 7070290 过山车：跨成员槽位旋转，需要“按槽位原主身份迁移”，不是整包交换。
5. 特性 200294：统一“实际获得增益”事件边界，作为萌化与增益类特性的公共前置。
