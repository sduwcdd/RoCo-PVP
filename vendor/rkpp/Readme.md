# 抓包与协议解析模块

面向战斗协议的抓包、解密、离线复现与实时解析模块。

---

## 当前能力

- 抓取 0x1002 会话 key，并用于 0x4013 报文解密。
- 自动持久化最新 key 到 `Key\latest.key`，收到新的 `0x1002` 时自动刷新当前 flow key。
- 支持 live 抓包、离线 pcap 回放、协议实时解析和 relay server。
- 支持列出、显示和设置默认网卡；也可以在命令行中显式指定网卡。
- 支持 `Ivdecoder` 单路径 0x4013 解密：AES-CBC 固定 IV、完整 plaintext、TSF4G trailer 校验。
- 支持 TGCP internal header、payload 原文保留和 schema/payload 双路径解码。
- 保留高语义战斗 opcode 的手写摘要，用于回合、技能、伤害、能量、换人、道具和战斗结束分析。

---

## 文件说明

- `rkpp_live_tools.py`：命令行入口，提供抓 key、实时解码、协议分析和 relay。
- `rkpp_analyzer.py`：抓包流重组、解密调度、协议解析和摘要分发。
- `rkpp_proto.py`：TGCP、protobuf wire、TSF4G trailer 与记录解析。
- `rkpp_proto_core.py`：传输/布局解析、proto-tree 基础原语与内层 message 解析。
- `rkpp_proto_battle.py`：战斗协议语义抽取。
- `rkpp_network.py`：网络流识别、key 处理和 0x4013 解密。
- `rkpp_analysis.py`：opcode/schema 查询、字段树解码、payload codec fallback 和名称增强。
- `rkpp_codec.py`：从 RocoMITMServer 接入的通用 protobuf codec。
- `rkpp_opcode_payload.py`：从 RocoMITMServer 接入的 opcode payload decoder。
- `rkpp_io.py`：CSV、summary、离线 pcap 输入与会话日志。
- `rkpp_reporter.py`：协议实时摘要输出。
- `rkpp_relay.py`：本地 HTTP NDJSON relay server。
- `rkpp_game_process.py`：游戏进程检测与密钥失效处理。
- `Data.py`：数据加载入口，优先读取 `rkpp_data.sqlite`。
- `rkpp_data.sqlite`：统一运行时数据包。
- `RKPP_worker.py`：抓包 worker，按序消费嗅探回调入队的报文。

> 其中 `rkpp_codec.py` 与 `rkpp_opcode_payload.py` 为从 **RocoMITMServer** 接入的第三方实现，
> 版权与授权归其原作者，不属于本项目原创部分。

---

## 依赖安装

建议使用 Python 3.11 或更新版本：

```powershell
python -m pip install -r requirements.txt
```

实时抓包还需要系统侧抓包驱动与权限，例如 Windows 上的 Npcap。离线 pcap 回放和数据刷新不需要打开实时抓包接口。

---

## 基本使用

列出网卡：

```powershell
python rkpp_live_tools.py --list-ifaces
```

设置默认网卡：

```powershell
python rkpp_live_tools.py --set-default-iface WLAN
python rkpp_live_tools.py --show-default-iface
```

抓取 key：

```powershell
python rkpp_live_tools.py capture-key --iface 以太网 --port 8195 --out-dir runs\key_capture
```

抓到的 `0x1002` 会话 key 会同时写入本次输出目录的 `key.txt`，以及项目根目录下的 `Key\YYYYMMDD_HHMMSS.key` 和 `Key\latest.key`。实时解码、协议解析和 relay 命令在未提供 `--key` 时会优先读取 `Key\latest.key`，后续收到新的 `0x1002` 时自动刷新当前 flow key 并更新 Key 目录。

实时协议解析：

```powershell
python rkpp_live_tools.py analyze --iface 以太网 --port 8195 --out-dir runs\analyze
```

离线 pcap 回放：

```powershell
python rkpp_live_tools.py analyze --read-pcap capture.pcap --key <16字节ASCII或32位hex> --out-dir runs\offline
```

---

## 用途与免责

本模块仅供内部使用。请自行确认使用行为是否符合适用法律法规、服务条款、用户协议、EULA 与第三方权利要求。

本模块按“**原样**”（**AS IS**）提供，不附带任何明示或默示担保。因使用、修改、分发或部署本模块所导致的任何直接或间接后果，均由使用者自行承担。
