# Roco Sandbox 公式来源核查（2026-10-25）

结论：新找到的社区源码提供了可复现的计算实现，但没有补齐本项目当前版本真实游戏校准证据。其普通伤害具有已有 Showdown 候选的先取整显示威力结构；相似的数学结构不能代替逐步浮点运算核对，更不能用另一个项目重复采用公式来证明游戏正确性。未改引擎、默认公式、数据库或训练许可。

## 固定来源与版本

仓库为 [HZ-KMNO/roco-sandbox](https://github.com/HZ-KMNO/roco-sandbox)，本次固定提交 `5fd3be6a7b02f4a066a9ce1060e4abdfd2031601`，提交时间 `2026-06-05T14:40:19Z`，package 版本 0.4.0。早于本项目 BWIKI `s4-2026-10-16` 快照，不把它视为当前规则版本。

递归树有 104 个文件、`truncated=false`；文件路径中未发现 test、fixture 或 calibrat 命名项，package scripts 只有开发、构建、预览和 Tauri 命令。本次查阅的公式文件没有真实对局录像或逐事件样本引用。这只说明本次可访问仓库范围内未找到校准证据，不能证明作者从未做过测试。

归档位于 `data/reference/formula-followup-20261025/`；`roco-sandbox-manifest.json` 保留固定 URL、文件 SHA-256、完整树路径与获取时间。只保存所需来源文件，没有创建新代码库或执行第三方应用。

## 精确实现与已有候选的关系

- [calculator.ts 30–50](https://github.com/HZ-KMNO/roco-sandbox/blob/5fd3be6a7b02f4a066a9ce1060e4abdfd2031601/src/lib/calculator.ts#L30) 的非生命面板为 `round(round(110*(R+3*t)/100+10)*(1+mod)+50)`；生命改为系数 170、内加 70、外加 100。源码没有 `Math.fround`。中性 R=105、t=0 返回 176，不能替代已有 Arena 单精度候选的 175。其 `110*(R+3*t)/100` 及加 10 后取整的位置也不能因代数等价就视为 Showdown 文档 `round(1.1*(R+3*t))+10` 的位级等价。它还默认六维资质为 0，本项目不能把这种程序默认值当成阵容码恢复出的事实。
- [calculator.ts 78–101](https://github.com/HZ-KMNO/roco-sandbox/blob/5fd3be6a7b02f4a066a9ce1060e4abdfd2031601/src/lib/calculator.ts#L78) 先将威力、本系与属性倍率乘积 `Math.round`，源码先计算 `K=37/41`，再计算 `floor(round((A*Q)*K)/D)`；本系常数 1.25，返回 `min=max`。这保留了已有 Showdown 候选的中间威力取整结构；实际系数运算顺序也必须保留，不能改写成顺序乘 37 再除 41 后声称位级一致。没有提供可裁定 Arena/Showdown 差异的新实战证据。该函数对非正防御直接返回 0，也不是已经验证的游戏边界。
- [damageReverser.ts 41–61](https://github.com/HZ-KMNO/roco-sandbox/blob/5fd3be6a7b02f4a066a9ce1060e4abdfd2031601/src/lib/damageReverser.ts#L41) 把反推边界向外取整，属于宽区间近似，不能直接当精确候选集。Node 源表达式构造检查：攻击 100、防御 102、威力 75、本系 1.25、属性倍率 1，正推伤害 83；反推返回攻击 99～101，但逐个正推分别为 82、83、84。只有中间整数符合该构造观察。证据保存为 `roco-sandbox-arithmetic.json`；这不是游戏观测。
- [damageReverser.ts 78–108](https://github.com/HZ-KMNO/roco-sandbox/blob/5fd3be6a7b02f4a066a9ce1060e4abdfd2031601/src/lib/damageReverser.ts#L78) 对不相交观察会重置为最新区间；[144–180](https://github.com/HZ-KMNO/roco-sandbox/blob/5fd3be6a7b02f4a066a9ce1060e4abdfd2031601/src/lib/damageReverser.ts#L144) 只尝试零资质或攻击项 +10，并按区间中点最近的性格打高/中/低标签。这些不是经过校准的后验概率，不能直接迁入用户要求的资质推断。

## 不适合填补当前状态结算缺口

[simulator.ts 2846 起](https://github.com/HZ-KMNO/roco-sandbox/blob/5fd3be6a7b02f4a066a9ce1060e4abdfd2031601/src/lib/simulator.ts#L2846) 的灼烧实现使用最大生命乘 2% 与层数后 `Math.round`，未在该路径乘属性倍率或封顶 1000；衰减至少一层，因此 1 层变 0，而 3 层变 2。中毒路径则乘属性克制并设至少 1 点。源码采用这些具体规则，不等于 BWIKI 已确认它们；它们也与历史 PVE 灼烧文章的候选存在差别。

该文件多处给毒/烧叠层设 `Math.min(3, ...)`；这不能被当作本项目已验证的状态层数上限。当前技能来源明确出现赋予 10 层灼烧等描述，而相应规则和特殊机制还需核对。文件中的随机行为使用 `Math.random`，不能直接充当可复现 RL 环境。

## 许可及后续使用边界

[LICENSE](https://github.com/HZ-KMNO/roco-sandbox/blob/5fd3be6a7b02f4a066a9ce1060e4abdfd2031601/LICENSE) 开头为 MIT 条款，但末尾另附游戏数据、个人学习用途及禁止商业再分发声明；GitHub 元数据返回 `NOASSERTION`。本报告仅记录原文结构，不对冲突条款作法律结论，也不将整个项目称为无条件 MIT 可复用。归档保留完整许可证。

可利用的是固定版本下的公式对照与反推反例；不可利用的是把源码默认值、宣传覆盖率或自动修正当作游戏真值。建议继续保留既有候选公式分歧，并用完整面板、版本和逐事件原始记录设计可区分样例。当前实战校准样本新增 0。

可信度：98/100（源码行为与获取范围）。已确认：提交、文件、公式和构造算术结果。待核实：当前游戏一致性、原作者未公开实测以及混合许可的具体法律解释。疑似编造：无。
