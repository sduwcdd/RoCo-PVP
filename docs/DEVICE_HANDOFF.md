# 第二台设备继续开发

仓库：https://github.com/sduwcdd/RoCo-PVP ，桌面版本1.1.8。源码直接位于根目录，不再进入RoCo_PVP/source，也没有AI_try、旧APP和private-source分区。旧历史在原设备单独保留。

## 获取与运行

```powershell
git -c core.autocrlf=false clone --recurse-submodules https://github.com/sduwcdd/RoCo-PVP.git
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

Android内部版已推进至0.3，APK以安卓内测预发布提供，源码位于mobile目录。iOS前台共用移动界面，采集转发仍未接通。手机使用步骤见../mobile/README.md。HEV子模块固定提交，SDK、本机Python路径和签名条件需在目标设备配置。

本地开发现为Android 0.10，已兼容华为Android 12回传的0x73上行前缀，139帧离线解析及两个编译模式验证通过。保留有界协议样本采集、原生文件导出和`scripts/replay_mobile_protocol.py`离线回放入口。默认PVP保留完整战况，新增只显示当前敌方身份、性格方向、体重、声音及奖牌提示的PVE模式。修复上行消息反复读取协议表的耗时，同份0.7用户记录的本机编译后端回放从13.45秒降至PVP4.29秒、PVE1.07秒，PVP最终战况相同，PVE元数据与完整解码相同。手机实际延迟和PVP 6v6仍待实测，尚未发布新GitHub版本。0.8延用既有内测签名。私密样本禁止纳入源码同步，步骤见mobile/README.md及docs/verification/android-pve-performance-20261111.md。

## 安卓0.3继续开发

Android 0.9新增`PvpOverlay.java`三个独立原生窗口及`mobile/shared/pvp-panel.html`透明HUD包装页，横屏按左上我方、右上敌方、顶部居中历史布局。标题点按收放、拖动移动，收起卸载页面并缩小真实窗口边界。PVE沿用0.8界面。新版APK仅本机生成，未发布GitHub；真机触摸与横屏效果待验证。构建身份为`mobile-20261111-internal-09`。

下载入口为 https://github.com/sduwcdd/RoCo-PVP/releases/tag/android-v0.3.0-internal ，包含APK、SHA-256校验文件和验证记录。此版本标为预发布，Windows更新使用稳定版本。

已有仓库先执行 `git pull --ff-only` 和 `git submodule update --init --recursive`。构建使用Python3.13、JDK17、Android SDK36基础平台和build-tools35.0.0；Gradle8.11.1及插件版本沿用仓库锁定值。

在仓库根目录配置本次PowerShell会话并构建：

```powershell
py -3.13 -m venv .venv-release
.venv-release/Scripts/python.exe -m pip install -r requirements-release.txt
$env:JAVA_HOME = '<JDK17目录>'
$env:ANDROID_HOME = '<Android SDK目录>'
$env:PATH = "$env:JAVA_HOME/bin;$env:PATH"
$env:ROCO_BUILD_PYTHON = (Resolve-Path .venv-release/Scripts/python.exe).Path
.venv-release/Scripts/python.exe scripts/build_mobile_resources.py --android-source-stage
Set-Location mobile/android
./gradlew.bat assembleDebug
```

若新设备已有local.properties，请核对其中SDK路径。输出为mobile/android/app/build/outputs/apk/debug/app-debug.apk。完整构建与来源说明见mobile/README.md、mobile/android/DEPENDENCIES.md。打包完成并核对后，删除mobile/build/generated/android-python临时编译输入。

签名文件单独通过安全渠道迁移。0.3测试证书SHA-256为 `f62169ddc3fd0df6d55ec550717e31692ec4ebce6d0d0a5fb1e43e1178758354`。继续覆盖安装同一测试应用时，将原debug.keystore放到目标设备ANDROID_USER_HOME指定目录；使用新密钥签名会产生安装冲突。APK中的资源与模块由构建脚本重新生成，签名私钥和生成的密钥配置只保存在本机。

0.3已通过12项Python边界测试、5项移动界面测试、主机TCP/UDP故障回归，以及APK构建、签名和资源核对。真实手机0x4013首包兼容性仍需新诊断确认。下一步优先查看用户0.3诊断的decode_issues；协议入口为mobile/python/roco_mobile.py，转发与悬浮窗入口为mobile/android/app/src/main/java/cn/roco/mobile/CaptureService.java，移动界面为mobile/shared/index.html。

## 数据与打包

源码包含必要图鉴、规则、资源、来源证据及匿名化回归夹具。凭据、会话密钥、个人队伍、真实回放、抓包、环境、node_modules和构建输出不进Git。安装包在同仓库Releases下载。普通Windows构建见UPDATABLE_APP.md。

第二台实际安装、构建与运行仍需目标机验证。Git不迁移Codex聊天、账号或设备设置；聊天应单独安全传输，不提交公开仓库。
