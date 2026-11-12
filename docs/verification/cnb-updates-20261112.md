# CNB国内更新源验证

日期为2026-11-12。仓库为https://cnb.cool/sduwcgg/roco-pvp。

## 发布与公开访问

已使用仓库限定凭据初始化资源仓库并发布Windows1.1.10、Android0.12。安装包及元数据先上传版本化草稿，核对CNB返回的SHA-256和长度后公开，最后用一次Git提交激活公开更新指针。只更新一个平台时保留另一平台的入口。

发布API需要维护者授权。APP使用的公开raw与download地址已经在无访问令牌、禁用代理的客户端中验证。下载跳转为cnb.cool到asset.cnb.cool，HTTPS和来源域名检查保持启用。Windows公开下载还核对了HTTP206及Range字节范围支持。

公开指针为：

- https://cnb.cool/sduwcgg/roco-pvp/-/git/raw/main/updates/windows/latest.yml
- https://cnb.cool/sduwcgg/roco-pvp/-/git/raw/main/updates/android/latest.json

发布器匿名读回指针并核对字节摘要。安装包链接位于仓库README及对应发行版。发布凭据文件cnb.txt被Git忽略，资源发布清单使用明确的构建附件路径。

## Windows实际更新

以本机实际已安装1.1.9身份驱动新版本生产DesktopUpdater和electron-updater，显式禁用Electron代理，读取CNB指针后确认source为cnb。真实下载252000441字节的1.1.10安装包，SHA-512与国内指针完全一致。

通过真实NSIS执行安装并自动重新打开APP，外部核对已安装release.json版本1.1.10、构建20261112-cnb-1110及后台源码身份相符。用户目录中的测试数据保留。本次使用生产默认安装目录，没有覆盖安装目录参数。

新版打包程序另通过真实控制台启动、IPC、图标、工作台加载及更新区渲染检查。记录保存在artifacts/release_builds/20261112-cnb-1110/desktop-verification.json和cnb-update-verification.json。

## Android实际更新

使用API36模拟器。基线为带国内更新入口的专用11构建，目标为公开0.12版本，双方沿用本机相同签名。模拟器冷启动前清空代理环境变量，Android系统代理为:0。

生产AppUpdater从固定CNB指针发现12，更新来源保持CNB，直接下载完整165297194字节，完成长度、SHA-256、包名、版本、最低SDK和安装签名校验。此轮检查、下载及校验约242.9秒。最初继承了宿主代理环境的启动轮次已作废，未计为直连验证结果。

两次系统安装取消及重试通过，强制停止后恢复已校验缓存。随后通过系统Update确认覆盖安装。旧instrumentation因自身被替换而终止，成功判据由外部独立取得：versionCode12、versionName0.12-internal、已安装APK摘要，以及文件和SharedPreferences两类测试数据均保留。

已安装APK的SHA-256为468f9d9d4cfe96a620986812cb9d18da24eda589bac3404304725ebe94ede25b。外部核对系统代理仍为:0。最终页面与清理结果记录在mobile/build/cnb-update-verification.json，临时升级探针及测试数据在取证后清理。

## 定向检查

19项桌面更新与移动界面检查、2项发布器检查、7项Android设备检查通过，覆盖国内源优先、已最新时终止查询、失败回退、下载来源绑定、固定仓库和HTTPS限制、文件及签名校验、并发保护和取消重试。

## 使用边界

旧安装包中的更新地址需要安装新版后生效。GitHub无法访问时，首次从国内仓库手动下载Windows1.1.10或安卓0.12，后续由APP检查国内更新。安卓系统安装确认继续由用户完成，已有应用应使用相同签名。

Windows已经在本机实际安装验证。安卓实际更新使用模拟器，具体手机的网络及厂商安装交互仍待用户反馈。测试未修改战斗数值、结算规则或游戏采集逻辑。
