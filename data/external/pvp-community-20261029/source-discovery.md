# 热门整队数据源调查（2026-10-29）

结论：**未取得完整六只配队，当前可训练完整整队记录数为 0。** 此目录的 `popular-*.raw.json` 是保留的 HTTP 426 错误响应，不能导入为训练数据。

## 可复核来源与阻断

- 本地只读程序集：`E:/洛克PVP助手/app/RocoSandbox.Native.dll`，ProductVersion `1.0.54`，SHA256 `99b13757d0aadf02dfc054556c9ea8f0777fcca8b7df76d8c415bd3ed46d3611`。
- `RocoAuthClient.GetPopularTeamsAsync` 指向 `http://server.hairuosky.cn:30006/api/popular-teams?limit=80`。
- 社区网页源码指向同基址的 `/api/recommendations`，与热门统计接口不同。
- 不带版本头的请求返回 `client_update_required`。按构造器设置真实版本与本机 DLL SHA256 后，两个接口均返回 HTTP 426 `client_integrity_failed`。直连亦复现。
- 正常 `ResolveClientSha256` IL 路径取入口程序集 `Location` 的 SHA256。未使用网络测试分支、伪造被接受的哈希、账号令牌或其他认证规避。真实请求及原始响应散列见 `popular-*-fetch.json`。
- 对 app 内文件名、WebView2 的精确配队字段、pokedex-api-cache、日志及本项目 vendor 副本的定向扫描，没有发现 `popular_teams_cache.json` 或完整 team/build 数据。没有运行或修改助手。

## 本地缓存读取器接受的结构

以下是**由 IL 读取逻辑推导的结构示意，不是真实配队样本**。根可以是数组，也可以是含 `items` 数组的对象：

```text
items[]
  id                            ReadJsonString
  favoriteCount / likes         TryReadInt
  snapshot
    team
      name                      ReadJsonString，空名跳过
      description               ReadJsonString
      gameTeamCode              ReadJsonString
      tags                      ReadJsonStringArray
    builds[]                    BuildPopularTeamPet；最多读取 6 项
      name                      ReadJsonString
      petbaseId                 ReadJsonString
      creatureId                ReadJsonString
      bloodline.name            ReadJsonString
      level                     ReadJsonString
      selectedSkillNames[]      ReadJsonStringArray
      selectedSkillIds[]        ReadJsonLongArray；为空时尝试按名称解析
      statMarks
        extremeStat             ReadJsonString，再转换属性名
        minusStat               ReadJsonString，再转换属性名
        plusStats[]             ReadJsonStringArray，再转换属性名
```

这里记录的是读取器调用类型，并未获得真实 JSON 样本来验证各字段编码。读取器最多取六项，不保证原始记录恰好六只。`plusStats` 是加点方向名称列表，所检查的读取逻辑没有直接读取各属性数值，不能仅凭名称列表断言具体加点量。

## 远端热门统计与完整配队的区别

`MapServerPopularTeam` 读取的 CLR 属性是 `Key / Rank / Appearances / Pets / PetIds`。映射宠物时只设置 `Name / AvatarUri`，没有设置技能、血脉、等级、加点或游戏队码。由于请求被拒绝，实际远端 JSON 键名和返回内容尚未验证；不能把本地 snapshot/builds 结构当作该接口已返回的结构。

## 训练接入所缺数据

需要可验证的真实六只组合及每只四槽技能、性格方向/血脉、明确加点配置，或可解码且字段足够的真实队码。当前既无六只完整记录，也无成功远端响应。不得用单精灵边际使用率拼队，或把八个技能候选截取四个当真实配招。训练端应对空池明确失败。

完整机器可读说明见 `source-discovery.json`，对应静态 IL 证据见 `source-discovery.il.txt`。本次只使用已安装 .NET 元数据读取能力，无新增依赖；临时静态读取脚本已删除。

## 独立备选来源的限量检查

公开 https://roco-showdown.com/teams 返回 HTTP 200，页面提供个人/共享阵容界面，但初始 HTML 没有完整阵容记录。本次检查页面入口及直接引用的阵容组件，没有找到直接公开 API 地址或完整配置数据，按限定范围停止；不能据此断言站点不存在共享队伍。取得完整队伍仍为 0。页面、相关脚本原文和抓取 SHA/时间保存在独立的 `roco-showdown-popular-*` 文件中，未冒充指定助手数据，也未登录或绕过限制。
