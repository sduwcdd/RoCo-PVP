# 洛克 PVP 辅助工具 · 1.1.9

用于洛克王国：世界的本地Windows辅助APP，提供实时HUD、对局记录、伤害估计与配置推断。维护源码直接位于仓库根目录；源码和安装包统一在本公开仓库维护。

## 使用安装包

从 [Releases](https://github.com/sduwcdd/RoCo-PVP/releases/latest) 下载Windows安装包。抓包需要Npcap及Windows管理员授权。关闭窗口收起到托盘，托盘退出等待本APP的采集、HUD和工作台停止；授权取消时不会假装退出。

1.1.8修复中文日志乱码、敌方原始性格增减箭头显示，并改进HUD窗口遮挡范围；包含本机抓包环境检查，检查结果不代表游戏检测策略或账号安全结论。身高、体重、音调参数及奖牌条件预测继续提供，未确认取得的奖牌明确显示预计。当前图鉴快照为20261105T124140+0800。范围与限制见 [当前进度](docs/PROJECT_STATUS.md)。

Windows安装版启动自动检查更新，连接控制台提供“一键更新并重启”。安卓0.10更新引导包与0.11支持APP内检查、下载、校验及系统确认安装。安装说明见[手机版](mobile/README.md)，实际验证见[更新记录](docs/verification/in-app-update-20261112.md)。

## 从源码开发

```powershell
git clone --recurse-submodules https://github.com/sduwcdd/RoCo-PVP.git
cd RoCo-PVP
py -3.13 -m venv .venv-rkpp
.venv-rkpp/Scripts/python.exe -m pip install -r requirements.txt
npm --prefix overlay ci
npm --prefix overlay start
```

需要Python3.13、Node.js/npm及Git。根目录洛克PVP.exe是依赖源码和本地环境的启动入口，不能单独分发。详情见 [跨设备开发](docs/DEVICE_HANDOFF.md)。

## 代码入口

- lab/server.py：本地API、工作台与HUD。
- lab/live_battle.py：报文、在场精灵和观测历史。
- lab/live_damage.py、hud_damage_runtime.py、live_modifiers.py：统一伤害估计。
- lab/live_inference.py、live_stat_model.py：属性及配置推断。
- overlay：控制台、HUD窗口、更新与退出管理。
- web：页面和资源；data：图鉴与规则；artifacts：必要来源证据。
- mobile：Android/iOS在研源码，状态见 [手机版说明](mobile/README.md)，不能等同于Windows验收。

不包含AI训练、旧保护安装包、凭据、个人队伍、真实回放或抓包。匿名化回归夹具和规则来源保留；工程检查不代表所有游戏规则已校准。

## 构建与维护

Windows使用普通打包，不使用Cython或前端混淆。见 [构建与发布](docs/UPDATABLE_APP.md) 和 [BWIKI维护](docs/BWIKI_UPDATE.md)。

公开更新源为sduwcdd/RoCo-PVP；旧更新源的用户需手动安装一次新源1.1.6。账号、聊天、设备配置和本地数据不通过Git迁移。
