#!/usr/bin/env python3

"""抓包工具入口。

子命令：
  capture-key    抓取首个 0x1002 key，输出 key.txt
  live-decode    持续抓包解密，导出 CSV
  analyze        持续抓包 + 协议实时解析 + CSV

无子命令时进入交互式菜单。
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import threading
import time
from pathlib import Path

from scapy import __version__ as scapy_version  # type: ignore
from scapy.all import AsyncSniffer, PcapWriter, conf  # type: ignore

from rkpp_analyzer import RkppAnalyzer
from rkpp_io import (CsvSink, MoveCsvSink, SessionLogger, ensure_output_dir,
                      iter_offline_packets, prompt_menu, prompt_server_mode, prompt_text)
from rkpp_network import (capture_iface_candidates, get_default_iface, get_default_route_iface,
                          iface_should_skip, iter_ifaces, latest_key_path, list_ifaces,
                          load_latest_key, packet_has_target_port, parse_key_text, set_default_iface)
from rkpp_relay import OpcodeRelayServer
from rkpp_reporter import ProtocolConsoleReporter
from RKPP_worker import RKPP_PacketWorker

DEFAULT_PORT = 8195
_BAD_KEY_EXIT_CODE = 2
_CAPTURE_DIAG_INTERVAL = 30.0
_CAPTURE_START_WARNING_SECONDS = 5.0

# 子命令配置：command -> (prefix, needs_csv, needs_reporter, stop_after_key)
_COMMAND_CONFIG = {
    "capture-key":    ("rkpp_key_capture",     False, False, True),
    "live-decode":    ("rkpp_live_decode",      True,  False, False),
    "analyze":        ("rkpp_analyze",          True,  True,  False),
    "opencode-server":("rkpp_opencode_server",  True,  False, False),
}

_INTERACTIVE_COMMANDS = {
    "1": "capture-key",
    "2": "live-decode",
    "3": "analyze",
    "4": "opencode-server",
}


# ---------------------------------------------------------------------------
# 统一抓包主循环
# ---------------------------------------------------------------------------

def _capture_diag_log(logger: SessionLogger, event: str, **fields) -> None:
    try:
        logger.log("[capture-diag] " + json.dumps(
            {"version": 1, "event": event, **fields}, ensure_ascii=False, separators=(",", ":"),
        ))
    except Exception:
        # Optional diagnostics must not change packet handling if the log disk fails.
        pass


def _capture_error(exc: Exception) -> dict:
    # Never persist arbitrary exception text, source lines, locals or chained
    # messages: any of them could contain a key or packet body without a label.
    result = {
        "type": type(exc).__name__, "message": "Exception text omitted; see system codes and traceback frames",
        "errno": None, "winerror": None, "traceback": [],
    }
    for name in ("errno", "winerror"):
        try:
            value = getattr(exc, name, None)
            if type(value) is int:
                result[name] = value
        except Exception:
            pass
    try:
        if result["winerror"] is not None and sys.platform == "win32":
            import ctypes
            result["message"] = ctypes.FormatError(result["winerror"]).strip()
        elif result["errno"] is not None:
            result["message"] = os.strerror(result["errno"])
    except Exception:
        pass
    try:
        tb = exc.__traceback__
        while tb is not None:
            code = tb.tb_frame.f_code
            result["traceback"].append({
                "file": Path(code.co_filename).name, "function": code.co_name, "line": tb.tb_lineno,
            })
            if len(result["traceback"]) > 6:
                del result["traceback"][0]
            tb = tb.tb_next
    except Exception:
        pass
    return result


def _log_capture_environment(logger: SessionLogger, targets: list, port: int, no_bpf: bool) -> None:
    admin = None
    if sys.platform == "win32":
        try:
            import ctypes
            admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            pass
    _capture_diag_log(
        logger, "environment", python=sys.version.split()[0], python_bits=struct.calcsize("P") * 8,
        platform=sys.platform, scapy_version=scapy_version, is_admin=admin,
        scapy_use_pcap=getattr(conf, "use_pcap", None),
        scapy_use_npcap=getattr(conf, "use_npcap", None),
        target_port=port, bpf=None if no_bpf else f"tcp port {port}",
        counter_scope="TCP target-port packets after the existing filters; not all NIC traffic",
        relay_health_is_capture_health=False,
    )
    try:
        _capture_diag_log(logger, "default_route", iface=get_default_route_iface())
    except Exception as exc:
        _capture_diag_log(logger, "default_route_error", error=_capture_error(exc))
    try:
        for name, description in iter_ifaces():
            _capture_diag_log(
                logger, "interface", iface=name, description=description,
                excluded_by_auto_rule=iface_should_skip(name, description), selected=name in targets,
            )
    except Exception as exc:
        _capture_diag_log(logger, "interface_inventory_error", error=_capture_error(exc))
    _capture_diag_log(logger, "selected_interfaces", interfaces=targets)


class _CaptureProbe:
    """Per-sniffer counters only: no per-packet logging or packet retention."""

    def __init__(self, iface, port: int, no_bpf: bool, submit) -> None:
        self.iface = iface or "<scapy-default>"
        self.port = port
        self.bpf = None if no_bpf else f"tcp port {port}"
        self.created_at = time.monotonic()
        self.ready = threading.Event()
        self.ready_at = None
        self.target_packets = 0
        self.submitted_packets = 0
        self.submit_errors = 0
        self.last_submit_error = None
        self._submit = submit

    def started(self) -> None:
        # Scapy calls this only after capture sockets are opened.
        self.ready_at = time.monotonic()
        self.ready.set()

    def received(self, packet) -> None:
        # The existing BPF/lfilter still decides which packets arrive here.
        # A snapshot can temporarily show received > submitted if the queue blocks.
        self.target_packets += 1
        try:
            self._submit(packet)
        except Exception as exc:
            self.submit_errors += 1
            # Store sanitized text, not an exception traceback retaining the packet.
            self.last_submit_error = _capture_error(exc)
            raise
        self.submitted_packets += 1

    def snapshot(self, sniffer) -> dict:
        thread = getattr(sniffer, "thread", None)
        alive = bool(thread and thread.is_alive())
        error = getattr(sniffer, "exception", None)
        state = "failed" if error is not None else (
            "stopped" if thread is not None and not alive else "ready" if self.ready.is_set() else "starting"
        )
        return {
            "iface": self.iface, "target_port": self.port, "bpf": self.bpf, "state": state,
            "thread_alive": alive, "running_flag": bool(getattr(sniffer, "running", False)),
            "ready_callback_seen": self.ready.is_set(),
            "startup_ms": round((self.ready_at - self.created_at) * 1000, 1) if self.ready_at is not None else None,
            "target_packets": self.target_packets, "submitted_packets": self.submitted_packets,
            "submit_errors": self.submit_errors,
        }


class _CaptureMonitor:
    def __init__(self, logger: SessionLogger, analyzer, worker) -> None:
        self.logger = logger
        self.analyzer = analyzer
        self.worker = worker
        self.last_summary = time.monotonic()
        self.states = {}
        self.slow_starts = set()
        self.first_packets = set()
        self.submit_failures = set()
        self.monitor_error_logged = False

    def poll(self, sniffers: list, *, summary: bool = False, phase: str = "running") -> None:
        try:
            self._poll(sniffers, summary=summary, phase=phase)
            self.monitor_error_logged = False
        except Exception as exc:
            if not self.monitor_error_logged:
                self.monitor_error_logged = True
                _capture_diag_log(self.logger, "monitor_error", error=_capture_error(exc))

    def _poll(self, sniffers: list, *, summary: bool, phase: str) -> None:
        snapshots = []
        now = time.monotonic()
        for label, sniffer in sniffers:
            probe = sniffer._rkpp_capture_probe
            data = probe.snapshot(sniffer)
            snapshots.append(data)
            identity = id(sniffer)
            if self.states.get(identity) != data["state"]:
                self.states[identity] = data["state"]
                error = getattr(sniffer, "exception", None)
                _capture_diag_log(
                    self.logger, "thread_state", **data,
                    error=_capture_error(error) if error is not None else None,
                )
            if data["state"] == "starting" and now - probe.created_at >= _CAPTURE_START_WARNING_SECONDS and identity not in self.slow_starts:
                self.slow_starts.add(identity)
                _capture_diag_log(self.logger, "startup_pending", **data, elapsed_seconds=round(now - probe.created_at, 1))
            if probe.target_packets and identity not in self.first_packets:
                self.first_packets.add(identity)
                _capture_diag_log(self.logger, "first_target_packet", **data)
            if probe.submit_errors and identity not in self.submit_failures:
                self.submit_failures.add(identity)
                _capture_diag_log(self.logger, "submit_error", **data, error=probe.last_submit_error)
        if summary or now - self.last_summary >= _CAPTURE_DIAG_INTERVAL:
            self.last_summary = now
            _capture_diag_log(
                self.logger, "summary", phase=phase, interfaces=snapshots,
                ready_threads=sum(s["state"] == "ready" for s in snapshots),
                target_packets=sum(s["target_packets"] for s in snapshots),
                submitted_packets=sum(s["submitted_packets"] for s in snapshots),
                analyzer_entered_packets=getattr(self.analyzer, "packet_count", None),
                decoded_rows=getattr(self.analyzer, "decoded_rows", None),
                parsed_business_records=getattr(self.analyzer, "parsed_business_records", None),
                key_hits=getattr(self.analyzer, "key_hits", None),
                worker_errors=getattr(self.worker, "errors", None),
            )


def _start_iface_sniffer(iface: str | None, port: int, worker: RKPP_PacketWorker, no_bpf: bool):
    bpf = None if no_bpf else f"tcp port {port}"
    probe = _CaptureProbe(iface, port, no_bpf, worker.submit)
    sniffer = AsyncSniffer(
        iface=iface, store=False, prn=probe.received, started_callback=probe.started,
        lfilter=lambda pkt: packet_has_target_port(pkt, port), filter=bpf,
    )
    sniffer._rkpp_capture_probe = probe
    sniffer.start()
    return sniffer


def _open_iface_sniffer(iface: str | None, port: int, worker: RKPP_PacketWorker, no_bpf: bool, logger: SessionLogger):
    label = iface or "<scapy-default>"
    try:
        return _start_iface_sniffer(iface, port, worker, no_bpf)
    except Exception as first:
        _capture_diag_log(logger, "start_call_error", iface=label, no_bpf=no_bpf, error=_capture_error(first))
        if not no_bpf:
            logger.log(f"[iface] {label} bpf failed, retry without bpf: {first}")
            try:
                return _start_iface_sniffer(iface, port, worker, True)
            except Exception as second:
                _capture_diag_log(logger, "start_call_error", iface=label, no_bpf=True, error=_capture_error(second))
                logger.log(f"[iface] failed {label}: {second}")
                return None
        logger.log(f"[iface] failed {label}: {first}")
        return None


def _run_session(analyzer: RkppAnalyzer, args: argparse.Namespace) -> None:
    if args.read_pcap:
        for frame_no, pkt in iter_offline_packets(args.read_pcap):
            analyzer.process_packet(pkt, frame_no)
            if analyzer.should_stop:
                break
        return
    worker = RKPP_PacketWorker(analyzer, analyzer.session_logger)
    worker.start()
    sniffers: list[tuple[str, object]] = []
    logger = analyzer.session_logger
    monitor = _CaptureMonitor(logger, analyzer, worker)
    iface_only = bool(getattr(args, "iface_only", False) and getattr(args, "iface", None))
    if iface_only:
        targets = [args.iface]
        logger.log(f"[iface] single-iface mode {args.iface}")
    else:
        preferred = getattr(args, "preferred_iface", None) or getattr(args, "iface", None) or get_default_iface()
        try:
            targets = capture_iface_candidates(preferred)
        except Exception as exc:
            _capture_diag_log(logger, "interface_selection_error", error=_capture_error(exc))
            raise
        if not targets:
            targets = [None]
        logger.log(
            "[iface] auto-capture "
            + (f"preferred={preferred} " if preferred else "")
            + f"candidates={','.join(str(item or '<scapy-default>') for item in targets)}"
        )
    _log_capture_environment(logger, targets, args.port, bool(args.no_bpf))
    for iface in targets:
        sniffer = _open_iface_sniffer(iface, args.port, worker, bool(args.no_bpf), logger)
        if sniffer is not None:
            label = iface or "<scapy-default>"
            sniffers.append((label, sniffer))
            logger.log(f"[iface] starting on {label}; waiting for capture-ready callback")
    monitor.poll(sniffers, summary=True, phase="startup")
    if not sniffers:
        worker.close()
        raise RuntimeError(
            "no capture interface could be opened; run as Administrator and reinstall Npcap with WinPcap compatible mode"
        )
    try:
        while not analyzer.should_stop:
            monitor.poll(sniffers)
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        monitor.poll(sniffers, summary=True, phase="stopping")
        for label, sniffer in sniffers:
            try:
                sniffer.stop()
            except Exception as exc:
                _capture_diag_log(logger, "stop_error", iface=label, error=_capture_error(exc))
        _capture_diag_log(logger, "worker_closing", worker_errors=worker.errors)
        worker.close()
        monitor.poll(sniffers, summary=True, phase="closed")


class _MultiListener:
    def __init__(self, *listeners) -> None:
        self.listeners = [listener for listener in listeners if listener is not None]

    def handle(self, row_index: int, row: dict, parsed_info: dict) -> None:
        for listener in self.listeners:
            listener.handle(row_index, row, parsed_info)


def _close_optional(resource: object | None) -> None:
    if resource is None:
        return
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def _resolve_runtime_iface(args: argparse.Namespace) -> str | None:
    if getattr(args, "read_pcap", None):
        return getattr(args, "iface", None)
    preferred = getattr(args, "iface", None) or get_default_iface()
    args.preferred_iface = preferred
    if bool(getattr(args, "iface_only", False)):
        args.iface = preferred
        return preferred
    # Native starts without --iface. Do not lock onto the saved NIC name.
    return preferred


def _load_preset_key(
    args: argparse.Namespace,
    command: str,
    session_logger: SessionLogger,
) -> bytes | None:
    if hasattr(args, "key") and args.key:
        key = parse_key_text(args.key)
        session_logger.log(f"[key] using provided key key_hex={key.hex()}")
        return key
    if command == "capture-key":
        return None
    if command == "opencode-server" and not getattr(args, "allow_stale_key", False):
        session_logger.log("[key] live relay waiting for fresh 0x1002 key refresh")
        return None
    key = load_latest_key()
    if key:
        session_logger.log(f"[key] loaded latest key from {latest_key_path()} key_hex={key.hex()}")
        return key
    session_logger.log("[key] no preset key; waiting for 0x1002 key refresh")
    return None


def _session_exit_code(
    command: str,
    analyzer: RkppAnalyzer,
    *,
    preset_key: bytes | None,
    session_logger: SessionLogger,
) -> int:
    if command == "capture-key":
        return 0 if analyzer.key_hits > 0 else 1
    if (
        preset_key is not None
        and analyzer.business_frames_seen > 0
        and analyzer.parsed_business_records == 0
        and analyzer.failed_business_records > 0
    ):
        session_logger.log(
            "[status] provided key produced no parsable business records; treating session as failure"
        )
        return _BAD_KEY_EXIT_CODE
    return 0


# ---------------------------------------------------------------------------
# 统一运行函数（合并原 run_capture_key / run_live_decode / run_analyze）
# ---------------------------------------------------------------------------

def run_command(args: argparse.Namespace) -> int:
    command = args.command
    config = _COMMAND_CONFIG.get(command)
    if config is None:
        print(f"未知命令: {command}")
        return 1

    prefix, needs_csv, needs_reporter, stop_after_key = config
    out_dir = ensure_output_dir(args.out_dir, prefix)

    # 初始化各组件
    session_logger = SessionLogger(out_dir / "capture.log")
    csv_sink: CsvSink | None = None
    move_csv_sink: MoveCsvSink | None = None
    writer: PcapWriter | None = None
    reporter: ProtocolConsoleReporter | None = None
    relay: OpcodeRelayServer | None = None

    try:
        iface_before = getattr(args, "iface", None)
        resolved_iface = _resolve_runtime_iface(args)
        if not getattr(args, "read_pcap", None):
            if getattr(args, "iface_only", False) and resolved_iface:
                session_logger.log(f"[iface] locked to {resolved_iface}")
            elif resolved_iface:
                session_logger.log(f"[iface] preferred {resolved_iface}")
            else:
                session_logger.log("[iface] no preferred NIC")

        if needs_csv:
            csv_path = getattr(args, "csv_out", None) or out_dir / "decoded_packets.csv"
            opcode_csv_path = getattr(args, "opcode_summary_out", None)
            csv_sink = CsvSink(csv_path, opcode_csv_path)

        if not args.read_pcap:
            pcap_path = args.pcap_out or out_dir / ("capture.pcap" if not needs_csv else "live_capture.pcap")
            writer = PcapWriter(str(pcap_path), append=False, sync=False)

        preset_key = _load_preset_key(args, command, session_logger)

        if needs_reporter:
            reporter = ProtocolConsoleReporter(logger=session_logger)

        if command == "opencode-server":
            server_mode = getattr(args, "server_mode", "normal")
            relay = OpcodeRelayServer(
                host=getattr(args, "relay_host", "127.0.0.1"),
                port=getattr(args, "relay_port", 8765),
                history_size=getattr(args, "relay_history", 500),
                logger=session_logger,
                mode=server_mode,
            )
            if server_mode == "move":
                move_csv_path = getattr(args, "move_csv_out", None) or out_dir / "move_summary.csv"
                move_csv_sink = MoveCsvSink(move_csv_path)
            relay.start()

        listener = _MultiListener(reporter, relay, move_csv_sink)

        analyzer = RkppAnalyzer(
            port=args.port, logger=session_logger, writer=writer,
            key_file=out_dir / "key.txt", csv_sink=csv_sink,
            preset_key=preset_key, stop_after_key=stop_after_key,
            analysis_listener=listener if listener.listeners else None,
        )

        mode = "offline" if args.read_pcap else "live"
        session_logger.log(
            f"[startup] command={command} mode={mode} iface={args.iface or '<scapy-default>'} "
            f"port={args.port} out_dir={out_dir}"
            + (f" csv={csv_sink.csv_path} opencode_csv={csv_sink.opcode_csv_path}" if csv_sink else "")
            + (f" server_mode={getattr(args, 'server_mode', 'normal')}" if command == "opencode-server" else "")
            + (f" move_csv={move_csv_sink.csv_path}" if move_csv_sink else "")
        )

        game_stop = None
        try:
            from rkpp_game_process import start_game_key_watchdog
            game_stop = start_game_key_watchdog(
                analyzer.invalidate_game_session_key,
                logger=session_logger.log,
            )
        except Exception as exc:
            session_logger.log(f"[game] watchdog unavailable {exc}")
        try:
            _run_session(analyzer, args)
        except KeyboardInterrupt:
            session_logger.log("[status] keyboard_interrupt stopping")
        finally:
            if game_stop is not None:
                game_stop.set()

        session_logger.log(
            f"[summary] packets={analyzer.packet_count} key_hits={analyzer.key_hits} "
            f"rows={analyzer.decoded_rows} errors={analyzer._total_errors} "
            f"listener_errors={analyzer.listener_errors}"
        )
        return _session_exit_code(
            command,
            analyzer,
            preset_key=preset_key,
            session_logger=session_logger,
        )

    finally:
        for resource in (writer, csv_sink, move_csv_sink, relay, session_logger):
            _close_optional(resource)


# ---------------------------------------------------------------------------
# 交互式模式
# ---------------------------------------------------------------------------

def build_interactive_args() -> argparse.Namespace:
    choice = prompt_menu()
    iface  = _prompt_iface()
    out_dir_str = prompt_text("输出目录（留空则自动创建）", "")
    out_dir = Path(out_dir_str) if out_dir_str else None
    base = argparse.Namespace(
        iface=iface, port=DEFAULT_PORT, out_dir=out_dir,
        pcap_out=None, read_pcap=None, no_bpf=False, list_ifaces=False,
    )
    command = _INTERACTIVE_COMMANDS[choice]
    if command == "capture-key":
        return argparse.Namespace(**vars(base), command=command)

    key: str | None = None
    latest_key = load_latest_key()
    if latest_key:
        key = latest_key.hex()
        print(f"已读取 {latest_key_path()}: {key}")
    else:
        print("未找到 latest.key，可留空等待 0x1002 自动刷新密钥。")
        while True:
            raw = input("请输入秘钥（16位ASCII或32位hex，留空自动刷新）: ").strip()
            if not raw:
                break
            try:
                key = parse_key_text(raw).hex()
                break
            except ValueError as e:
                print(f"秘钥格式错误: {e}")
    server_mode = "normal"
    if choice == "4":
        server_mode = prompt_server_mode()
    return argparse.Namespace(
        **vars(base),
        command=command,
        csv_out=None, key=key,
        server_mode=server_mode, move_csv_out=None,
        relay_host="127.0.0.1", relay_port=8765, relay_history=5000,
    )


def _prompt_iface() -> str | None:
    default_iface = get_default_iface()
    while True:
        default_label = default_iface or "Scapy默认"
        raw = input(
            f"接口名（回车使用默认，?=列出网卡，set=设置默认） [{default_label}]: "
        ).strip()
        if not raw:
            return None
        if raw in {"?", "list"}:
            list_ifaces(default_iface)
            continue
        if raw.lower() == "set":
            list_ifaces(default_iface)
            new_default = input("新的默认接口名: ").strip()
            if not new_default:
                print("默认接口未修改。")
                continue
            try:
                set_default_iface(new_default)
            except ValueError as exc:
                print(f"默认接口设置失败: {exc}")
                continue
            default_iface = new_default
            print(f"默认接口已设置为: {default_iface}")
            continue
        return raw


# ---------------------------------------------------------------------------
# argparse + main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抓 key / 持续抓包解密导出工具")
    parser.add_argument("--list-ifaces", action="store_true")
    parser.add_argument("--show-default-iface", action="store_true")
    parser.add_argument("--set-default-iface")
    sub = parser.add_subparsers(dest="command")

    def _common(p):
        p.add_argument("--iface")
        p.add_argument("--port", type=int, default=DEFAULT_PORT)
        p.add_argument("--out-dir", type=Path)
        p.add_argument("--pcap-out", type=Path)
        p.add_argument("--read-pcap", type=Path)
        p.add_argument("--no-bpf", action="store_true")
        p.add_argument("--iface-only", action="store_true",
                       help="只抓指定 --iface，不自动监听其他网卡")

    def _key_arg(p):
        p.add_argument("--key", help="已知 key，16字节ASCII或32位hex")

    def _csv_arg(p):
        p.add_argument("--csv-out", type=Path)

    cap = sub.add_parser("capture-key", help="抓取首个 0x1002 key，输出 key.txt")
    _common(cap)

    live = sub.add_parser("live-decode", help="持续抓包，输出解密 CSV")
    _common(live)
    _key_arg(live)
    _csv_arg(live)

    analyze = sub.add_parser("analyze", help="持续抓包并实时输出协议解析，同时导出 CSV")
    _common(analyze)
    _key_arg(analyze)
    _csv_arg(analyze)

    relay = sub.add_parser("opencode-server", help="解析 opencode 并通过本地 HTTP NDJSON relay 提供给其他程序")
    _common(relay)
    _key_arg(relay)
    _csv_arg(relay)
    relay.add_argument("--opcode-summary-out", type=Path,
                       help="opencode 摘要 CSV 的输出路径")
    relay.add_argument("--server-mode", choices=("normal", "move"), default="normal",
                       help="normal=常规中转，move=只提供 client_move 并额外输出 move_summary.csv")
    relay.add_argument("--move-csv-out", type=Path,
                       help="server-mode=move 时的 move CSV 输出路径")
    relay.add_argument("--relay-host", default="127.0.0.1")
    relay.add_argument("--relay-port", type=int, default=8765)
    relay.add_argument("--relay-history", type=int, default=5000)
    relay.add_argument("--allow-stale-key", action="store_true",
                       help="允许 live relay 使用上次保存的 key；默认等待本次连接刷新")

    return parser


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args()
    if args.set_default_iface:
        path = set_default_iface(args.set_default_iface)
        print(f"默认网卡已设置为: {args.set_default_iface}")
        print(f"配置文件: {path}")
        return 0
    if args.show_default_iface:
        default_iface = get_default_iface()
        print(default_iface or "<unset>")
        return 0
    if args.list_ifaces:
        list_ifaces()
        return 0
    if not args.command:
        args = build_interactive_args()
    return run_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
