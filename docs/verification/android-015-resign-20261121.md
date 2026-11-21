# 安卓 0.15 原签名重发

日期为 2026-11-21。
本轮同步了 GitHub 最新源码。
源码基于提交 `6630125`。
该提交包含变动上行头字段的修复。

发布版本名为 `0.15-internal`。
内部版本号为 `17`。
该号码高于源码原有的 `16`。
构建身份为 `mobile-20261121-015-resigned`。

## 签名

本轮沿用 0.14 的签名私钥。
本轮核对了原密钥的证书摘要。
证书 SHA-256 为

```text
b6a6896a62a5d84a377b064e745f4d492d551e89272db10b26894aa2289b19f2
```

私钥副本保存在项目本地。
路径为 `archive/android-signing/debug.keystore`。
Git 忽略规则覆盖该私钥。
本轮通过 Gradle 初始化脚本指定该私钥。

已安装原签名 0.14 的用户可覆盖更新。
错签 0.15 的用户需要重新安装。
这些用户应先备份应用数据。
Android 使用签名校验覆盖安装。
依据见[官方签名说明](https://developer.android.com/studio/publish/app-signing)。

## 构建环境

项目位于 `F:/codex_workspace/roco_pvp`。
JDK 位于 `F:/Android/jdk-21`。
SDK 位于 `F:/Android/Sdk`。
Gradle 缓存位于 `F:/gradle`。
本轮临时目录位于项目 `.tmp/resign-015`。
CNB 发布临时文件也改用项目 `.tmp/`。

## 验证

16 项封装定向检查通过。
Gradle 签名报告匹配原证书。
最终 APK 的证书也匹配原证书。
包名为 `cn.roco.mobile`。
包内解析器源码摘要匹配当前源码。
APK 编译后端通过 16 项封装检查。
PVE 后端启动检查通过。
CNB 发布器的 2 项检查通过。
这些验证均在本机执行。
真机安装后的表现仍需用户验证。

APK 路径为

```text
mobile/build/roco-mobile-android-internal-0.15.apk
```

APK 大小为 `181636434` 字节。
APK 的 SHA-256 为

```text
3a381c3955dafb498a2bf472e55ff3b2c2a84846076acce2ff2a777a540ba77e
```

验证记录位于 `mobile/build/`。
签名记录为 `android-0.15-verification.json`。
后端记录为 `android-0.15-resign-runtime.json`。
构建日志为 `android-0.15-build.log`。
