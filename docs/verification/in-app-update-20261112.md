# 应用内更新验证

日期为2026-11-12。Windows版本1.1.9，安卓更新引导包0.10与更新版0.11。

## 已实现

Windows安装版启动检查稳定版本，控制台直接显示更新区。“一键更新并重启”串行执行检查、下载、SHA-512校验、后台清理、NSIS安装与重新启动。更新失败可重试，已有校验缓存由electron-updater管理。源码开发入口继续加载本地源码。

安卓启动检查同仓库的android-v预发布，按versionCode选择具有android-update.json的更新。下载限制目标仓库与HTTPS跳转，校验长度、SHA-256、应用包名、版本、最低SDK及与已安装应用相同的签名。校验成功后通过只读Provider交给系统安装器。来源授权、用户取消、进程重启后的缓存恢复均有可重试入口。

发布脚本从实际APK读取并验证签名与版本，生成清单，上传全部草稿附件并核对GitHub摘要后再公开预发布。Windows使用稳定版本及latest.yml。安卓预发布保留prerelease标记，未改变Windows稳定更新指向。

## Windows实际测试

使用本机保留的1.1.6安装构建作为受测基线，调用生产DesktopUpdater和electron-updater访问真实GitHub，下载252000033字节的1.1.9安装包。下载SHA-512与公开latest.yml相同。真实NSIS安装、自动重新打开APP、已安装release.json版本1.1.9、后台源码身份以及用户目录测试数据保留均已核对。

初次测试探针传入正斜线格式的自定义安装目录，造成测试安装位置异常。已恢复正确的本机安装目录，移除探针中的自定义目录，以生产默认目录行为重新从1.1.6基线完成升级。应用更新实现没有添加自定义安装目录覆盖。

安装包自身另通过真实控制台启动、IPC、图标、工作台加载及更新区渲染检查。记录保存在artifacts/release_builds/20261112-inapp-update-119-final/desktop-verification.json和update-verification.json，下载收据位于本机workspace/.codex-tmp/desktop-update-e2e/receipt.json。

## Android实际测试

在API36模拟器中安装同签名的0.10更新引导包，从生产GitHub接口发现0.11，真实下载165280234字节并完成全部校验。APK SHA-256为dc3b5eb1a5b789e66bf3f6e7d6dac91ab2449f9cb76fcf973e3711e67c699102。

- 真实下载和校验约32.6秒。
- 实际打开系统来源授权页，授权后取消系统安装，缓存与安装重试入口保留。
- 强制停止后重新打开，恢复已校验缓存并核对两份测试数据。
- 通过系统Update确认实际覆盖安装。安装中旧instrumentation进程被替换终止，随后由外部独立核对versionCode11、versionName0.11-internal及已安装APK摘要。
- 文件与SharedPreferences两份测试数据均保留。重新打开后的真实页面显示0.11-internal及“已是最新版本”。

模拟器经主机现有代理访问GitHub，生产URL及TLS校验保持启用。此前DNS失败和直连被重置均显示为可重试错误。真机网络及厂商安装交互仍由用户验证。

设备记录与截图保存在mobile/build/android-inapp-update-verification.json、update-source-permission.png和update-after-version.png。临时升级探针源码、设备测试包及测试数据已在取证后删除。

## 定向检查与发布

17项桌面更新及移动界面检查、4项Android设备校验测试通过。覆盖未完成校验时阻止安装、网络错误重试、并发排斥、包名与签名拒绝、截断及错误摘要、只读Provider边界。

- Windows发布为https://github.com/sduwcdd/RoCo-PVP/releases/tag/v1.1.9。
- 安卓引导包发布为https://github.com/sduwcdd/RoCo-PVP/releases/tag/android-v0.10.0-internal。
- 安卓更新版发布为https://github.com/sduwcdd/RoCo-PVP/releases/tag/android-v0.11.0-internal。

0.10引导包和0.11使用本机相同测试签名。此前由另一台设备签名的APK需要迁移原私钥，或先保存所需数据后重新安装本机签名引导包，后续同签名更新可保留数据覆盖安装。Android安装需要用户在系统页面确认。
