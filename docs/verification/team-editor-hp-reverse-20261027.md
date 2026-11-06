# 阵容编辑器生命数值改版：第一阶段回归与验收（2026-10-27）

接手 GPT 被额度中断的那一轮：它已落地「去掉性格名称输入 + 种族值右侧生命数值 + 手填反推 + 冲突锁定」的第一阶段，
但中断在「旧阵容导入 / 编辑保存是否被这次改动破坏」的针对性回归上。本轮把这段回归跑完，并补上它没覆盖的反例与前后端一致性证据。

## 1. 界面最终形态

编辑器配置区（`web/battle_workspace.html`）只剩四项：

| 控件 | ID | 说明 |
| --- | --- | --- |
| 血脉 | `editor-bloodline` | 保持不变 |
| 增益方向 | `editor-modifier-up_id` | 六维之一或“尚未确定” |
| 减益方向 | `editor-modifier-down_id` | 六维之一或“尚未确定” |
| 个体资质 | `editor-talents` | 六项复选，须恰好选三项 |

`id="editor-nature"` 已不存在——性格名称不再需要用户记忆。但 `nature_id` 仍在数据层保留：
旧阵容导入时按原值参与计算，界面不展示也不再让用户输入。

种族值区块右侧（`editor-summary` 的第二个子块 `editor-hp-wrap`）有「当前生命具体数值」输入框
（`aria-label="当前生命具体数值"`），双向工作：

- **正向**：方向和三项个体齐备 → 自动显示计算值（提示「按当前增减方向与三项个体计算 · N」）；
- **反向**：手填一个整数 → `reverseHpConfigurations` 枚举相容解：
  - 唯一解 → 直接应用并锁定；
  - 多解 → 列出全部组合（如 `物攻↑ / 魔攻↓ · 生命个体 10`），由用户点选，不虚构概率；
  - 无解 → 明确提示「当前已确定的增减方向或个体选择与该生命值冲突」，不改动任何已有值。

## 2. 冲突约束的实际粒度

用户举例的三类情形逐一对应到实现：

| 用户描述 | 已确定的部分 | 反推行为 | 反推后的界面 |
| --- | --- | --- | --- |
| 只加性格、不加个体值 | 方向已设，生命个体未勾 | 解里 `hp_talent_selected=false`，唯一 | 生命复选锁定为未勾（disabled），两个方向下拉锁定 |
| 只加个体值、不加性格增益 | 生命个体已勾定值，方向未设 | 候选只含**非生命**方向组合 | 生命复选保持勾选并锁定，方向下拉在选定候选后锁定 |
| 性格与个体值都已确定 | 方向 + 生命个体都定 | 只做校验 | 匹配则应用，不匹配则报冲突且回滚 |

锁定由 `editor.hp_constraint = {up_id, down_id, hp_selected, hp_value}` 承载；
`renderTalents` 里 `check.disabled = d==="hp" && !!editor.hp_constraint || ...`，
`renderEditor` 里 `select.disabled = !!editor.hp_constraint`。
任一手动改动（勾选、改方向、改个体值）都会先 `clearHpReverse()`，即先解除锁定再改，不留半锁状态。
另提供「清除反向限制」按钮显式解锁。

## 3. 验证

### 3.1 前端（真实 UI 处理器，内存 DOM）

`node --test tests/test_battle_mechanics.js tests/test_battle_team_code.js tests/test_simulation_ui.js tests/test_weather_ui.js`
→ **101 / 101 通过**（原有 99 项 + 本轮新增 2 项）。

新增两项专门覆盖 GPT 没测的反例：

1. `HP-only reverse fill never offers a life-changing direction when the HP talent is already fixed`
   —— 生命个体已定 10、方向未设时，`reverseHpConfigurations` 返回的**全部**候选都满足
   `hp_talent_selected=true / hp_talent_value=10`，且 `up`、`down` 都不含生命；界面列出多个按钮、
   点选后生命复选保持勾选并锁定、两个方向下拉锁定、状态回到「按当前…计算 · 400」。
2. `an HP value that contradicts the fixed directions does not silently rewrite them`
   —— 方向 hp↑/spd↓ 与生命个体 10 已定，填入不相容的 401：`hp_constraint` 仍为 null，
   方向和个体值原样保留，下拉不被锁死。

### 3.2 后端相关套件

`python -m unittest tests.test_simulation tests.test_damage_inference tests.test_lab_server -v`
→ **31 / 31 通过，111.716s**。覆盖引擎 -12 的开局能量 10、面板估算、伤害反推、HTTP 路由。

### 3.3 前后端生命公式对拍（本轮新增）

`scripts/_hp_parity_export.py` + `scripts/_hp_parity.js`：同一批 8 个配置分别走
`web/battle.js:configuredMaxHp` 与 `lab/simulation._estimate → arena_stat60`，结果**完全一致**：

```
[378, 317, 317, 294, 296, 399, 368, 380]
```

两处是同一表达式：`growth = f32(base*0.01) + raw_iv*0.005`（`raw_iv` = 显示个体值 × 6）、
`core = jsRound(f32(170*growth+70))`、`hp = jsRound(core*mult+100)`，float32 强转位置也一致。

### 3.4 真实 HTTP 端到端（本轮新增）

`scripts/_http_e2e_hp.py` 对着 8766 上真实运行的 server 验证「编辑器里的配置 = 试战面板实际使用的面板」：

| 用例 | 编辑器算出的生命 | `/api/simulation/prepare` 返回的 max_hp | 开局能量 |
| --- | --- | --- | --- |
| 3001 / hp10·patk10·spd10 / hp↑ spd↓ | 378 | 378 | 10 |
| 3001 / patk10·matk10·spd10 / patk↑ matk↓ | 281 | 281 | 10 |

页面可达性：`/battle` 200（29672 字节）、`/battle.js` 200、`/simulation.js` 200、
`/api/status` 200、`/api/catalog` 200；`/battle` 返回的 HTML 中
`editor-modifier-up_id` 与 `editor-summary` 存在、`id="editor-nature"` 不存在。
（`/battle_workspace.html` 本身 404 属正常：`/battle` 由 server 读出该文件后渲染。）

## 4. 未完成 / 已知限制

- **候选过宽**：方向未定、生命个体也未设时手填数值，候选可达 20+ 条。界面全部列出不虚构筛选，
  但没有做「按常见度排序」或分页，属交互体验问题。
- **性格名称彻底移除**：按 GPT 的口径是「界面隐藏、数据保留」。若要求连存储层一起删掉，
  需要另做一次存档迁移（当前旧存档的 `nature_id` 仍参与计算）。
- 本轮未跑：`tests/test_rl_battle_env.py`（26 项，约 12 分钟）与全量 Python 套件；
  引擎已升到 `composable-battle-20261027-12`，旧 `engine_hash` 不可比对。

## 5. 怎么用

```powershell
# 项目根目录
$env:PYTHONUTF8='1'; $env:PYTHONPATH='.'
python -m lab.server --port 8766
# 浏览器打开 http://127.0.0.1:8766/battle
```

编辑器里：选精灵 → 选血脉 → 选增益/减益方向 → 勾三项个体 → 右侧生命数值会自动出现；
或直接手填你看到的满血数值，让平台反推方向与个体值。保存后试战面板用的就是同一套面板值。

## 6. 产物索引

| 文件 | 内容 |
| --- | --- |
| `artifacts/_js_tests.log` / `.status` | 101/101 全量前端日志 |
| `artifacts/_py_core.txt` / `_py_core_summary.txt` | 31/31 后端日志 |
| `artifacts/_hp_cases.json` / `_hp_py.json` / `_hp_js.json` | 8 组对拍输入与两侧结果 |
| `artifacts/_http_smoke.txt` / `_http_smoke_battle.txt` | 端点状态与页面标记检查 |
| `artifacts/_http_e2e_hp.json` / `.log` | 真实 HTTP 端到端结果 |
