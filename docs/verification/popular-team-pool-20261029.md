# 热门配队数据快照与逐局抽队接口

日期：2026-10-29。**原始数据已保存，RL抽队接口已实现，但完整热门配队数据尚未取得，未启动热门阵容训练。**

## 已保存的数据

目录：data/external/pvp-community-20261029/。原始字节未修改，local-snapshot.json记录原路径、时间、大小和SHA-256；inventory.json记录全部文件哈希及统计。没有修改E盘的第三方助手。

- pvp-usage.raw.json：865个精灵/形态条目，其中772条有性格/个体加点/血脉/技能边际使用率，采集时间2026-09-28T19:52:13Z（北京时间2026-09-29）。不是865套队伍，不含完整联合配置概率。
- enemy-presets.raw.json：728个ID的预设；技能列表通常超过四个，不能当作真实携带四槽，也不能截取前四。已知三项方向与数值不证明同一真实整队配置。
- community-ui.source.js：配队/社区加载源码，用于保留来源。
- popular-*：指定助手接口的真实HTTP426响应及请求依据，不是成功的队伍数据。
- roco-showdown-popular-*：独立备选公开站的原文和抓取记录；本轮没有取得其动态完整配队。

## 实际阻断

指定助手的公开热门接口需要客户端完整性校验。使用本机真实版本1.0.54及实际入口程序集SHA-256，仍返回client_integrity_failed；无头请求返回client_update_required。没有伪造校验值、使用测试分支、读取账号凭据或规避访问控制。本地目录、精确WebView2字段、日志和vendor副本中未发现完整popular_teams_cache.json。证据见[source-discovery.md](../../data/external/pvp-community-20261029/source-discovery.md)。

前端存在热门配队功能不等于本地已有完整可训练阵容。远端映射器只明确读取排名/出场数/六只组合，成功响应的实际内容尚未确认。本地缓存的snapshot.builds读取器可含技能/血脉/性格及加点方向，但尚未取得真实记录，也不能仅凭plusStats方向推断数值。

当前training-pool.json明确source_status=blocked、teams=[]并保留原始错误。不能用单精灵统计随机拼队、固定课程或手工33条未知配置替代后声称热门阵容接入成功。

## 已实现的训练接入

- lab/rl_team_pool.py：绑定BWIKI目录哈希、PVP规则哈希及原始文件SHA；验证六只顺序、四槽与空槽顺序、性格、明确三项个体值，保留血脉/学习条件冲突。未知技能或条件不足不修复成正常配置。
- RLBattleEnv(team_pool=...)：每次reset用独立种子流为双方分别均匀抽一套，允许镜像；不重排六只或四槽。不修改战斗随机流、公式、技能、奖励或胜负。
- pool内容绑定引擎身份。抽出的阵容有副本隔离；clone保留冻结池；reset失败阻断旧状态继续使用。
- selfplay主进程/CPU worker/评估共用同一池。每局seed和双方team_id记录到team_matchups；这些审计信息不进入策略公开观测，敌方技能仍按实际观测揭示。
- 默认CLI读取training-pool.json，空池明确失败，不自动回退旧合成阵容。旧软件课程必须显式--pilot，固定自备双阵容仍可用--rosters，二者与--team-pool互斥。
- 检查点保存完整池及身份，本地evaluate_pvp_policy同样恢复池。旧模型、远程冻结版不覆盖；新源码身份已变化，旧模型仍需原冻结版加载。

## 导入与启动

拿到完整六人配置后，导出JSON应使用既有精灵配置格式：顶层teams数组，每项有id、name、roster；roster为六项，包含form_id、四个有序move_ids、nature_id或明确nature_modifiers、三项talent_selection及数值。涉及学习限制需血脉、等级/阶段或解锁依据。不得填未知资质、补默认技能或默默修正首领形态。原生snapshot/builds导出仍须基于真实样本核对字段映射，当前不会假装支持未验证编码。

```powershell
python scripts/import_pvp_team_pool.py --input 完整阵容导出.json --output data/external/pvp-community-20261029/training-pool-v2.json
python -m lab.selfplay --research --team-pool data/external/pvp-community-20261029/training-pool-v2.json --team-size 6 --max-episode-steps 49 --workers 1
```

导入器保留原始快照，逐项输出阻断/隔离记录，输出文件已存在时拒绝覆盖。原始字段不齐或全部不兼容时输出空池并退出2。当前默认池仍为空，上面的训练命令须在真实配置导入成功后才能运行。

验证：5项新增定向用例和1项既有评估回归均通过，包括真实6v6 reset/clone/观测隔离、两进程spawn接收相同池并记录抽队ID、确定性/源哈希拒绝、未知字段与重复技能拒绝、HTTP错误不生成合成队。另实际运行默认训练CLI，确认空池时报错且未创建训练目录。23项保存文件哈希再次核对通过；未跑全量测试，临时检查均以stdin执行，无临时脚本遗留。

本轮未远程部署、未启动新训练、未重写旧检查点。已有全机制与校准缺口仍保留，静态组件通过不代表完整实战已校准。
