# 第二台设备继续开发

仓库：https://github.com/sduwcdd/RoCo-PVP ，桌面版本1.1.10。源码直接位于根目录，不再进入RoCo_PVP/source，也没有AI_try、旧APP和private-source分区。旧历史在原设备单独保留。

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

Android内部版已推进至0.15，APK以安卓内测预发布提供，源码位于mobile目录。iOS前台共用移动界面，采集转发仍未接通。手机使用步骤见../mobile/README.md。HEV子模块固定提交，SDK、本机Python路径和签名条件需在目标设备配置。

0.10阶段的本地开发记录，已兼容华为Android 12回传的0x73上行前缀，139帧离线解析及两个编译模式验证通过。保留有界协议样本采集、原生文件导出和`scripts/replay_mobile_protocol.py`离线回放入口。默认PVP保留完整战况，新增只显示当前敌方身份、性格方向、体重、声音及奖牌提示的PVE模式。修复上行消息反复读取协议表的耗时，同份0.7用户记录的本机编译后端回放从13.45秒降至PVP4.29秒、PVE1.07秒，PVP最终战况相同，PVE元数据与完整解码相同。该阶段手机实际延迟和PVP 6v6仍待实测，当时尚未发布新GitHub版本。0.8延用既有内测签名。私密样本禁止纳入源码同步，步骤见mobile/README.md及docs/verification/android-pve-performance-20261111.md。

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

## 跨设备保持安卓签名一致

2026-11-20回到当前设备开发，已同步源码至`0d19f48`，0.15在此基础上兼容实录中的`0x6E`上行前缀。实际项目位于`D:\workspace\projects\RoCo-PVP-public`，此前C盘入口通过现有路径兼容访问。临时文件、构建缓存、SDK和本轮安装包均位于D盘。

用户确认尚未迁移下述0.14私钥，并要求0.15使用本机已有签名。当前私钥实际文件为`D:\workspace\.roco-tools\roco-android-internal\android-user\debug.keystore`，由本机构建环境的`ANDROID_USER_HOME`选择。别名为`androiddebugkey`，沿用默认debug配置口令。证书SHA-256为`f62169ddc3fd0df6d55ec550717e31692ec4ebce6d0d0a5fb1e43e1178758354`。

将这一私钥通过私密渠道复制到另一设备的实际debug Store位置，默认是`%USERPROFILE%\.android\debug.keystore`；已有文件先备份。目标设备运行`:app:signingReport`核对实际Store与上述证书后再构建。私钥不进入Git。使用下述`b6a6896a`证书安装的0.14无法由此签名直接覆盖，应先备份用户数据再重新安装；之后各设备持续使用统一私钥。

### 0.14阶段的签名记录

2026-11-15已核对本机签名文件与已验证的0.14安装包证书一致。现有debug构建使用Android默认签名配置，设备迁移时需要复制同一份私钥文件。

- 本机签名文件为 `%USERPROFILE%\.android\debug.keystore`，当前实际路径为 `C:\Users\86195\.android\debug.keystore`。
- 通过U盘或私密传输将该文件复制到新设备的 `%USERPROFILE%\.android\debug.keystore`。目标位置已有文件时先备份，再放入本项目使用的原文件。Mac/Linux默认位置为 `~/.android/debug.keystore`。
- 当前别名为 `androiddebugkey`，沿用默认debug配置的库密码和密钥密码 `android`。
- 在新设备运行 `./gradlew.bat :app:signingReport`，核对实际Store路径及下面的SHA-256，再构建APK。同包名的后续版本继续递增versionCode。

当前0.14证书SHA-256为

```text
b6a6896a62a5d84a377b064e745f4d492d551e89272db10b26894aa2289b19f2
```

Git同步源码和这份说明，签名私钥通过私密渠道单独迁移。仓库已忽略`*.keystore`、`*.jks`等签名材料。仅复制APK或上述证书摘要无法代替私钥。

历史0.3证书SHA-256为 `f62169ddc3fd0df6d55ec550717e31692ec4ebce6d0d0a5fb1e43e1178758354`，属于此前另一设备的签名记录。覆盖当前0.14时以上述已核对的当前证书为准。

当前核对使用本机PKCS#12证书及安装包验证记录，安装包文件SHA-256与该记录一致。新设备尚需执行上述Store和证书核对。平台依据见[Android官方签名说明](https://developer.android.com/studio/publish/app-signing)。

0.3已通过12项Python边界测试、5项移动界面测试、主机TCP/UDP故障回归，以及APK构建、签名和资源核对。真实手机0x4013首包兼容性仍需新诊断确认。下一步优先查看用户0.3诊断的decode_issues；协议入口为mobile/python/roco_mobile.py，转发与悬浮窗入口为mobile/android/app/src/main/java/cn/roco/mobile/CaptureService.java，移动界面为mobile/shared/index.html。

## 数据与打包

源码包含必要图鉴、规则、资源、来源证据及匿名化回归夹具。凭据、会话密钥、个人队伍、真实回放、抓包、环境、node_modules和构建输出不进Git。安装包在同仓库Releases下载。普通Windows构建见UPDATABLE_APP.md。

第二台实际安装、构建与运行仍需目标机验证。Git不迁移Codex聊天、账号或设备设置；聊天应单独安全传输，不提交公开仓库。

应用内更新已接通Windows1.1.9与Android0.10引导包→0.11。测试与签名条件见verification/in-app-update-20261112.md，构建发布见UPDATABLE_APP.md。

国内安装包与更新指针托管于https://cnb.cool/sduwcgg/roco-pvp，维护流程见CNB_UPDATES.md。发布令牌使用本机被忽略的.env.cnb或cnb.txt文件。
