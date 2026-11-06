# 本轮验收：数据对拍结论 · 天梯使用率接入 · rkpp 实时抓包

日期 2026-10-28。三项内容对应你这次提的 1 / 2 / 3。

## 1. 数据不一致的裁定与修正

### 1.1 六维种族值：以 BWIKI 为准，不改

你确认图鉴值正确、解包是滞后补丁。我方 `catalog` 本来就用 BWIKI 快照，因此
**3663 量风碗 / 3773 幽铃 一行未动**，当前值固定为：

| 形态 | 生命 | 物攻 | 魔攻 | 物防 | 魔防 | 速度 |
|---|---|---|---|---|---|---|
| 3663 量风碗 | 85 | 84 | 83 | 98 | 72 | 96 |
| 3773 幽铃 | 113 | 44 | 104 | 88 | 115 | 76 |

`scripts/verify_external_data.py` 仍会把这 10 项列为"与解包不一致"——这是**预期**，
表示解包侧落后，不代表我方有错。差异报告的结论栏已按此写明。

### 1.2 连击段数：三条按描述，已改

`lab/skill_hits.py` 原来把"自己获得…／敌方获得…"当作条件子句而提前退出，导致这三条被判成 1 段。现按你的裁定改为读描述里的段数：

| 技能 | 描述 | 旧 | 新 |
|---|---|---|---|
| 7021080 三连破 | 自己获得物攻+30%，3连击。 | 1 | **3** |
| 7110410 电离爆破 | 敌方获得魔攻-20%，速度-20，2连击。 | 1 | **2** |
| 7160390 耍赖 | 自己获得双攻永久+10%，2连击。（有减益时+1） | 1 | **2** |

改动只放宽了两个子句标记（"自己获得""敌方获得"）与"永久"，其余条件标记（应对、若、每次、使用后、队伍中、改为、每携带、每受、时连击）保留，"连击数"与"不含连击"仍被排除。全量重跑后**只有这 3 条变化**，其余保持 1 段。

验证：`scripts/verify_external_data.py` 的连击项从 `match 51 / differ 3` 变为 **`match 54 / differ 0`**。

注意：三条都是状态技（无威力），段数变化不改变伤害；耍赖的"有减益时+1"仍属条件，不进基础段数。

### 1.3 七个形态：按你说的不管

3872–3878（公平鸽/奔波鼠/流浪鼠/花怨鳗/鳗尾兽/稻草人/稻草守护者）是解包未收录、外观微调，
不改种族值、不做特殊处理。

## 2. 天梯使用率：已接入工作台与 RL

### 2.1 数据与口径

`data/external/pokedex_pvp_usage.json`：865 条目录、616 只有数据，四维（性格/个体/血脉/技能）各 772 条观测。
`metadata` 自带 `source_endpoint=wegame.shallow.ink/.../pet/stat`、`collected_at=2026-09-28T19:52:13.196Z`、`mode=pvp`、`team_type=2`。

口径写进代码与接口，避免被当成别的东西：

- `population_statistics: true` —— 这是真实玩家人群快照，不是人工候选。
- `joint_distribution: false` —— 只有单维占比，没有性格×技能交叉表，**不得相乘当成联合概率**。
- 元素里的 `percent` 是"该维度内占比"，不是"对手携带概率"。

### 2.2 新模块 `lab/usage_prior.py`

| 方法 | 作用 |
|---|---|
| `find(q, limit)` | 按名字/编号搜精灵，返回热度摘要（Top 性格/技能/血脉） |
| `build(base_id, form_id, catalog)` | 给出该形态的"最常用配置"：首位性格（含 up/down 与是否与性格表匹配）、个体前三项、首位血脉（映射到 0–19 编号，不可映射则置空并说明）、四招 |
| `prior_candidates(...)` | 显式候选：按性格 TopN，`prior` = 该性格占比，六维资质齐全 |
| `roster_member / roster` | 直接产出 `lab.rl_battle_env` 可用的队伍记录 |
| `provenance()` | 出处与时间，供界面标注 |

关键约束（都写了测试）：

- **技能必须在该形态学习池内**。天梯里排得高但学不会的技能（喵喵的"荆棘爪"等 14 条）进入 `skipped` 并注明原因，**不会用低排名技能顶替**。
- 个体只取前三项并填 10，其余保持 `None`（"未知"），不填零冒充已知。
- 血脉"奇异""污染"不在 19 个可选血脉内，置空并给 `bloodline_note`。
- 无数据精灵（如 3009 赤毛鸡仔 `no_data`）直接抛错，不生成伪造配置。

### 2.3 接口

| 接口 | 返回 |
|---|---|
| `GET /api/usage/pets?q=&limit=` | `{provenance, pets:[{base_id,name,data_status,top_nature,top_skill,top_bloodline}]}` |
| `GET /api/usage/pet?id=&form=` | 完整 `build`（含 `moves_detail`、`skipped`） |
| `GET /api/usage/team?ids=3001,3002` | 批量 `builds` + 逐只 `errors` |

### 2.4 工作台

编辑器里新增 **"按天梯填充"** 按钮（`#apply-ladder`，位于精灵概要下方）：

- 点一下把性格、增减方向、血脉、个体三选六、四招填进编辑框，并显示"天梯快照（2026-09-28）· 性格 踏实 62.86% · 血脉 草 88.66% · 个体 生命/物攻/物防 · 技能 …"。
- **不自动保存**，仍要点"保存到阵容"；填完 `hp_constraint` 会被清空，避免旧的减血约束卡住新配置。
- 找不到数据时明确报"天梯快照里没有这只精灵"，不填半套。

### 2.5 RL 先验

`roster_member` 产出的记录形如：

```json
{"form_id": 3001, "nature_id": 30, "move_ids": [7030200, 7030220, 7020780, 7020390],
 "talent_selection": {"selected": ["hp","patk","pdef"], "values": {"hp":10,"patk":10,"pdef":10}},
 "team_code": {"raw_markers": [79, 80, 82]},
 "usage_provenance": {"base_id": 3001, "source_endpoint": "...", "collected_at": "..."}}
```

`BeliefFilter` 的 schema 与 `prediction_source`（只允许 id + snapshot_id）**一行未改**；先验在环境侧以显式 `prior` 传入，不伪装成联合分布。

冒烟：`scripts/smoke_rl_usage.py` 用天梯阵容构造 `RLBattleEnv`（3001/3002/3003 对 3004/3005/3006），`reset(seed=7)` 成功，A 侧 `observe` + `legal_actions` 返回 7 个合法动作。详见第 4 节"已知问题"，B 侧在同一次冒烟里暴露了一个与 usage 无关的引擎缺口。

## 3. rkpp 实时抓包

见 [`docs/RKPP_LIVE.md`](RKPP_LIVE.md)。要点：

- 已把 `E:\洛克PVP助手\app\rkpp` 原样复制到 `vendor/rkpp`（17 py + 2 md + sqlite），保留 RocoMITMServer 版权声明，未改一行。
- 依赖装好：scapy 2.8.0 / pycryptodome 3.24.1 / protobuf 6.33.6 / msgpack 1.2.4；`--list-ifaces` 能看到 `WLAN`。
- 实跑 `opencode-server`：`[relay] listening url=http://127.0.0.1:8765`，`/health` 200、`/latest` 200 `[]`。
- 本工程新增 `lab/live_bridge.py` + `GET /api/live/status` + `GET /api/live/events` + 工作台「实时抓包」面板（3 秒轮询，可复制启动命令）。
- **必须以管理员运行**：本轮进程 `is_admin: false`，抓包回调停在 `waiting for capture-ready callback`，只能拿到 0 事件。中继本身能起、能被本工程识别（`relay_available: true`）。

## 4. RL 冒烟（不训练）

`scripts/smoke_rl_usage.py`：天梯阵容 3001/3002/3003 对 3004/3005/3006，`reset(seed=7)`，
双方 `observe()` + `legal_actions()`：

```
side a: active=3001 hp=100% energy=10 legal_actions=7
side b: active=3004 hp=100% energy=10 legal_actions=6
identity engine_hash: 504fa4e25ca92598
SMOKE OK
```

第一次跑时 B 侧抛 `Cannot quote own skill 7110200 slot 3: First-action cost requires owned entry action count`。
根因是开局首发成员没有 `mark_entry_actions`，而 `mechanism_runtime.cost` 的 `cost.current` 分支要求它是 int。

**修法与放弃的方案**：

- 先尝试在 `start_simulation` 给所有成员补 `mark_entry_actions = 0`。这会破坏两条既有断言
  （`test_unknown_star_dependency_blocks_before_damage_or_any_commit`、
  `test_unknown_star_blocks_before_swift_damage_callback`）：星标记把"字段缺失"当作"依赖未知 → 阻断"，
  补 0 之后变成"已知 → 放行"。**已回滚。**
- 最终只在 `lab/rl_battle_env._costs` 的**报价副本**上给"己方在场成员"补 0：
  查询用的是 `deepcopy`，真实状态不变；替补成员仍保持缺失，星标记的阻断语义不受影响。
  该副本语义等于"本回合首次行动"，与开局真实对局一致。

验证：`tests.test_rl_battle_env.ReviewRegressionTests` 5/5（含 `test_dynamic_cost_uses_execution_chain_and_public_quote`），
`ObservationTests` + `LegalActionGateTests` 见 `artifacts\_rl_obs_legal.txt`。

## 5. 已知的既有失败（与本轮改动无关）

`tests/test_mark_integration.py::test_unknown_star_dependency_blocks_before_damage_or_any_commit`
与 `tests/test_mark_switch.py::test_unknown_star_blocks_before_swift_damage_callback`
在当前代码上得到 `applied`，断言期望 `blocked`。

- 两条都只走 `build_research_context_v2` / `execute_research_turn_v2`（见测试源码 41–45 行），
  不经过 `start_simulation`，也不经过 `rl_battle_env`，因此不是本轮改动引入。
- 影响：使用 1035 星标记、而 `mark_entry_actions` 未知时，引擎当前会放行而不是阻断。
  属星标记依赖判定的既有缺口，待单独处理（本轮未改，避免在数据/接入批次里混入规则语义变更）。

## 6. 复跑清单

```
python -m unittest tests.test_usage_prior -v          # 8/8
python -m unittest tests.test_live_bridge -v          # 7/7
python scripts/verify_external_data.py                # 连击 match 54 / differ 0
python scripts/report_external_diffs.py               # 差异报告（已带裁定结论）
python scripts/smoke_rl_usage.py                      # SMOKE OK
node --test tests\test_buff_preview_ui.js tests\test_simulation_ui.js tests\test_team_code_ui.js `
  tests\test_damage_preview_ui.js tests\test_workbench_ui.js tests\test_battle_render_ui.js   # 30/30
node --test tests\test_battle_mechanics.js tests\test_battle_team_code.js `
  tests\test_hud_render.js tests\test_weather_ui.js                                          # 84/84
```

Python 回归批次（76 项，`artifacts\_py_tests_all2.txt`）：74 通过，2 为上节既有失败。

## 7. 端口与入口

- 工作台：`python -m lab.server --port 8766` → `http://127.0.0.1:8766/battle`
- 抓包中继（管理员）：见 RKPP_LIVE.md 的启动命令
- HUD：`http://127.0.0.1:8766/hud`
