# 魔镜能量减少复核（2026-10-25）

来源为 BWIKI 快照 20261025T013619+0800，技能 7170280 魔镜，完整原文“敌方获得魔防-50%，且失去3能量。”。v6仅增加此整句，未泛化偷取、应对或全队效果。原171个v5已编译程序除版本外不变；v5原产物保留。

编译测试44项通过（5.966秒）；运行器和服务端测试60项通过（16.712秒）；独立配对行动测试33项通过（47.433秒，新增5项）。上述测试集合存在重叠，不将计数简单相加为独立测试数。完整相关回归结果另见 energy-reduction-tests-20261025.json。

独立复核执行56组构造能量/费用组合（对方能量0至7，后手费用0至6），18提交、38阻断，核对更新后支付、请求扣除3与实际扣除min(energy,3)、无能量转移、失败整对回滚及回调未运行。这些均为实验接口检查，不是实际对局证据。

主代理复核新增运行逻辑：能量操作只修改指定目标，参数必须正整数且拒绝布尔；要求独立energy_reduction_policy=clamp_to_zero_experiment；事件保留前后能量与请求/实际减少量；任何预检失败不会留下先前魔防修正或已付费用。后续执行故障也整体回滚，后续条件读取修改后的状态。

完整回合、力竭处理、后手费用不足的游戏行为和真实操作顺序均未因此完成。尤其整对回滚只是失败事务边界，不代表游戏会撤销先手已发生的技能。

## 本次文件 SHA-256

- lab/skill_programs.py: ea2abfe91641493cd69a28274a4265ca68138811aad999399220796f963df23e
- lab/effect_runtime.py: 2cbe1a94424e55a60506cefe10859239fce439ea858e7c360cd3389b636bbb2b
- tests/test_skill_programs.py: 9d55c094d8f6219dc1d29b4bb2b38f9f5d005d73062cb1e9dc8e79a570aa1202
- tests/test_effect_runtime.py: 418e4ccef882c24b6b87c5cfd385381f51fae50e3950022c3fb5bfec8916bc71
- tests/test_action_runtime.py: dc32efaed7432a1b9e736e2e905347aabf870667cd557c54435fcb10411f6cf9
- tests/test_lab_server.py: 7178c5b880934a88413302078cbe7fcff6a75d2cbc30f701408b3e345a0b9fa6
