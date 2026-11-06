# 第三方发行版资产整合验收（2026-10-28）

对象：`E:\洛克PVP助手`（「青空洛克PVP助手」打包发行版）与本项目 `D:\Users\86195\Desktop\workspace\roco_pvp`。

原则（用户口径）：**已有的保留原状，对方有的新功能直接照抄**；对方工程只读，未改动、未移动任何文件。

范围：本轮做了「数据与图标落地 / 权威数据对拍 / 游戏内 HUD 页面照抄并接入 / 工作台图标」四块；**未做**状态百分比自动推断、天梯使用率接入 RL 先验、实时抓包（rkpp）。

---

## 1. 对方工程可复用的东西（已核实）

| 资产 | 位置 | 性质 | 本轮处置 |
|---|---|---|---|
| 游戏内悬浮 HUD | `app\wwwroot\battle-hud-full.html` | 单文件内联脚本，108501 字符，不联网络，只读 `localStorage` 的 `roco.battleHud.*` | 照抄为 `web\hud.html` + 1 行桥接脚本 |
| 权威解包数据 | `app\wwwroot\native-data\authority\*.json` | `skill.json` 1988 / `petbase.json` 1150 / `buff.json` 3310 / `level_skill.json` 1.5 MB | 同步到 `data\external\` |
| 增益换算表 | `app\wwwroot\roco_buff_calc_map.json` | 220 条 `{id,name,desc,typeId,baseIds,phyAtkPercent…}` | 同步，未接线 |
| 天梯使用率 | `app\wwwroot\pokedex_800_pvp_usage_v340.json` | 865 条，带 `metadata.source_endpoint` 与快照时间 | 同步为 `data\external\pokedex_pvp_usage.json`，未接线 |
| 图标包 | `app\wwwroot\roco-skill-icons`（1766 张）/ `roco-pet-avatars-id`（990 张）/ `roco-type-icons`（18）/ `bloodline-icons`（21） | PNG/WebP | 同步到 `web\assets\roco\` |
| 抓包模块 | `app\rkpp\`（17 个 py + `rkpp_data.sqlite` 24.5 MB） | 需 Npcap + 管理员权限，`rkpp_codec.py` / `rkpp_opcode_payload.py` 版权属第三方 RocoMITMServer | 只做结构探查，未复制、未运行 |

对方前端业务代码是打包产物（`assets\index-B3Ye5KAR.dat` 3.4 MB），不可读，因此"照抄"只落在可读的 HUD 页与数据/图标上。

---

## 2. 权威数据对拍：图鉴 vs 解包

脚本：`scripts\verify_external_data.py` → `artifacts\_verify_external.txt`。

| 项 | 一致 | 差异 | 结论 |
|---|---|---|---|
| 技能能耗 | 579 / 579 | 0 | 完全一致 |
| 技能威力 | 354 | 4 | 全部是"计算型威力"，**我方数值正确**：`dam_para[0]` 是公式标记，基础威力取 `dam_para[1]`（吨位压制 7020990、以重制重 7021000、钢钻 7070030、冰锋横扫 7090360） |
| 连击段数 | 51 | 3 | 均为状态技（无威力），不影响伤害：`7021080 三连破`、`7110410 电离爆破`、`7160390 耍赖` |
| 六维种族值 | 3746 / 3756 | 2 形态 | `3663 量风碗`、`3773 幽铃` 各差 5–6 项；两份数据互斥，**未定论、未改** |
| 形态特性 id | 626 / 626 | 0 | 完全一致 |

结论：现有引擎的技能能耗与伤害技能威力经解包数据复核成立，不需要改动。

---

## 3. 游戏内 HUD：照抄 + 桥接

- `scripts\install_hud.py` 以对方原件为输入生成 `web\hud.html`：源 sha `ca82ff9e3f9e48fd`、产物 sha `828025e7d1750095`，只多一行 `<script src="/hud_bridge.js"></script>` 与头部注释。
- HUD 本身**不联网**，只读 `localStorage`。工作台通过 `publishHudSnapshot()`（`web\battle.js`）把局面写成 `roco.workbench.hud.v1`，`web\hud_bridge.js` 每 250 ms 转写成 HUD 认的三个键：`roco.battleHud.combatRuntime.v71`、`roco.battleHud.state.v52`、`roco.battleHud.recognizedEnemyTeam.v52`。**两侧代码都没有为对方改动。**
- 入口：工作台顶栏新增「游戏 HUD ↗」，直接打开 `http://127.0.0.1:8766/hud`。
- 发布内容只取工作台已记录的局面：双方成员、有序技能槽、最近血量百分比（我方据此换算绝对值）、对方已确认/已使用的技能、回合时间线。**不含对方隐藏配置**。

HUD 读到的字段（实测契约，改前端时按此对齐）：

- runtime：`myTeam` / `enemyTeam` / `active[side].rosterIndex` / `hp[side]{hpAfter,percent}` / `observedEnemyMoves` / `battleTimeline`。
- 队伍条目：`petName`、`petBaseId`（决定头像路径）、`currentHp`、`maxHp`/`stats.hp`、`moves[]`（含 `skillName` / `power` / `energy_cost` / `move_category`）。
- 图片路径：技能 `/roco-skill-icons/{技能ID}.png`、精灵 `/roco-pet-avatars-id/{形态ID}.png`（含 `_1` 异色）、系别 `/roco-type-icons/{系别}.png`。

---

## 4. 资源路由与图标接入

`lab\server.py` 新增静态服务：`/assets/roco/`、`/roco-pet-avatars-id/`、`/roco-skill-icons/`、`/roco-type-icons/`、`/native-data/roco_buff_calc_map.json`、`/native-data/authority/buff.json`，并对每个请求做 `resolve()` 后的根目录包含校验（穿越一律 404）。

图标文件按游戏图标资源 id 命名，而工作台说的是图鉴技能 id，因此服务端加了一层别名：找不到同名文件时用 `manifest.json` 的 `skill_icons` 映射再查一次（如 `7020480 → 某 icon id.png`），这样前端只要写 `/roco-skill-icons/<技能ID>.png` 即可。

工作台自身界面：

- 成员卡头像改为**本地优先**：先取 `/roco-pet-avatars-id/<形态ID>.png`，失败才回退 BWIKI 外链，再失败则移除（离线也能看）。
- 技能 chip 增加 15 px 技能图标（`<img class="move-icon">`），加载失败自动移除，不占位。

---

## 5. 验证证据

| 层 | 命令 | 结果 |
|---|---|---|
| 静态资源 | `python scripts\_http_static_check.py` | **15 / 15**（含 `/hud`、`/hud_bridge.js`、技能图标别名 `7020480`、异色头像 `3010_1`、两个 JSON；两处目录穿越均 404，未知技能图标 404） |
| HUD 渲染 | `node --test tests\test_hud_render.js` | **2 / 2**（无头 DOM 执行 HUD 内联脚本：我方 332 血、对方 205/250、技能条目、头像路径、替补；空快照不抛异常） |
| JS 全量 | `node --test tests\test_battle_mechanics.js tests\test_battle_team_code.js tests\test_simulation_ui.js tests\test_weather_ui.js tests\test_hud_render.js` | **110 / 110** 通过（原 108 + 新增 2） |
| Python | `python -m unittest tests.test_lab_server tests.test_damage_preview -v` | **30 / 30** 通过，89.6 s |

证据文件：`artifacts\_http_static.txt`、`artifacts\_hud_test.txt`、`artifacts\_js_tests.txt`、`artifacts\_py_tests.txt`、`artifacts\_verify_external.txt`、`artifacts\_sync_assets2.txt`、`artifacts\_install_hud.txt`。

### 浏览器实拍未做

本机 `bu` 页面会话整轮只返回 `Computer-use Python code completed.`，`cu` 侧 Chrome 为空白全屏；用户已明确「电脑出问题，后续没有必要不用实机截图」。因此 HUD 的"能渲染"以无头 DOM 执行 + 真实 HTTP 取资源两层证明，未提供截图。

---

## 6. 未做与原因

| 项 | 状态 | 原因 |
|---|---|---|
| 状态百分比自动推断（用 `roco_buff_calc_map.json` 带出物攻 +10 等） | 未接线 | 工作台现有 4 个手填输入可用；要自动带出须先确定"哪条 buff 生效于哪一方、叠几层"，需要与解包 buff 表逐条对齐，属独立一轮 |
| 天梯使用率接入 RL 配置先验 | 未接线 | 数据已落盘（865 条、带出处），但 `lab\rl_battle_env.py` 的候选先验当前只用阵容码与受约束变体；接入需改后验构造并重跑 `tests\test_rl_battle_env`（约 24 分钟） |
| 实时抓包（rkpp / Npcap） | 未引入 | 需管理员权限，且会在用户真实游戏会话上旁路监听，用户未表态 |
| `3663 量风碗` / `3773 幽铃` 种族值 | 未改 | 图鉴与解包互斥，缺第三份证据 |
| 3 条状态技连击段数 | 未改 | 无威力，不影响伤害；改动会影响 `skill_hits` 默认口径 |

---

## 7. 结论

- 对方工程中**可读且可复用**的部分已全部落到本项目：HUD 页面、权威数据、图标包、天梯使用率快照。
- 本项目原有功能未被替换：工作台仍是唯一操作界面，HUD 只是新增的一个视图；数据层、规则引擎、RL 环境均未改动行为。
- 图鉴数值经解包复核：技能能耗 579/579、伤害技能威力全部成立。
- 运行入口不变：`python -m lab.server --port 8766` → `http://127.0.0.1:8766/battle`，HUD 在 `/hud`。
