# 邻槽当前威力纯查询

7070030钢钻与7070200六自由度已注册来源绑定的完整程序，保留传动1的既有共同生命周期。内部槽1/2（界面2/3号位）选择左右邻槽；边缘环绕未确认，明确阻断。

解包两项均为damage_rule24（Enum.ChangeRule.CR_BOTHSIDESELF），参数分别[0,1,33]、[30,0,25]，技能结果21150010为共同传动来源。BWIKI原文分别为两侧威力和三分之一、额外增加两侧威力差四分之一。完整record/hash、原SKILL和传动BUFF/BASE保存在reviewed-adjacent-power配置。

具名研究策略明确采用原文精确1/3、1/4，差取绝对量，先组合最后floor一次。当前表33并不被偷改称为精确33.333%；flag0也未被宣称已从服务端解出绝对差方向。source/policy必须匹配，边缘、递归依赖、未选choice和缺少纯source adapter的邻槽都阻断，绝不回落catalog基础power。

`power_query.quote_damage_power(rules_or_prepared,params,relative_state,context)`从research_damage提取并共享：history→机制→天气→特性→核心魔法→印记。它不执行伤害公式、不读攻防面板、不裁剪HP、不支付、不抽样、不运行hooks，也不修改输入；返回连击分摊前的实际power。research_damage继续保留状态触发早期分派、trait费用注入、ignore-resistance及所有原输出追踪。

`adjacent_power_runtime.quote_carried_powers(catalog,relative_state,context)`返回四槽quoted/blocked快照。每槽先解析实际source params：共同mechanism/action_fields/derived及native无副作用的单攻击表达，再绑定原槽history并用共同power query。已知非攻击技能和空槽为无攻击power0。原生多攻击阶段、读付款后能量的native源和需要实际蓄力状态的动态charge需要相应纯adapter；没有反推伤害代替查询。

`resolve(program,relative_state,context)`为preflight/execute共同入口。需`adjacent_power_policy=POLICY`、四槽当前总费用`carried_effective_skill_costs`、当前turn及动作上下文；重复同ID需`selected_skill_slot`。完整catalog文件SHA256与catalog_content_hash都绑定，PreparedRules不放进JSONcontext。同snapshot的不同目录内容不被混用。Swift在真实入场后重取共同费用快照并带同一政策。

费用项可为非负整数或严格的`{'blocked':非空原因}`。查询该槽时才传播失败，无关槽费用或choice不确定不会误挡已确认的左右邻槽。总费用技能和特性仍使用原严格全四槽合同。

定向验证：钢钻邻槽两项已有历史增长的当前power70/135被正确读出并得68，非基础50/90；纯查询无输入修改。六自由度50/90得40；边缘、循环和未选choice明确阻断。原damage物理/魔法面板定向复核通过。未跑全量回归或声称服务器时序已校准。
