# 国内安装包与更新源

国内下载入口为 https://cnb.cool/sduwcgg/roco-pvp 。该仓库托管安装包、校验信息和更新指针，GitHub继续维护项目源码及备用发行版。

## APP行为

Windows安装版优先使用CNB公开文本更新源，检查失败时尝试GitHub备用源。下载安装包始终绑定成功检查时选中的来源，保留electron-updater的SHA-512校验、后台清理与安装重启。

安卓优先读取CNB的latest.json，校验固定仓库地址与完整元数据。有效且已最新的指针直接结束检查；不可用或无效时尝试GitHub。APK继续校验长度、SHA-256、包名、版本和安装签名，并由用户在系统页面确认安装。

两个公开指针为：

- https://cnb.cool/sduwcgg/roco-pvp/-/git/raw/main/updates/windows/latest.yml
- https://cnb.cool/sduwcgg/roco-pvp/-/git/raw/main/updates/android/latest.json

用户下载与检查更新使用公开raw/download地址。发布维护使用CNB OpenAPI和仓库读写授权，客户端没有访问令牌配置。

## 发布

在本机设置CNB_TOKEN环境变量，或使用被Git忽略的.env.cnb / cnb.txt保存发布令牌。令牌限定资源仓库，权限为基本信息读取、代码读写和发行版读写。

```powershell
$env:JAVA_HOME = 'E:/Java/jdk21'
$env:ANDROID_HOME = 'C:/Users/86195/AppData/Local/Android/Sdk'
.venv-release/Scripts/python.exe scripts/publish_cnb_updates.py --desktop-build-id 20261112-cnb-1110 --apk mobile/build/roco-mobile-android-internal-0.12.apk
```

脚本先核对Windows构建收据及APK签名和版本，上传到版本化草稿，核对服务端SHA-256与字节长度，再公开发行。随后在一次Git提交中更新公开指针及README下载链接。发布已存在的相同附件可重试，同名而内容不同的附件报错。只发布某个平台时保留另一平台的指针与下载入口。

新APK持续使用本机同一签名，签名材料由开发设备保管。Windows构建说明见UPDATABLE_APP.md，安卓构建说明见../mobile/README.md。

## 访问与来源

2026-11-12已核实公开仓库可匿名读取，安装包下载从cnb.cool跳转到asset.cnb.cool。原生HTTP客户端保留HTTPS及来源域名检查。发布器读回指针时禁用环境代理，核对远程与本地指针字节相同。

本轮设备与实际更新验证见verification/cnb-updates-20261112.md。
