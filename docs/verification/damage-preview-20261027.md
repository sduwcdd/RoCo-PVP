# 技能结果预估（裸伤害）交付与验收 — 2026-10-27

工程根：`D:\Users\86195\Desktop\workspace\roco_pvp`
服务：`python -m lab.server --port 8766` → `http://127.0.0.1:8766/battle`
引擎修订：`composable-battle-20261027-12`；快照 `20261025T013619+0800`（633 形态 / 579 技能 / 246 特性）

## 1. 需求与边界

新增一块「技能结果预估」，位置固定在「下一步，怎样选择？」卡片下方、「记下这一回合」上方。

- 前提：双方在场精灵的形态、性格（增减方向）、三项个体已确定。
- 输出：每个已携带技能槽的**逐段裸伤害与合计**，以及对方剩余生命与百分比。
- 明确不计入：对方换人、对方使用防御技能、聚能、应对成功增伤、天气、印记、**未在「本回合状态修正」里填写的状态层**、特性、核心魔法、暴击与随机浮动。
- 防御减伤与「应对成功增伤」由用户自己口算乘算，工具只给裸伤害。
- 模型建议部分不在本次范围（策略模型尚未训练，仍显示「尚未训练」）。

## 2. 公式取证（回答「减伤是不是乘 (1−80%)、增伤是不是乘 (1+50%)」）

结论全部来自仓库内真实实现，不是推测。

### 2.1 防御减伤：是「先乘后取整」，等价 ×(1−n/100) 再向下取整

`lab/defense_runtime.py:376`

```
damage = raw_damage * (100 - numerator) // 100
```

- `numerator` 是**减伤百分点（0–100 的整数）**，例如「减伤 80%」即 `n=80`。
- 作用对象是**最终伤害**（在生命裁剪之前），先相乘再整除，等价于 `raw * 0.2` 后向下取整。
- 所以「在当前估计结果基础上乘 (1−80%)」成立，但**取整顺序必须是先乘后 floor**；若先对 raw 取整再乘，边界值会差 1。

### 2.2 增伤：分两条通道，多数技能走「威力」通道，不能直接乘最终伤害

1. **威力倍率通道（绝大多数）**：技能文本写的是「本次技能威力变为 3 倍 / 4 倍 / 威力 +50% / 威力 +100」。
   威力 `P` 进入 `numerator = round(A × P × M × 37/41)`、`damage = floor(numerator / D)` 的乘性链（`lab/numeric_candidates.py:163`，`M = 属性倍率 × 本系倍率`）。
   正解：**先把威力乘上倍率，再整条重算**。直接对最终伤害乘 1.5 会因为 `round` 与 `floor` 的边界给出不同整数，不能等同。
2. **真实伤害倍率通道（少量）**：`lab/research_damage.py:217`
   `final_unclipped = floor(nominal * conditional * trait_multiplier)`，其中 `conditional` 来自 `params.damage_multiplier`（如印记 `damage_ratio`）。
   这一条才是「对伤害乘 ×(1+50%)」的形式，同样乘完必须 `floor`。

措辞证据（`artifacts/_response_power_probe.txt`）：579 技能里筛出 40 条「应对 + 威力/伤害」描述，其中 **34 条提「威力」、7 条提「伤害」**（典型：嗜痛「减伤 80%」、突袭「应对状态：本次技能威力变为 3 倍」、闪燃「4 倍」、暖气「减伤 70%…威力 +50」）。
规则侧证据：`data/rules/reviewed-choice-components-1.json` 的 `power_factor_on_response: 2`（应对成功威力 ×2）、`reviewed-action-fields-1.json` 的 `opponent_cost_power_factor: 10`。

### 2.3 面板与属性倍率

- 面板式 `lab/numeric_candidates.py:108`（`arena_stat60`）：`growth = f32(base*0.01) + raw_iv*0.005`，`core = jsRound(f32(170*growth+70))`（生命）/ `jsRound(f32(110*growth+10))`（其余），`value = jsRound(core*mult + bonus)`，`bonus` 生命 100、其余 50；`raw_iv = 显示个体 × 6`。
- 属性倍率用 `BwikiRuleset.type_multiplier` 的显式「防守方属性组合表」；表缺失时该槽进入 `blocked_slots`，**不按无克制处理**。
- 本系加成：技能属性 ∈ 精灵属性时 ×1.5（`same_type_multiplier`，可在 settings 覆盖）。
- 核心魔法的威力比例（`lab/power_query.py:51` 只允许 1 或 5/2）**不引入**本预估。

## 3. 实现

### 3.1 后端 `lab/damage_preview.py`（新模块）

`preview_damage(catalog, payload)`：

- 先复用 `lab/simulation.prepare_simulation` 生成 state，因此面板、性格、三选六、HP 公式、初始能量与引擎完全同源。
- 逐槽输出：`slot / skill_id / name / type / kind / power / energy_cost / affordable / attack_stat / attack_panel / attack_panel_base / attack_stat_modifier_percent / defense_stat / defense_panel / defense_panel_base / defense_stat_modifier_percent / type_multiplier{numerator,denominator} / same_type_bonus / combined_multiplier / hit_count / hit_count_source / power_basis / per_hit_power / per_hit_damage / hits_detail / hits_executed / damage（名义合计）/ applied_damage / damage_percent_of_max / lethal / defender_hp_before / defender_hp_after / defender_hp_after_percent / formula_trace / candidate_id`。
- 变化技能与未登记威力 → `non_damage_slots`；克制表不可用 → `blocked_slots`（附原因，不静默跳过）。
- 顶层：`attacker / defender`（member_id、slot_index、form_id、name、types、hp、max_hp、energy、max_energy、stats、setup_notes）、`stat_terms`（规范化后的百分比项）、`warnings`、`excluded_effects`（10 条）、`policy`（含 `expression` 与 `defense_mitigation`）、`calibrated:false`、`training_eligible:false`、`snapshot_id`、`catalog_content_hash`。
- 入参：`teams{my,opponent}`、可选 `settings`（走 `simulation.settings` 校验）、`side`（"a"/"b"）、`active_slot{a,b}`（**索引**，不是 member_id）、`hp{a,b}`、`hp_percent{a,b}`、`stat_terms{a,b}{patk|matk|pdef|mdef|speed: 数字或数字数组}`。
- `hp_percent` 语义：>0 时最少 1 点生命（`max(1, ceil(max_hp*pct/100))`），=0 → 0；同一方同时给 `hp` 与 `hp_percent` 直接报错。

### 3.2 服务端 `lab/server.py`

`import_request` 新增 `/api/preview/damage` 分支，`do_POST` 的路径白名单同步加入（缺一即 404）。

### 3.3 前端

- `web/battle_workspace.html`：在 advice 卡与 `record-panel` 之间插入 `#preview-panel`（含 `#preview-badge` / `#preview-matchup` / `#preview-stats` / `#preview-content`）与 `.preview-*` 样式；桌面 `.center-column` 栅格由三行改为四行 `max-content max-content max-content minmax(85px,1fr)`，否则历史面板会把新卡挤没。
- `web/battle.js`：新增 `PREVIEW_SETTINGS`、`previewToken`、`previewLastBody`、`previewActiveIds`、`previewActiveSlots`、`previewStatNumber`、`previewStatTerms`、`previewPayload`、`previewPanel`、`previewPercent`、`previewRow`、`previewOtherRow`、`refreshPreview`；`render()` 末尾 `refreshAdvice();refreshPreview();`；`bind()` 末把 4 个状态修正输入绑到 `refreshPreview`。
- 去重：请求体指纹与上次相同则直接复用渲染结果，避免每次 render 都打后端；失败时清空指纹以便重试。
- 显示：`hit_count>1` 追加「N 连击」与「（N × 每段 M）」；填了状态修正时追加「攻面板 207→414 / 守面板 114→79.8」。

## 4. 验证

### 4.1 Python（`python -m unittest tests.test_damage_preview -v`）

**14 项通过，80.7 s**（`artifacts/_py_preview_multihit.txt`）。除 §4.1 早期的 9 项外，本批新增 5 项：
- `test_multi_hit_sequence_matches_engine_settlement`：同一配置下 `prepare_simulation → start_simulation → act_simulation` 的实际结算事件，与预估逐段对拍（段数 3、每段 19、总 57、终血 275 完全一致）。
- `test_hit_count_parser_ignores_conditional_clauses`：`base_hits` 对 6 个代表技能的段数判定（旋转突击 3、追打 1、反击拳 2、震击 1、微型斥候 1、乱打 5）。
- `test_stat_terms_scale_the_panel_linearly`：`{patk:[50,50]}` 必须得到面板 ×2（线性相加，不是 50%×50% 相乘），伤害按新面板重算。
- `test_defense_debuff_lowers_the_defender_panel`：`{pdef:[-30]}` → 守方面板 ×0.7、伤害上升。
- `test_stat_terms_reject_bad_input`：未知阵营 / 未知属性 / 字符串 / 超范围 / 来源过多 / 压到 0 面板，全部报错。

### 4.2 JavaScript（`node --test tests/test_battle_mechanics.js tests/test_battle_team_code.js tests/test_simulation_ui.js tests/test_weather_ui.js`）

**108 / 108 pass**，0 fail，584.7 ms（`artifacts/_js_tests_multihit.txt`、`artifacts/_js_one_fail.txt` 为修前记录）。本批新增 2 条渲染用例：
- 「the preview panel renders the per-hit split of a multi-hit skill」：断言面板文案含 `3 连击`、`→ 伤害 57`、`3 × 每段 19`、`对方剩 275/332`，徽章为 `裸伤害 · 未校准`。
- 「the preview forwards the manual stat terms and shows the scaled panel」：填入 `100` 后请求体带 `stat_terms:{a:{patk:100}}`、行内显示 `攻面板 207→414`；只发已填写的字段（空侧不下发）。

### 4.3 真实 HTTP

- `scripts/_http_preview_check.py`（早期）：`/api/status` 200、`/api/preview/damage` 200；突袭 58、偷袭 95、`hp_percent{b:1}` → 4/332、越界与空队 400。
- `scripts/_http_multihit_check.py`（本批，exit=0）：旋转突击 3 段每段 19 合计 57 → 275；能量炮 2 段每段 22 合计 44 → 288；刺藤 2 段每段 36 合计 72 → 260。
- `scripts/_http_stat_terms_check.py`（本批，exit=0）：
  - 基线 旋转突击 面板 207 → 伤害 57；
  - `stat_terms{a:{patk:[50,50]}}` → 面板 **414.0**（Σ 100%）、伤害 **114**（恰为 2 倍）；
  - `stat_terms{b:{pdef:[-30]}}` → 守方面板 114 → **79.8**、伤害 57 → **81**；
  - `stat_terms{a:{luck:10}}` → 400「状态修正含未知属性」。


### 4.4 真实浏览器（页面自动化实机验证）

在运行中的服务上，用页面自动化（`bu`）走完整用户流程：添加我方迪莫（性格 物攻↑/魔防↓，个体 生命10/物攻10/速度10 → 生命 425）→ 添加对方喵喵（性格 魔攻↑/魔防↓，同样三项个体 → 生命 332）→ 在「记录这一回合」两侧选定在场精灵 → 观察预估卡：

- 卡片位置：紧接「下一步，怎样选择？」下方、在「记下这一回合」之上，三列栅格与历史面板均未被挤压。
- 徽章：`裸伤害 · 未校准`。
- 双方行：`我方 迪莫 425/425 · 能量 10/10 → 对方 喵喵 332/332`。
- 槽1 猛烈撞击（普通·物伤·威力 65·能耗 1）→ **伤害 106**，226/332（68.1%）。
- 槽2 闪光（光系·魔伤·威力 60·能耗 1）→ **伤害 37**，295/332（88.9%），标注「克制 1/2 · 本系 ×1.5」。
- 槽3 防御（普通·变化）→ 该行显示「本预估只覆盖直接伤害技能」，不进伤害列表。
- 两次攻击分别走物攻/魔攻与物防/魔防两条面板，物理 106 与魔法 37 各自与「威力×面板×倍率」链一致（`12142/115 ≈ 105.6 → 106`；`6009/160 ≈ 37.6 → 37`）。
- 底部固定说明含「伤害×(100−减伤)÷100 向下取整」与「应对成功增伤请先把威力乘上倍率再重算」。
- **注意**：这张截图（`artifacts/preview_panel_20261027.png`）是**连击修复与状态修正之前**的界面，不含「N 连击」标注与 4 个修正输入。本批的界面验证改由 JS 渲染用例承担（§4.2 两条），实机重截图未完成。

## 4.5 界面验证方式说明（诚实披露）

本批尝试重新打开 Chrome 做实机目视，`bu`（页面自动化）多次调用只返回 `Computer-use Python code completed.` 而无任何 DOM/截图输出（会话失联），`cu`（桌面）侧 Chrome 窗口处于空白全屏且 F11/Ctrl+L 无响应，最终未能取到「N 连击」与状态修正输入的实机截图。因此这两项**只有 mock DOM 渲染用例 + 真实 HTTP + 引擎对拍**三层证据，没有浏览器像素级截图。功能可用性不受影响（Node 用例执行的是 `web/battle.js` 的真实 `refreshPreview`/`previewRow`）。

## 5. 已知简化（已在界面与返回中声明，不算缺陷）

- 多段技能**逐段取整后求和**；段数取自技能描述解析（579 技能中 42 条直接伤害技能可解出基础段数：1段 8、2段 20、3段 11、4段 1、5段 2），**未与游戏文件核对**；描述里「应对成功改变段数」「位置连击+1」等条件加成不计。
- 只对攻方在场精灵出结果；守方视角需另传 `side:"b"`。
- 不含天气/印记/未填写的状态层/特性/核心魔法/暴击，也不含防御减伤与应对增伤（用户口径：自己口算）。
- 状态修正只算你手动填入的面板百分比（见 §7），不做技能名到 buff 的自动推断。
- `calibrated:false`、`training_eligible:false`：这是预估值，不是校准后的真实伤害，不得作为训练真值。

## 6. 仍未做

- 引擎侧 `104002/104007` 推进结算仍未接入 `lab/simulation.py`（仅 104001/104003/104004 初始化 `core_magic_runtime`）。
- 愿力冲击 19 个系别变体归属未解析。
- 迪莫「进化同时替换首槽」仍是 `verified:false` 的用户口径。
- RL 正式训练仍被 `lab/rl_contract.py` 校准门禁锁定（本轮只做环境/接口 smoke，未启动训练）。

## 7. 本批追加一：连击（多段）修复

### 7.1 引擎口径取证

- `lab/effect_runtime.py` 的 `damage.sequence` 按 `params["hits"]` 逐段调用解析器，**逐段独立取整**后累加；一方力竭即停。
- `lab/research_damage.py:181-192`：`power_basis == "source_power_total"`（默认）时 `power = power / hit_count`，即**每段威力 = 总威力 ÷ 段数**。
- 实证（`scripts/_dbg_engine_vs_preview.py`，`artifacts/_engine_vs_preview.txt`）：迪莫 旋转突击（威力 35、3 连击）打喵喵，引擎事件为 `(19,0,3) (19,1,3) (19,2,3)`，合计 57，HP 332→275；预估 `hit_count 3 / per_hit_power 11.667 / per_hit_damage 19 / damage 57 / defender_hp_after 275` —— 逐段完全一致。

### 7.2 实现

- 新增 `lab/skill_hits.py`：`base_hits(catalog, skill_id) -> (hits, source)`。按 `，,。；;\n` 切句；含「不含连击」「连击数」的句子跳过；遇「应对 / 若 / 每次 / 使用后 / 队伍中 / 敌方获得 / 自己获得 / 改为 / 永久 / 每携带 / 每受 / 时连击」等条件标记即停止向后找；否则取第一个 `(\d+)\s*连击`。返回 `wiki_desc_parsed` 或 `single_hit_default`。
- `lab/damage_preview.py`：逐槽改为**循环逐段结算**（`per_hit_power = power/hits`，`applied = min(remaining, nominal)`，`remaining<=0` 提前 break），新增返回字段 `hit_count / hit_count_source / power_basis / per_hit_power / per_hit_damage / hits_detail[{index,power,nominal_damage,applied,defender_hp_after}] / hits_executed / applied_damage`；`damage` 为**名义总伤害**，`applied_damage` 为实际扣血，`lethal` 与 `defender_hp_after` 基于 applied。
- `web/battle.js` 的 `previewRow`：`hit_count>1` 时元信息追加「N 连击」，伤害后附「（N × 每段 M）」。

### 7.3 未核对项（诚实声明）

- 段数来源是技能描述，`data/rules/reviewed-mechanism-components-1.json` 中没有可用的 `base_hits` 列（检索命中 0），因此**没有**游戏文件级证据；界面与返回文案都写明「未与游戏文件核对」。
- 8 条条件型描述（追打 / 散手 / 反击拳 / 疾风刺 / 震击 / 虫鸣 / 微型斥候 / 绞轮）已确认降级为静态段数，不参与条件加成。

## 8. 本批追加二：状态修正（回答「这一版能算状态栏吗」）

### 8.1 答案

- **改之前：不能。** 面板只含性格、个体与血脉，状态层一律列为排除项。
- **现在：能算你已经知道的那部分。** 面板顶部新增 4 个输入：我方物攻 %、我方魔攻 %、对方物防 %、对方魔防 %；填入本回合已生效的百分比即可进伤害链，未填项一律不推断。

### 8.2 口径（与引擎同一式，不是自创）

- 引擎 `lab/research_damage.py:113-121`：`terms = stat_modifiers[stat] + stat_terms(...)`，`effective = base_panel * (1 + Σ terms)`，trace 字段写死 `stat_modifier_application: "base_panel * (1 + sum(signed rational terms))"`，策略名 `linear_signed_terms_experiment` —— **线性相加，不是逐层相乘**。
- 预估实现：`有效面板 = 基础面板 × (1 + Σ填入百分比)`，用 `Fraction` 精确求和后转 float，再进 `round(A×P×M×37/41) → floor(/D)`。
- 例：力量增效满层（`data/skills_all.csv` 记「自己获得物攻+100%」；解包 `reviewed-modifier-source-units-1.json` 记 `units.patk = [10,100]`、`add_max 99`，即每层 +10%）→ 我方物攻填 `100` 即可，面板 207→414，旋转突击 57→114。
- 多个来源相加：`[50, 50]` → Σ100 → ×2（若按相乘会得 ×2.25，属错误口径，已有测试守住）。

### 8.3 仍不计入

- 灼烧 / 中毒 / 寄生等按层结算的**持续伤害**（这是另一个回合末结算通道，不是面板修正）。
- 印记、特性、天气、核心魔法、暴击、防御减伤、应对增伤。
- 技能名 → buff 的自动推断：解包数据里只有 91/579 技能带 BUFF 单位，其余靠文本描述，自动推断会给错数，故本版不做。

