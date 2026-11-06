# 手机版开发入口

手机版与游戏在同一台手机运行。计算在手机本机进行，复用 `lab`、现有 HUD、BWIKI 快照和来源校验，不要求电脑伴随服务。桌面安装包和既有用户数据没有迁移或覆盖。

## Android 内部开发版

支持 Android 10 / API 29 及以上，arm64-v8a 和 x86_64。当前内部测试包为 **0.2**：`build/roco-mobile-android-internal-0.2.apk`。旧 0.1 包 `build/roco-mobile-android-internal-debug.apk` 保留，避免混淆请安装带 `0.2` 的文件。配套记录为 `build/android-0.2-verification.json`、`build/android-0.2-device-tests.txt`。

1. 在手机安装内部 APK，打开“洛克同机助手（内部版）”。
2. 首页点击游戏选择卡，搜索并确认实际游戏应用，再点“开始采集”授权 VPN。新版会优先匹配“洛克王国：世界”，不会默认采集应用列表第一项；运行中诊断另显示实际采集包名。仅选中应用经过本机转发器，没有远程代理。
3. 点击“允许悬浮窗”，在系统设置允许显示在其他应用上层；返回后可拖动顶部栏，点击顶部栏收起或展开。
4. 开启采集后**完全退出并重新打开游戏**，使解析器能够观察握手。只切换后台或直接进入对战可能继续使用旧连接。可点“打开游戏”启动已选游戏。
5. 底部切换连接、我方、对方、回合和图鉴，宽屏另有双方对照。首页分别显示网络采集、握手和对局识别，不把 VPN 启动当作战斗解码成功。通知栏或首页“停止采集”会撤销本机 VPN。
6. 仍无数据时，展开首页“连接诊断”并点“复制诊断信息”。包括实际采集应用、TCP/UDP 数量、协议分类、握手与业务计数及错误；不包含密钥、原始报文或个人对局。将这些诊断文字提供给开发者，才能继续核实真实手机协议。

“VPN 已启动”只说明转发器运行；识别到握手及真实战斗报文后才能显示对局。尚未完成真实手机游戏协议验证。手机已有其他 VPN 时，系统可能要求替换当前 VPN；系统行为参见 [Android VPN 文档](https://developer.android.com/develop/connectivity/vpn)。

已进行 Android 模拟器验证：内嵌 Python、资源身份校验、同源 HTTP/HUD、JNI；独立测试应用实际经过 TUN → HEV → 本机 SOCKS → 出口的 TCP/UDP 双向转发；错误停止清理及悬浮窗显示。该验证不能代替真实游戏登录、战斗协议和厂商后台限制的实测。

0.2 修复了旧版仅镜像 8195 端口的盲区，改为各 TCP 连接首段有界识别。已识别 HTTP/TLS 等非游戏流只继续转发，不送战斗解析器；这是协议识别，不是任意 TLS 解密。业务包早于握手时保持等待，不因缺密钥立即停止 VPN；真正解密失败或战斗协议解析失败仍明确阻断。非战斗未知消息单独计数，不把原始字段树当作已知语义。计数在普通连接关闭后保留。

本轮 10 项小型边界测试和两条主机内嵌引擎加密管线通过；模拟器 3 项检查还包含经实际 VPN 的 18082/18083 非标准端口 → 握手 → 共享解析器 → HUD，两条构造协议场景覆盖未知非战斗消息及缺握手后恢复。它们是明确标注的测试夹具，不是实际手机游戏抓包，不进入发布 APP。未修改伤害、技能或对战结算规则。

## iOS 当前可交付范围

`ios/` 包含 Xcode 工程、前台本机引擎桥接、完整面板和只读视频画中画源码。画中画显示真实快照及更新时间，完整交互在助手内进行。

目前没有 Mac/Xcode 和签名条件，未生成 IPA，也未编译或在 iPhone 验证。iOS 游戏流量转发、扩展内后台引擎及 App/扩展通信仍未接通，VPN 按钮明确禁用；这些是实际实现缺口，不能描述为只差签名。详见 [iOS 构建说明](ios/README.md)。

## 共用规则与构建

`python/roco_mobile.py` 接收原生转发器提供的有序 TCP 字节，调用已有协议解析器、BattleTracker 和 HUD 发布流程。`shared/index.html` 只负责手机布局，伤害与配置推断继续使用现有实现。HTTP 仅监听 `127.0.0.1`，保留原有 Host/Origin 校验。缺失握手、队列溢出和解析错误均可见，不伪造战况。

在仓库根使用已安装 `cryptography` 的 Python 3.13 构建环境生成配套资源；当前验证过的 `.venv-release` 可用，采集环境 `.venv-rkpp` 不保证含有打包依赖：

```powershell
.venv-release/Scripts/python.exe scripts/build_mobile_resources.py --android-source-stage
Set-Location mobile/android
./gradlew.bat assembleDebug
```

JDK、SDK、Python 的本机路径按 `android/local.properties` 与 `ROCO_BUILD_PYTHON` 配置。依赖固定版本及来源见 [Android 依赖记录](android/DEPENDENCIES.md)。Android 编译器需要临时 `.py` 输入，Chaquopy 在 APK 内编译为 `.pyc`；完成构建并核对包内内容后删除 `mobile/build/generated/android-python/`。下次构建重新生成，不改动引擎原始源码。

当前手机版保护级别是字节码和认证加密资源，低于桌面原生编译保护。APK 属内部开发包，可被逆向，不作为正式保护版本分发；release 构建已阻断。生成资源、临时编译输入、安装包、签名材料均不得提交到公开仓库。没有上传或发布手机版。
