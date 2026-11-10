# 第二台设备继续开发

仓库：https://github.com/sduwcdd/RoCo-PVP ，桌面版本1.1.8。源码直接位于根目录，不再进入RoCo_PVP/source，也没有AI_try、旧APP和private-source分区。旧历史在原设备单独保留。

## 获取与运行

```powershell
git clone --recurse-submodules https://github.com/sduwcdd/RoCo-PVP.git
cd RoCo-PVP
py -3.13 -m venv .venv-rkpp
.venv-rkpp/Scripts/python.exe -m pip install -r requirements.txt
npm --prefix overlay ci
npm --prefix overlay start
```

需要Python3.13、Node.js/npm、Git，采集另需Npcap。旧布局克隆请保留后重新克隆，避免覆盖未提交工作。后续使用git pull --ff-only及git submodule update --init --recursive。

根目录洛克PVP.exe是源码启动入口，依赖同目录源码与依赖。命令行工作台为 .venv-rkpp/Scripts/python.exe -m lab.server --port 8766。托盘退出等待本APP采集、HUD和工作台停止；取消管理员授权会保留APP并提示。

## 当前边界

Windows1.1.8包含退出清理、中文日志编码修复、敌方原始性格箭头、HUD内容高度适配及本机环境检查，保留身高/体重/音调与奖牌预测，战斗规则与HUD共用。图鉴快照20261105T124140+0800，限制见PROJECT_STATUS.md。

mobile保留在研源码：Android内部0.2尚无真实手机游戏协议验收；iOS未编译，采集转发未接通。它们不是已完成的Windows1.1.6功能。步骤见../mobile/README.md。HEV子模块固定提交；SDK、本机Python路径和签名条件需在目标设备配置。

## 数据与打包

源码包含必要图鉴、规则、资源、来源证据及匿名化回归夹具。凭据、会话密钥、个人队伍、真实回放、抓包、环境、node_modules和构建输出不进Git。安装包在同仓库Releases下载。普通Windows构建见UPDATABLE_APP.md。

第二台实际安装、构建与运行仍需目标机验证。Git不迁移Codex聊天、账号或设备设置；聊天应单独安全传输，不提交公开仓库。
