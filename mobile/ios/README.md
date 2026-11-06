# iOS 本机助手源码

当前交付：**Xcode 工程和本机运行源码，未在 Mac 编译、未签名、未在 iPhone 验证，不是可安装 IPA。** 用户当前没有 Mac/开发者账户，因此这里完成可以在 Windows 开发、静态检查和交付的部分。

已经写入工程：

- `RocoLocal` 前台 App：Objective-C 调用内嵌 Python 3.13，校验同一份 `mobile/build/generated` 资源，由 `roco_mobile.start(filesRoot)` 返回 `127.0.0.1` 临时 HTTP 端口，WKWebView 打开 `/mobile` 完整面板。没有电脑伴随服务或云端后端。
- 原生只读画中画：CoreGraphics 把 `/api/hud/snapshot` 的真实回合、双方在场宠物、HP 和快照时间画入视频帧，使用 AVKit sample-buffer PiP；无数据则明确显示等待。面板中的 `rocoNative` / `{action: "pip"}` 调用已接入。PiP 可用性、后台更新和系统是否允许持续运行都还要真机验证；界面始终提示后台可能冻结，以时间戳为准。完整面板在助手内交互。
- `PacketTunnel` 独立扩展 target 和 App Groups / packet-tunnel entitlements：**现在不启动 VPN**。其 `startTunnel` 明确返回错误，绝不安装会吞掉流量的路由；App 的 VPN 按钮保持禁用。该扩展目前也不嵌入前台 App。
- Mac 构建准备脚本：可信本地 Python.xcframework、iOS 原生依赖、标准库复制、`.so → .framework/.fwork` 转换和签名。PyCryptodome 的原始 C 库另外通过 iOS loader glue 定位已签名 framework；启动先做 AES/AESGCM 导入和回环检查，失败则不宣布引擎就绪。

## 以后在 Mac 构建

需要完整 Xcode（只有 Command Line Tools 不够）、Python 3.13，以及可信来源的 Python 3.13 iOS `Python.xcframework`。Python-Apple-support 或按 CPython 官方文档自行编译均可；脚本不猜下载版本、散列或替你下载未经验证的包。

1. 在仓库根生成与 Android 相同的引擎资源：

   ```sh
   python3.13 scripts/build_mobile_resources.py
   ```

2. 准备匹配 Python 3.13 和设备/模拟器 ABI 的两份 `app_packages`，包含 `cryptography`、`pycryptodome`（`Crypto`）、`scapy`、`protobuf`、`msgpack` 以及它们需要的依赖。`cryptography`、`Crypto`、`_cffi_backend` 等二进制必须是 iOS 构建；**Windows、macOS 或 Android wheel 不能替代**。本仓库尚未产出或验证这些 iOS 原生依赖，不应把准备脚本通过视为全部原生依赖已经可用。

3. 从仓库根执行（路径换成已验证的本地制品）：

   ```sh
   python3.13 mobile/ios/scripts/prepare-runtime.py \
     --python-xcframework /absolute/path/Python.xcframework \
     --packages-device /absolute/path/ios-arm64/app_packages \
     --packages-simulator /absolute/path/ios-simulator/app_packages
   open mobile/ios/RocoLocal.xcodeproj
   ```

   `Runtime/` 被 git 忽略；脚本拒绝覆盖已有 Runtime，换制品时先移走旧目录。工程已提交，不需要 XcodeGen；修改工程生成逻辑后可运行 `python3 scripts/generate-project.py` 重新生成。

4. 选择 `RocoLocal` scheme。先构建模拟器：

   ```sh
   xcodebuild -project mobile/ios/RocoLocal.xcodeproj -scheme RocoLocal \
     -sdk iphonesimulator -configuration Debug \
     CODE_SIGNING_ALLOWED=NO build
   ```

   Xcode build phase 调用 `python3` 标准库脚本，请保证 Mac PATH 中存在 Python 3。真机编译需在 Xcode 选择自己的 Team / Bundle Identifier 并完成设备签名。未创建或声称已有分发证书、开发者资格、已签名应用或可安装链接。

5. 真机验收：启动须显示资源校验成功，完整面板能打开；所有 HTTP 仅走手机 `127.0.0.1`。当前无 iOS 采集接入时应显示等待真实数据，不能出现虚构战斗。检查 PiP 支持、切后台后的时间戳和恢复界面；原生依赖若导入失败应可见错误。此阶段仍不应开启 VPN。

前台 App 不使用 App Groups，默认没有配置该 entitlement；`RocoLocal.entitlements` 留作以后集成扩展时启用。扩展签名之前，应把两个 entitlement 文件中的 App Group 和 Bundle Identifier 换成自己账户允许的值，并在 App target 配置 entitlement，验证 App / Extension 具有相同 App Group 权限。

## iOS 游戏流量仍缺的部分

这部分**是实现缺口，并非只差签名**。目前没有完成 iOS `NEPacketTunnelFlow` ↔ 转发器适配、本机 SOCKS TCP/UDP/DNS 转发、后台扩展里的引擎生命周期、App/扩展认证 IPC 和真机登录链路校验。不能用同一套 Python 规则已经移植来证明 iOS 协议、密钥取得或游戏抓取已经成功；没有假设可以解密任意 TLS 流量。

已有 MIT 依赖 HEV `2.19.3` / commit `c5584feca8f6df70ee53eb2879e034b849a3d15a` 支持 Apple 构建，其公开 C API 接受 TUN 文件描述符，不能把它直接当成已经实现的 `NEPacketTunnelFlow` 集成。可在 Mac 用 `bash mobile/ios/scripts/build-hev.sh` 从已固定的本地 vendor 源生成候选 XCFramework，脚本在 `mobile/ios/build` 内构建；**生成库也不会开启 VPN**。不采用访问 `packetFlow.socket.fileDescriptor` 等私有 KVC 方法。

实际接通时应由扩展拥有全部本机转发和 Python 后台引擎，使用 Apple 的 `packetFlow.readPackets/writePackets` 公共 API 接入经过验证的有界报文适配器，再连接 HEV 和本机 SOCKS 服务。SOCKS 上游成功转发的有序字节，按每条 TCP flow 分别调用 `EngineBridge.feedFlow` / `roco_mobile.feed(flowId, remoteAddress, remotePort, "c2s"或"s2c", bytes)`，关闭时调用 `close_flow`；不能把 VPN 原始 IP 包或重传片段直接塞给 ordered-stream 接口。App 只通过同组、带认证的本机 IPC 读取快照。只有 TCP/UDP、DNS、IPv4/IPv6、错误退出、重连、队列溢出和真实登录采集都验证后，才嵌入扩展、配置路由并启用按钮。

## 当前验证边界与资料

Windows 已检查 Python 语法、XML plist/entitlement、工程对象引用和共享 scheme；没有 Xcode / iOS SDK / Swift 编译器，未编译 Swift、Objective-C、HEV，也未执行 PiP 或 iOS 原生 Python 导入。Windows/Android 的测试不能替代上述 iOS 验证。

- [CPython 3.13：嵌入 iOS、标准库、原生扩展 framework 包装与签名](https://docs.python.org/3.13/using/ios.html)
- [Python-Apple-support 项目](https://github.com/beeware/Python-Apple-support)
- [Apple：AVKit sample-buffer PiP ContentSource](https://developer.apple.com/documentation/avkit/avpictureinpicturecontroller/contentsource-swift.class/init%28samplebufferdisplaylayer%3Aplaybackdelegate%3A%29)
- [Apple：NEPacketTunnelProvider.packetFlow](https://developer.apple.com/documentation/networkextension/nepackettunnelprovider/packetflow)
- HEV 的本地固定版本、MIT 许可证和 C API：`../vendor/hev-socks5-tunnel/LICENSE`、`src/hev-main.h`。
