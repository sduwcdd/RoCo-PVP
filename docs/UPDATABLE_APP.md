# Windows APP 构建与更新

当前使用不加密字节码、ZIP资源和未混淆前端，不再提供旧Cython/AES桌面保护入口。开发运行overlay，分享时生成NSIS包。资源完整性、来源身份、进程归属和管理员授权检查保留。

## 构建

Windows x64、Python3.13、Node.js/npm。运行依赖在.venv-rkpp，安装包使用隔离环境：

```powershell
py -3.13 -m venv .venv-release
.venv-release/Scripts/python.exe -m pip install -r requirements-release.txt
npm --prefix overlay ci
New-Item -ItemType Directory -Force artifacts/release-tools
Copy-Item scripts/release_tools.package.json artifacts/release-tools/package.json
Copy-Item scripts/release_tools.package-lock.json artifacts/release-tools/package-lock.json
npm --prefix artifacts/release-tools ci
.venv-release/Scripts/python.exe scripts/build_updatable.py --version 1.1.9 --id <唯一构建ID>
```

发布Electron固定45.2.1。新版本同步overlay/package.json、package-lock.json及update_config.json。完整构建包含当前后端、资源和桌面，不修改原工作区或自动上传。

只改桌面可使用 --reuse-backend <此前普通构建ID>。复用核对完成状态、后端文件清单及ZIP中的当前BWIKI身份；Python或资源变化时重建。

输出在dist/RocoPVP-<构建ID>-installer，含Setup、blockmap和latest.yml。日志与来源清单在artifacts/release_builds/<构建ID>，不进Git。

## 同仓库发布

源码与更新统一为sduwcdd/RoCo-PVP。APP更新、帮助、构建器和发布脚本均使用此地址，接收者无需令牌。旧RoCo-PVP-Releases不再作为更新源。

```powershell
.venv-release/Scripts/python.exe scripts/publish_app_update.py --build-id <构建ID> --dry-run
.venv-release/Scripts/python.exe scripts/publish_app_update.py --build-id <构建ID>
```

正式发布需所有者权限；令牌仅从本机凭据或临时环境读取。发布器检查桌面及哈希后上传同一构建的三个附件，构建本身始终 --publish never。无证书时程序未签名，下载哈希不替代发行者签名。

退出/更新先停止本APP采集、HUD和工作台；失败时保留APP并提示，不结束外部服务。旧更新源安装版需手动安装一次新源1.1.6，之后在设置内更新。

数据仍位于LOCALAPPDATA/RocoPVP，覆盖安装不主动删除配置或回放。手机版当前内部资源格式另行维护，不能以Windows验证替代手机实测。

## 应用内更新

Windows安装版启动时自动检查公开稳定版，连接控制台直接显示版本更新区。点击“一键更新并重启”后，依次检查版本、下载安装包、校验SHA-512、停止本APP后台、安装和重新启动。网络中断可重试，已校验文件由更新器缓存。源码开发入口继续使用本地代码。

安卓从0.10更新引导包开始提供“应用更新”。启动自动检查，点击下载后显示进度，完成长度、SHA-256、包名、版本和签名校验后可安装。系统需要用户允许此来源安装并确认；取消可重试。新旧APK使用同一签名时保留应用数据覆盖更新。

安卓发布使用同一仓库的android-v版本预发布，与Windows稳定更新分开。将构建APK交给下列命令，自动从APK提取并校验身份，生成android-update.json，先上传草稿全部附件并核对GitHub摘要，再公开预发布：

```powershell
.venv-release/Scripts/python.exe scripts/publish_mobile_update.py --apk mobile/build/roco-mobile-android-internal-0.11.apk --dry-run
.venv-release/Scripts/python.exe scripts/publish_mobile_update.py --apk mobile/build/roco-mobile-android-internal-0.11.apk
```

发布设备应持续使用相同签名文件，私钥保存在本机。更新清单包含versionCode、versionName、packageName、minSdk、apk、sha256、size、signerSha256。普通用户从APP下载，开发者发布时使用本机GitHub凭据。
