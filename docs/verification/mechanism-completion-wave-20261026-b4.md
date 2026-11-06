# 机制推进批次 b4 — 啮合传递 / 联动装置 / 相位移动（传动七连补齐 6/7）

日期：2026-10-27
引擎版本：`composable-battle-20261026-9`
快照：`20261025T013619+0800`

本批在 b3（排气、气沉丹田、轴承支撑、减压阀）基础上继续推进，新增 **3 个技能**、扩写 2 个既有机制模块、修改 1 个既有防御模块。

---

## 1. 啮合传递 7070170 —— 位置条件属性（新模块 `lab/slot_stat_runtime.py`）

### 整句
> 自己获得速度+30，本技能位于1号或3号位时额外获得物攻+80%，传动1。

### 证据
- `BUFF 20010100` = “速度+10”（`add_max` 99）→ +30 = 3 层；
- buff `20640740` / `20640750` 各带两个 base（`2064074`+`2064076` / `2064075`+`2064076`），对应两个位置分支；`21150010` 为被动载体；
- `energy_cost` [1]，`dam_para` [0]，`skill_dam_type` 19。

### 实现
- 程序 operations = 固定的 `stat.modify spd {30,100}` + `slot_stat.plan` 占位；
- `execute()` 在跑完固定 op 后，**按 `selected_skill_slot`** 决定是否追加 `stat.modify patk {80,100}`；
- 槽位未知时**不猜位置**，返回 `slot_stat.positional_skipped`（`reason=unknown_or_non_matching_slot`）；
- 索引约定：1号位 = slot 0，3号位 = slot 2（与相邻选择器同一套约定），写入 `installation_uncertainty`。

---

## 2. 联动装置 7070070 —— 相邻永久威力授予（扩写 `lab/adjacent_power_aura_runtime.py`）

### 整句
> 使用后两侧技能的威力永久+20，应对防御：变为威力永久+30。

### 证据
`skill_result` = effect 20640720（buff 载体）+ effect 1031131（type 2，`param[0]` = 子技能 7070071）。

### 实现
- 新增**按目标槽位**的授予账本 `adjacent_power_grants`：`{slot: {entries[], total, grant_hash}}`，每条 entry 记录来源技能、金额、回合、token；
- `grant()` 给两个直接相邻槽位各加 20；`response_success=True` 时加 30；每次使用叠加；同 token 幂等；
- `response_success` 必须是显式 bool，否则抛错（不默认 false 蒙过去）；
- `modify_power()` 现在把三类来源相加：自身成长 + 邻居授予 + 邻居光环，floor 0；
- 金额白名单校验：entry 金额必须是该来源复核过的 20 / 30 之一，否则视为篡改。

---

## 3. 相位移动 7070270 —— 位置条件减伤（修改 `lab/defense_runtime.py` + 防御配置）

### 整句
> 减伤50%，本技能位于1号位或3号位时，额外减伤40%，应对攻击，传动1。

### 实现
- `reviewed-defense-components-1.json` 新增 7070270 条目：`reduction {50,100}` + `reduction_slot_bonus {slots:[0,2], amount:40}` + `transmission 1`；防御技能数 40 → **41**；配置指纹 → `f3d76249f64e5dc45e47a0a644c11a7b78705deb08276a8c61afae22118243cc`。
- `defense_runtime.execute_defense_skill` 在既有的 `reduction_status_count` 之后新增 `reduction_slot_bonus` 分支：命中 slot 0/2 时把 40 加到减伤分子，**封顶 100**，并输出 `defense.slot_bonus` 事件（含 `slot`、`applied`、`reduction`、`policy`）；
- 未命中或槽位未知 → 只保留基础 50%，事件里 `applied=false`；
- 新增 `SLOT_BONUS_POLICY = "positional_reduction_added_at_activation_cap_100_experiment_v1"`。

---

## 4. 验证结果

```
tests.test_defense_runtime                    16 OK（含新增 test_phase_move_slot_bonus_only_from_source_positions）
tests.test_mesh_and_gearbox_runtime            11 OK
tests.test_adjacent_power_aura_runtime          6 OK
tests.test_adjacent_cost_runtime                8 OK
tests.test_pressure_runtime                     9 OK
tests.test_response_cost_runtime                6 OK
合跑 57 tests -> OK
```

定向准入探针（`scripts/_check_b4_admission.py`）：

```
7070260 7070170... 逐个 supported=true, blockers=[]
reviewed_total 332（b3 结束时 329，本批 +3）
```

`tests.test_research_phases` 的两个既有失败本批未复跑（改动不涉及该模块的执行分支，只加了 3 个 post_hook 与 2 个分派分支；上一次复跑仍只这两个失败）。

---

## 5. 传动七连现状（7 个里 6 个已准入）

| 技能 | 状态 | 说明 |
| --- | --- | --- |
| 7070030 钢钻 | ✅ 既有 | `reviewed-adjacent-power-1.json` 已含，`dam_para [0,1,33]` = 两侧威力和的 1/3 |
| 7070060 轴承支撑 | ✅ b3 | 相邻能耗 -1 + 永久自减 1 |
| 7070070 联动装置 | ✅ b4 | 相邻永久 +20 / 应对防御 +30 |
| 7070080 能量守恒 | ❌ | 减伤 80%（防御侧已有）+ **应对后两侧技能永久 -1 能耗**：需要“防御结算 → 相邻槽位费用授予”的跨模块钩子，本批未做 |
| 7070170 啮合传递 | ✅ b4 | 速度 +30；1/3 号位物攻 +80% |
| 7070250 减压阀 | ✅ b3 | 相邻威力 +10 + 永久自增 20 |
| 7070270 相位移动 | ✅ b4 | 50% + 1/3 号位额外 40% |
| 7070290 过山车 | ❌ | 全队**跨精灵**向下移动 1 位，需要“按槽位原主身份迁移”，不是整包交换；现有 `slot_runtime` 只支持同成员相邻交换与整包交换 |

---

## 6. 仍未完成项与具体缺口（不是没时间，是缺证据或缺基础设施）

1. **疾风涡轮 7150170 / 疾风连袭 7150320**：缺 `execute_research_turn_v2` 的队列化二次释放。b3 已说明；本批未动。
2. **特性 200294“实际获得增益”事件边界**：需要一个统一的“增益实际生效”事件源，目前各模块各自记录（`modifier_ledger.register_stat`、`status_runtime`、`adjacent_power_grants`），没有单一权威入口。
3. **萌化（7020770 退化 + 716 系列 12 技能）**：只做“获得 1 层萌化”会把整句生命周期切成半句，违反本项目准入规则；`status_runtime.STATUS_RULES` 里目前没有萌化的完整规则证据。
4. **星陨系（719 系列 10+）**：`raw parameter 20` 的单位与公式仍未解码。
5. **体重/属性差威力（7160150 砂糖弹球、7020990 吨位压制、7021000 以重制重、7150250 闪击、7080320 鸣沙陷阱）**：本批已把原始参数拉出来，形态是**查表**而非线性公式：
   - `damage_rule 35`：`7160150 dam_para [0,20,40,60,80,100,120,0]`、`7020990 [0,160,140,120,100,90,80,1]`、`7021000 [0,80,90,100,120,140,160,1]`
   - `damage_rule 38`：`7150250 [60,6,0,20,40,60,80,90,100,110,120,130,140]`、`7080320 [60,4,0,20,...]`
   看起来是“首元素基数 + 步长 + 分段威力表”，但**体重字段（或速度/物防差）的单位与分段边界没有客户端证据**，且 catalog 里没有可直接用的体重数值。按纪律不猜，标记为待解码。

---

## 7. 改动文件（b4）

新增：
- `lab/slot_stat_runtime.py`
- `data/rules/reviewed-slot-stat-1.json`（sha256 `53e99a2d97788d79571c0ee97c221c2aec1b93d9704bbedb104d5e2138b10687`）
- `tests/test_mesh_and_gearbox_runtime.py`
- `scripts/build_wave_b4_configs.py`、`scripts/build_phase_move_config.py`、`scripts/_prep_b4_modules.py`、`scripts/_wire_b4.py`、`scripts/_add_phase_move_test.py`、`scripts/_fix_phase_move_test.py`、`scripts/_check_b4_admission.py`、`scripts/_dump_backlog.py`、`scripts/_probe_*.py`（一次性脚本）

修改：
- `data/rules/reviewed-adjacent-power-aura-1.json`（新增 7070070；sha256 `5aa1cb8accc25d2969d7bdfb0c70820723a5d7913c0edf5b5059003b9705fa72`）
- `lab/adjacent_power_aura_runtime.py`（邻居授予账本 + 三类来源相加 + 金额白名单）
- `data/rules/reviewed-defense-components-1.json`（新增 7070270，41 个）
- `lab/defense_runtime.py`（`reduction_slot_bonus` 分支 + `SLOT_BONUS_POLICY` + 新 CONFIG_HASH）
- `tests/test_defense_runtime.py`（新增相位移动测试）
- `lab/runtime_programs.py`、`lab/runtime_capabilities.py`、`lab/research_phases.py`（slot_stat 接入 + 三个新 post_hook）
