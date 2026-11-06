# 游戏配置加载、默认值与提取来源复核

日期：2026-10-25。复核对象为已有 `artifacts/unpack_probe_20261025` 及本轮新增加载依赖。游戏安装文件只读；没有执行游戏 Lua、启动游戏、连接服务端或改写原分析产物。

## 已确认的提取与解析完整性

重新使用保留的 Python 解析器读取全部 8 张原始 `.non` / `.bytes`，合计 **17,578 行**，与已有可读 JSON 逐值一致；包含字段缺失、数组顺序、嵌套字段及本地化 ID。没有重新生成或覆盖可读表。

复核四份原 manifest 的 **47 个提取文件**：payload SHA-256 全部吻合；其中 **25 个反编译结果**的记录哈希也吻合。只读重验 **47 段原 PAK 字节范围，共 4,254,768 字节**，哈希与 manifest 一致，每次读取前后包大小与修改时间未变。没有为此重新扫描约 65 GB 的包体。

保存的 `directory_search.json` 包含 330 包，主索引和完整目录索引验证字段均为 true。该全包结论来自已保存目录审计，本轮只重验上述选定数据范围，不能把它写成本轮重新验证全部索引。

原工具和 CUE4Parse 来源版本仍为提交 `460fc477bad0f9db3cfc387365a6699ee246377e`；工具、原字段结构、原表数据、已解析 JSON、加载脚本的当前 SHA-256 均附在 [JSON 证据](game-loading-review-20261025.json)。

## 文件选择与实际加载优先级

有候选列表的 manifest 项逐项核对最高数字 `_N_P.pak` 选择规则，均符合原选择策略。**这只证明候选选择一致，不证明引擎实际挂载顺序。** 不应根据 Unreal 的一般习惯替代当前游戏的加载证据。

`DataConfigManagerNew.luac.decompiled.lua` 第 84–93 行区分 `Data/Bin/BinData/` 与 `Data/Bin/BinDataCompressed/`，由原生 `IsCompressedBinDataEnabled()` 判断，并用对应 `.non` 注册配置。第 130 行的 `GlobalConfig.DisableBinData` 为真时回退基础 Lua 配置。补充提取的 `GlobalConfig` 第 99 行文件值确为 `DisableBinData=false`，它是所选文件中的配置值，不足以证明在线运行后永不改变。

`BinDataManager.luac.decompiled.lua` 的注册、加载、按索引/键读取等函数转调 `self.Overridden` 原生方法。Lua 索引调用显式减一，但 wrapper 没有给出压缩开关实现、字段缺失默认值或 PAK 优先级。`DataConfigManagerNew` 中的 editor_override 位于 IS_EDITOR 条件内，不能据此宣布正式 PVP 存在同样覆盖；ReloadTable 方法存在也不能证明它在在线对局何时被调用。

本轮安装目录的有限文件检查未取得当前运行的 PAK mount/lookup 追踪。在该安装 `Win64/NRC` 下没有 Saved 目录；未扩大读取账号日志或启动游戏制造运行记录。因此，实际挂载优先级、在线覆盖及最终有效配置仍列为未确认，而不是否定它们存在。

## 序列化缺失值与运行时默认值必须分开

`parse_roco_tables.py` 的 `parse_struct` 读取按高位到低位排列的字段存在位图，未置位即不写入输出字典；固定版本 `FRocoBinData.cs` 的 `ParseStruct` 同样跳过缺失字段。数组从常量区依次读取，保留包括零在内的参数位置，不排序、不去重。动态数组按字段 Size、固定数组按 4 字节步长，与所参考实现一致；每个数组和嵌套结构均检查消耗长度。

这证明 **序列化记录中缺失与显式零不同**，但还没有证明原生 FBinData/UBinDataManager 暴露给 Lua 时是否物化默认值。尤其不能将 `round_energy` 缺少 num 改成 num=0。

`DataConfigManagerEx` 第 29–46 行的数字/文本 getter 使用 `cfg and cfg.num/str or defaultValue`：只有 Lua 暴露值为 nil/false 才返回调用方默认值，数值 0 在 Lua 中为真。由于原生层可能先处理缺失，不能反向推断“压缩表缺字段必然触发 getter 默认值”。每个调用点及原生读取实现仍需继续追踪。

字段类型、参数数组长度和位置已可可靠读取，不等于 `energy_rule`、`cast_moment`、`trigger_type` 等业务值语义已确认；不同字段仍需独立枚举依据。

## 解析器畸形输入边界

发现一项明确的加固缺口：`Bin.read` 检查 n<0 和 p+n 超出文件，但没有检查 p<0；`entries` 又直接使用 footer offset。最小构造中 `b=b"abcd"; p=-2; read(1)` 会返回 `b"c"`，而不是拒绝负偏移。这是针对畸形输入的边界缺陷，**当前八表没有观察到由此造成的误读**，也不能仅凭现有表通过就宣称解析器对任意数据已安全完备。

未修改保留的旧工具。正式通用导入器后续应加入负偏移、footer 最小长度、数据/常量区边界与引用范围的显式校验；不得用容错补零掩盖损坏。

## 回归验证

新增 `tests/test_game_table_probe.py`，6 项通过（1.161 秒）：缺失与显式零、数组顺序含零、嵌套缺失、记录长度不符拒绝、未知类型/非法数组长度拒绝、八表完整重新解析。全部测试只读取已有产物，没有临时冒烟文件或游戏目录写入。

可信度：98/100（限已列文件与边界）。已确认：重新解析一致性、选定提取范围哈希、序列化缺失处理及加载分支源码。待核实：实际挂载优先级、原生缺失值物化、在线覆盖与最终模式适用性。疑似编造：无。
