#!/usr/bin/env python3

"""网络层：AES-128-CBC 解密、key 管理、BE21 帧解析、TCP 流状态。"""
from __future__ import annotations

import logging
import os
import sys
import json
import threading
import weakref
from collections import OrderedDict
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from typing import Any

try:
    from Crypto.Cipher import AES
except ImportError as exc:
    raise SystemExit("缺少 pycryptodome。先执行: python -m pip install --user pycryptodome") from exc

from scapy.all import IP, IPv6, TCP, conf  # type: ignore

from rkpp_io import now_text

logger = logging.getLogger(__name__)

MAGIC = b"\x33\x66"
FIXED_HDR_LEN = 21
RKPP_IVDECODER_MODE = "Ivdecoder"
RKPP_IVDECODER_AES_IV = bytes(range(16))
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_KEY_DIR = SCRIPT_DIR / "Key"
SETTINGS_PATH = SCRIPT_DIR / "rkpp_settings.json"
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = Path(os.environ['LOCALAPPDATA']) / 'RocoPVP/rkpp'
    SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_KEY_DIR = SCRIPT_DIR / 'Key'
    SETTINGS_PATH = SCRIPT_DIR / 'rkpp_settings.json'

# BE21 合法 cmd 范围，用于帧头校验以减少假 magic 命中。
_KNOWN_CMD_RANGE = range(0x0001, 0x8000)
# 0x9001 HEARTBEAT is a real TGCP command (see TGCP_COMMAND_NAMES).
# Rejecting it desyncs the stream and swallows later battle frames.
_KNOWN_CMD_EXTRA = frozenset({0x9001})

# 防止 seen_acks 无限增长。
RKPP_MAX_SEEN_ACKS = 256

# 防止连续流缓存与乱序段缓存无限增长。
RKPP_MAX_BUFFER_SIZE = 16 * 1024 * 1024
RKPP_MAX_PENDING_BYTES = 8 * 1024 * 1024

_MAX_SEEN_ACKS = RKPP_MAX_SEEN_ACKS
_MAX_BUFFER_SIZE = RKPP_MAX_BUFFER_SIZE
_MAX_PENDING_BYTES = RKPP_MAX_PENDING_BYTES

# qkGapSkip: 缺口放弃阈值。缺口是永久性的，大小不重要，因此以"等待无进展"为主判据。
# 实测：服务器方向曾因 6,389 字节缺口滞留 1,284,138 字节数据、parse_offset 长期为 0。
RKPP_GAP_SKIP_BYTES = 64 * 1024
RKPP_GAP_SKIP_PENDING_BYTES = 2 * 1024 * 1024
RKPP_GAP_SKIP_STALL_FEEDS = 300

# Observation only: never supplies bytes, changes counters, or repairs a stream.
CAPTURE_INTEGRITY_REVISION = "20261020-capture-integrity-v1"
_CAPTURE_INTEGRITY_MAX_FLOWS = 256
_CAPTURE_INTEGRITY_MAX_PACKETS = 8192
_capture_integrity_lock = threading.RLock()
_capture_integrity_generations = count(1)
_capture_integrity_serial = 0
_capture_integrity_active_flow: str | None = None
_capture_integrity_flows: OrderedDict[str, Any] = OrderedDict()
_capture_integrity_packets: OrderedDict[tuple, dict[str, Any]] = OrderedDict()


def capture_integrity_watermark() -> int:
    """Relay startup boundary; packets whose feed began earlier cannot be certified."""
    with _capture_integrity_lock:
        return _capture_integrity_serial


def _capture_integrity_unknown(epoch: str, flow_id=None, generation=None) -> dict[str, Any]:
    return {
        "revision": CAPTURE_INTEGRITY_REVISION, "epoch": epoch,
        "flowId": flow_id, "streamGeneration": generation,
        "gapSkipped": None, "gapBytesDropped": None,
        "droppedPendingSegments": None, "trimmedBuffers": None,
        "resyncBytes": None, "decodeFailures": None,
        "pendingGap": None, "observed": False,
    }


def _capture_integrity_flow_snapshot(flow, epoch: str, since: int) -> dict[str, Any]:
    unknown = _capture_integrity_unknown(
        epoch, flow.flow_id, flow._capture_integrity_generation,
    )
    # A zero counter is evidence only for real, fed DirectionStates in BOTH directions.
    if (flow._capture_integrity_busy or flow._capture_integrity_failed
            or not flow._capture_integrity_decoder_observed
            or flow._capture_integrity_observation <= since):
        return unknown
    states = (flow.c2s, flow.s2c)
    if any(s._base_seq is None or s._capture_integrity_owner is None
           or s._capture_integrity_owner() is not flow for s in states):
        return unknown
    return {
        **unknown,
        "gapSkipped": sum(s.gap_skipped for s in states),
        "gapBytesDropped": sum(s.gap_bytes_dropped for s in states),
        "droppedPendingSegments": sum(s.dropped_pending_segments for s in states),
        "trimmedBuffers": sum(s.trimmed_buffers for s in states),
        "resyncBytes": sum(s.resync_bytes for s in states),
        "decodeFailures": flow._capture_integrity_decode_failures,
        "pendingGap": any(s._pending and s._next_contig_seq is not None
                          and min(s._pending) > s._next_contig_seq for s in states),
        "observed": True,
    }


def capture_integrity_snapshot(*, epoch: str, since: int = 0,
                               row: dict[str, Any] | None = None) -> dict[str, Any]:
    """Exact emitted-packet proof, or live per-flow health (including silent gaps).

    `observed` means these reassembly states were observed, NOT that capture started
    at the TCP handshake, or that the NIC/pcap/decoder never lost anything.
    No lookup fallback to the latest flow is allowed for an unmatched event/CSV.
    """
    with _capture_integrity_lock:
        if row is not None:
            flow_id = row.get("flow_id")
            unknown = _capture_integrity_unknown(epoch, flow_id)
            # Live analyzer rows have integer packet coordinates; legacy CSVs don't.
            if (not isinstance(flow_id, str) or row.get("direction") not in ("c2s", "s2c")
                    or type(row.get("stream_offset")) is not int
                    or type(row.get("seq")) is not int):
                return unknown
            key = (flow_id, row["direction"], row["stream_offset"], row["seq"])
            record = _capture_integrity_packets.get(key)
            ref = _capture_integrity_flows.get(flow_id)
            flow = ref() if ref else None
            if (record is None or flow is None or record["serial"] <= since
                    or record["ambiguous"] or flow._capture_integrity_busy
                    or flow._capture_integrity_failed
                    or record["snapshot"]["streamGeneration"] != flow._capture_integrity_generation):
                return unknown
            return {**record["snapshot"], "epoch": epoch}
        flows = {}
        for flow_id, ref in _capture_integrity_flows.items():
            flow = ref()
            flows[flow_id] = (_capture_integrity_flow_snapshot(flow, epoch, since)
                              if flow is not None else _capture_integrity_unknown(epoch, flow_id))
        active = flows.get(_capture_integrity_active_flow)
        return {**(active or _capture_integrity_unknown(epoch)), "flows": flows}


def _capture_integrity_begin(state):
    global _capture_integrity_serial, _capture_integrity_active_flow
    owner = state._capture_integrity_owner
    flow = owner() if owner else None
    if flow is None:
        return None
    with _capture_integrity_lock:
        ref = _capture_integrity_flows.get(flow.flow_id)
        if ref is None or ref() is not flow:
            return None
        _capture_integrity_serial += 1
        flow._capture_integrity_busy += 1
        _capture_integrity_active_flow = flow.flow_id
        _capture_integrity_flows.move_to_end(flow.flow_id)
        return flow, _capture_integrity_serial


def _capture_integrity_finish(token, packets) -> None:
    if token is None:
        return
    flow, serial = token
    with _capture_integrity_lock:
        flow._capture_integrity_busy -= 1
        flow._capture_integrity_observation = max(flow._capture_integrity_observation, serial)
        if packets is None:
            flow._capture_integrity_failed = True
            return
        snapshot = _capture_integrity_flow_snapshot(flow, "", 0)
        for packet in packets:
            key = (flow.flow_id, packet.direction, packet.stream_offset, packet.seq)
            old = _capture_integrity_packets.get(key)
            ambiguous = bool(old and (old["ambiguous"] or
                             old["snapshot"]["streamGeneration"] != flow._capture_integrity_generation))
            _capture_integrity_packets[key] = {
                "serial": serial, "snapshot": dict(snapshot), "ambiguous": ambiguous,
            }
            _capture_integrity_packets.move_to_end(key)
        while len(_capture_integrity_packets) > _CAPTURE_INTEGRITY_MAX_PACKETS:
            _capture_integrity_packets.popitem(last=False)


def _capture_integrity_record_resync(state, byte_count: int) -> None:
    """Count only bytes actually skipped by the original BE21 resync branches."""
    if state is None:
        return
    try:
        with _capture_integrity_lock:
            state.resync_bytes += byte_count
    except Exception:
        owner = getattr(state, "_capture_integrity_owner", None)
        flow = owner() if owner else None
        if flow is not None:
            flow._capture_integrity_failed = True


def printable_ascii(blob: bytes) -> str | None:
    return blob.decode("ascii", errors="replace") if blob and all(32 <= b < 127 for b in blob) else None


def parse_key_text(text: str) -> bytes:
    raw = text.strip()
    hex_cand = "".join(c for c in raw if c in "0123456789abcdefABCDEF")
    if len(raw) == 16:
        try:
            key = raw.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("key 必须是 16 字节 ASCII 或 32 位 hex") from exc
    elif len(hex_cand) == 32:
        key = bytes.fromhex(hex_cand)
    else:
        raise ValueError("key 必须是 16 字节 ASCII 或 32 位 hex")
    if len(key) != 16:
        raise ValueError("AES-128 key 必须正好 16 字节")
    return key


def load_key_from_file(path: str | Path) -> bytes | None:
    def _try_parse(value: str) -> bytes | None:
        try:
            return parse_key_text(value)
        except ValueError:
            return None

    path = Path(path)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return None
    first = text.splitlines()[0].strip()
    if "=" not in first:
        return _try_parse(first)
    for line in text.splitlines():
        if line.startswith("key_hex="):
            value = line.split("=", 1)[1].strip()
            if value:
                key = _try_parse(value)
                if key is not None:
                    return key
        if line.startswith("key_ascii="):
            value = line.split("=", 1)[1].strip()
            if value and value != "<non-ascii>":
                key = _try_parse(value)
                if key is not None:
                    return key
    return None


def _key_record_text(key: bytes, flow_id: str, captured_at: str) -> str:
    return (
        f"key_hex={key.hex()}\nkey_ascii={printable_ascii(key) or '<non-ascii>'}\n"
        f"flow={flow_id}\ncaptured_at={captured_at}\n"
    )


def write_key_file(path: str | Path, key: bytes, flow_id: str, *, captured_at: str | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _key_record_text(key, flow_id, captured_at or now_text()),
        encoding="utf-8",
    )


def default_key_dir() -> Path:
    return DEFAULT_KEY_DIR


def latest_key_path(key_dir: str | Path | None = None) -> Path:
    return Path(key_dir or DEFAULT_KEY_DIR) / "latest.key"


def load_latest_key(key_dir: str | Path | None = None) -> bytes | None:
    return load_key_from_file(latest_key_path(key_dir))


def write_key_store(key: bytes, flow_id: str, key_dir: str | Path | None = None) -> tuple[Path, Path]:
    key_dir = Path(key_dir or DEFAULT_KEY_DIR)
    key_dir.mkdir(parents=True, exist_ok=True)
    captured_at = now_text()
    text = _key_record_text(key, flow_id, captured_at)
    latest_path = latest_key_path(key_dir)
    latest_path.write_text(text, encoding="utf-8")
    return latest_path, latest_path


def decrypt_4013_body(key: bytes, body: bytes) -> tuple[bytes, bytes]:
    """Decrypt 0x4013 with the current Ivdecoder layout."""
    if len(body) < 16:
        raise ValueError("0x4013 body 长度不足，无法解密")
    if len(body) % 16 != 0:
        raise ValueError("0x4013 body 不是 16 字节对齐")
    return RKPP_IVDECODER_AES_IV, AES.new(key, AES.MODE_CBC, RKPP_IVDECODER_AES_IV).decrypt(body)


def packet_has_target_port(packet, port: int) -> bool:
    return packet.haslayer(TCP) and (int(packet[TCP].sport) == port or int(packet[TCP].dport) == port)


def tcp_payload_bytes(packet) -> bytes:
    """Captured TCP body within declared IP/TCP bounds, never link Padding.

    Scapy may attach Ethernet Padding below TCP, including on payload-free ACKs.
    Use serialized header lengths, not byte patterns or len(TCP.payload). IP
    fragments need IP reassembly first; malformed/unsupported headers yield no
    bytes. A truncated body yields only its captured prefix, never synthetic fill.
    IPv6 jumbograms (plen=0) are not inferred from trailing captured bytes.
    """
    if not packet.haslayer(TCP):
        return b""
    tcp = packet[TCP]
    ip = tcp.underlayer
    while ip is not None and not isinstance(ip, (IP, IPv6)):
        ip = ip.underlayer
    if ip is None:
        return b""
    raw_ip, raw_tcp = bytes(ip), bytes(tcp)
    # Both serialized layers include the same trailing Padding on real Scapy
    # packets (also with IPv4 options / IPv6 extensions). Verify, do not assume.
    tcp_start = len(raw_ip) - len(raw_tcp)
    if tcp_start < 0 or raw_ip[tcp_start:] != raw_tcp or len(raw_tcp) < 20:
        return b""
    if isinstance(ip, IP):
        if len(raw_ip) < 20 or raw_ip[0] >> 4 != 4:
            return b""
        cursor = (raw_ip[0] & 15) * 4
        declared_end = int.from_bytes(raw_ip[2:4], "big")
        # MF or a nonzero fragment offset: never feed an IP fragment as a
        # complete TCP segment. DF is not fragmentation.
        if cursor < 20 or raw_ip[9] != 6 or int.from_bytes(raw_ip[6:8], "big") & 0x3FFF:
            return b""
    else:
        if len(raw_ip) < 40 or raw_ip[0] >> 4 != 6:
            return b""
        declared_end = 40 + int.from_bytes(raw_ip[4:6], "big")
        cursor, next_header = 40, raw_ip[6]
        available_end = min(declared_end, len(raw_ip))
        while next_header != 6:
            if cursor + 2 > available_end:
                return b""
            if next_header in (0, 43, 60):  # Hop-by-Hop, Routing, Destination
                size = (raw_ip[cursor + 1] + 1) * 8
            elif next_header == 51:  # Authentication Header
                size = (raw_ip[cursor + 1] + 2) * 4
                if size < 12:
                    return b""
            elif next_header == 44:
                size = 8
                if cursor + size > available_end or int.from_bytes(raw_ip[cursor + 2:cursor + 4], "big") & 0xFFF9:
                    return b""  # only an atomic fragment is already complete
            else:
                return b""  # ESP/unknown extension: do not guess TCP's location
            if cursor + size > available_end:
                return b""
            next_header = raw_ip[cursor]
            cursor += size
    available_end = min(declared_end, len(raw_ip))
    tcp_header_bytes = (raw_tcp[12] >> 4) * 4
    if (tcp_start != cursor or tcp_header_bytes < 20
            or tcp_start + tcp_header_bytes > available_end):
        return b""
    return raw_ip[tcp_start + tcp_header_bytes:available_end]


def packet_ip_tuple(packet) -> tuple[str, str] | None:
    for layer in (IP, IPv6):
        if packet.haslayer(layer):
            ip = packet[layer]
            return ip.src, ip.dst
    return None


def flow_key_from_packet(packet, port: int) -> tuple[str, str, int, str, int, str] | None:
    ip_pair = packet_ip_tuple(packet)
    if ip_pair is None or not packet.haslayer(TCP):
        return None
    src_ip, dst_ip = ip_pair
    tcp = packet[TCP]
    sp = int(tcp.sport)
    dp = int(tcp.dport)
    if dp == port:
        return src_ip, "c2s", sp, dst_ip, dp, f"{src_ip}:{sp}->{dst_ip}:{dp}"
    if sp == port:
        return dst_ip, "s2c", dp, src_ip, sp, f"{dst_ip}:{dp}->{src_ip}:{sp}"
    return None


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path or SETTINGS_PATH)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load settings %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(settings: dict[str, Any], path: str | Path | None = None) -> Path:
    path = Path(path or SETTINGS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def get_default_iface(path: str | Path | None = None) -> str | None:
    value = load_settings(path).get("default_iface")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def set_default_iface(iface: str, path: str | Path | None = None) -> Path:
    iface = iface.strip()
    if not iface:
        raise ValueError("interface name cannot be empty")
    settings = load_settings(path)
    settings["default_iface"] = iface
    return save_settings(settings, path)


def iter_ifaces() -> list[tuple[str, str]]:
    return [
        (iface.name, getattr(iface, "description", ""))
        for iface in conf.ifaces.values()
    ]


def list_ifaces(default_iface: str | None = None) -> None:
    default_iface = default_iface if default_iface is not None else get_default_iface()
    found_default = False
    for name, description in iter_ifaces():
        suffix = ""
        if default_iface and name == default_iface:
            suffix = "\t[default]"
            found_default = True
        print(f"{name}\t{description}{suffix}")
    if default_iface and not found_default:
        print(f"{default_iface}\t[default, not currently listed]")


_SKIP_IFACE_HINTS = (
    "loopback",
    "npcap loopback",
    "bluetooth",
    "wan miniport",
    "pseudo-interface",
    "isatap",
    "teredo",
    "debug",
    "virtualbox",
    "vmware",
    "hyper-v",
)

_WAN_IFACE_HINTS = (
    "pppoe",
    "vpn",
    "wintun",
    "wireguard",
    "tap-windows",
    "tap adapter",
    "nordlynx",
    "openvpn",
    "ras async",
)

_WIFI_IFACE_HINTS = (
    "wlan",
    "wi-fi",
    "wifi",
    "wireless",
    "无线",
)


def iface_should_skip(name: str, description: str = "") -> bool:
    blob = f"{name} {description}".lower()
    return any(hint in blob for hint in _SKIP_IFACE_HINTS)


def iface_is_wan_like(name: str, description: str = "") -> bool:
    if "*" in (name or ""):
        return True
    blob = f"{name} {description}".lower()
    return any(hint in blob for hint in _WAN_IFACE_HINTS)


def iface_is_wifi(name: str, description: str = "") -> bool:
    blob = f"{name} {description}".lower()
    return any(hint in blob for hint in _WIFI_IFACE_HINTS)


def get_default_route_iface() -> str | None:
    iface = None
    try:
        result = conf.route.route("0.0.0.0")
        if result:
            iface = result[0]
    except Exception:
        iface = None
    if iface is None:
        iface = getattr(conf, "iface", None)
    if iface is None:
        return None
    name = getattr(iface, "name", None) or str(iface)
    name = str(name).strip()
    return name or None


def capture_iface_candidates(preferred: str | None = None) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    listed = iter_ifaces()
    if preferred:
        ordered.append(preferred)
        seen.add(preferred)
    for name, desc in listed:
        if name in seen or iface_should_skip(name, desc):
            continue
        ordered.append(name)
        seen.add(name)
    return ordered


def _usable_wan_iface(name: str | None) -> bool:
    return bool(name) and "*" not in name


def _pick_single_capture_iface(
    safe: list[str],
    wan: list[str],
    preferred: str | None,
    default_route: str | None,
    meta: dict[str, str],
) -> str | None:
    if preferred and preferred in safe:
        return preferred
    if default_route and default_route in safe:
        return default_route
    if preferred and preferred in wan and _usable_wan_iface(preferred):
        return preferred
    if default_route and default_route in wan and _usable_wan_iface(default_route):
        return default_route
    for name in safe:
        if iface_is_wifi(name, meta.get(name, "")):
            return name
    if safe:
        return safe[0]
    if wan:
        for name in wan:
            if _usable_wan_iface(name):
                return name
        return wan[0]
    return None


def select_capture_ifaces(
    listed: list[tuple[str, str]],
    preferred: str | None = None,
    default_route: str | None = None,
) -> tuple[list[str | None], str]:
    skip: list[str] = []
    wan: list[str] = []
    safe: list[str] = []
    seen: set[str] = set()
    meta: dict[str, str] = {}

    def remember(name: str, description: str = "") -> None:
        if not name or name in seen:
            return
        seen.add(name)
        meta[name] = description or ""
        if iface_should_skip(name, description):
            skip.append(name)
            return
        if iface_is_wan_like(name, description):
            wan.append(name)
            return
        safe.append(name)

    if preferred:
        remember(preferred, "")
    for name, desc in listed:
        remember(name, desc or "")

    def order_targets(names: list[str]) -> list[str]:
        ordered = list(names)
        if default_route and default_route in ordered:
            ordered = [default_route] + [item for item in ordered if item != default_route]
        if preferred and preferred in ordered:
            ordered = [preferred] + [item for item in ordered if item != preferred]
        return ordered

    targets = list(safe)
    if default_route and default_route in wan and _usable_wan_iface(default_route) and default_route not in targets:
        targets.append(default_route)
    if preferred and preferred in wan and _usable_wan_iface(preferred) and preferred not in targets:
        targets.append(preferred)

    skipped_wan = [name for name in wan if name not in targets]
    route = f"default_route={default_route} " if default_route else ""
    pref = f"preferred={preferred} " if preferred else ""
    wan_note = f" skipped_wan={','.join(skipped_wan)}" if skipped_wan else ""

    if len(targets) > 6:
        picked = _pick_single_capture_iface(safe, wan, preferred, default_route, meta)
        if picked:
            extra = [item for item in targets if item != picked]
            extra_note = f" also_safe={','.join(extra)}" if extra else ""
            return [picked], (
                f"single-iface fallback {picked} reason=too-many-nics {pref}{route}"
                f"candidates={','.join(order_targets(targets))}{wan_note}{extra_note}"
            )

    if targets:
        ordered = order_targets(targets)
        return ordered, f"auto-capture all {pref}{route}candidates={','.join(ordered)}{wan_note}"

    if preferred:
        return [preferred], f"single-iface fallback {preferred} reason=preferred-only {route}"

    return [None], f"auto-capture scapy-default {route}".strip()


def resolve_capture_ifaces(preferred: str | None = None) -> tuple[list[str | None], str]:
    return select_capture_ifaces(iter_ifaces(), preferred, get_default_route_iface())


def iface_description(name: str) -> str:
    for iface_name, desc in iter_ifaces():
        if iface_name == name:
            return str(desc or "")
    return ""


@dataclass
class Be21Packet:
    direction: str
    stream_offset: int
    cmd: int
    seq: int
    hdr_len: int
    body_len: int
    header_extra: bytes
    body: bytes


def _validate_be21_header(data: bytearray, off: int) -> bool:
    if off + FIXED_HDR_LEN > len(data):
        return False
    cmd = int.from_bytes(data[off + 6:off + 8], "big")
    hdr_len = int.from_bytes(data[off + 13:off + 17], "big")
    body_len = int.from_bytes(data[off + 17:off + 21], "big")
    if cmd not in _KNOWN_CMD_RANGE and cmd not in _KNOWN_CMD_EXTRA:
        return False
    if hdr_len < FIXED_HDR_LEN:
        return False
    if (hdr_len + body_len) > 4 * 1024 * 1024:
        return False
    return True


def parse_be21_from_buffer(data: bytearray, direction: str, start: int, *,
                           integrity_state=None) -> tuple[list[Be21Packet], int]:
    packets: list[Be21Packet] = []
    off = start
    size = len(data)
    while off + FIXED_HDR_LEN <= size:
        if data[off:off + 2] != MAGIC:
            nxt = data.find(MAGIC, off + 1)
            if nxt < 0:
                break
            _capture_integrity_record_resync(integrity_state, nxt - off)
            off = nxt
            continue
        if not _validate_be21_header(data, off):
            _capture_integrity_record_resync(integrity_state, 2)
            off += 2
            continue
        cmd = int.from_bytes(data[off + 6:off + 8], "big")
        seq = int.from_bytes(data[off + 9:off + 13], "big")
        hdr_len = int.from_bytes(data[off + 13:off + 17], "big")
        body_len = int.from_bytes(data[off + 17:off + 21], "big")
        pkt_len = hdr_len + body_len
        if off + pkt_len > size:
            break
        packets.append(
            Be21Packet(
                direction=direction,
                stream_offset=off,
                cmd=cmd,
                seq=seq,
                hdr_len=hdr_len,
                body_len=body_len,
                header_extra=bytes(data[off + FIXED_HDR_LEN:off + hdr_len]),
                body=bytes(data[off + hdr_len:off + pkt_len]),
            )
        )
        off += pkt_len
    return packets, off


@dataclass
class DirectionState:
    direction: str
    buffer: bytearray = field(default_factory=bytearray)
    parse_offset: int = 0
    stream_base: int = 0
    _base_seq: int | None = None
    _next_contig_seq: int | None = None
    _pending: dict[int, bytes] = field(default_factory=dict)
    _pending_bytes: int = 0
    dropped_pending_segments: int = 0
    trimmed_buffers: int = 0
    # qkGapSkip: 永久缺口若一直等下去，整条方向流会永久停摆；累计统计便于观测。
    gap_skipped: int = 0
    gap_bytes_dropped: int = 0
    _stall_feeds: int = 0
    resync_bytes: int = 0
    _capture_integrity_owner: Any = field(default=None, init=False, repr=False, compare=False)

    def feed(self, seq: int, payload: bytes) -> list[Be21Packet]:
        """Observe the existing reassembler without changing its return/order/error."""
        if not payload:
            return self._feed(seq, payload)
        token = None
        try:
            token = _capture_integrity_begin(self)
        except Exception:
            # An unavailable observer must not take down packet capture.
            if self._capture_integrity_owner and self._capture_integrity_owner():
                self._capture_integrity_owner()._capture_integrity_failed = True
        packets = None
        try:
            packets = self._feed(seq, payload)
            return packets
        finally:
            try:
                _capture_integrity_finish(token, packets)
            except Exception:
                if token is not None:
                    token[0]._capture_integrity_failed = True

    def _feed(self, seq: int, payload: bytes) -> list[Be21Packet]:
        """把 TCP 段按 seq 重组为连续字节流，再交给 BE21 解析器。"""
        if not payload:
            return []

        if self._base_seq is None:
            self._base_seq = seq
            self.buffer.extend(payload)
            self._next_contig_seq = seq + len(payload)
        else:
            self._ingest_segment(seq, payload)

        if len(self.buffer) > _MAX_BUFFER_SIZE:
            self._trim_buffer()

        # qkGapSkip: 待处理缓存卡住时（缺口补不上），放弃缺口继续解析，
        # 否则该方向流会永久停摆（实测：服务器方向曾因此滞留 1.28MB 数据）。
        skipped = self._qkGapSkipIfStalled()
        base = self.stream_base
        packets, new_off = parse_be21_from_buffer(self.buffer, self.direction, self.parse_offset,
                                                 integrity_state=self)
        self.parse_offset = new_off
        for packet in packets:
            packet.stream_offset += base

        if self.parse_offset >= 0x10000 and self.parse_offset > len(self.buffer) // 2:
            trim = self.parse_offset
            del self.buffer[:trim]
            self.stream_base += trim
            if self._base_seq is not None:
                self._base_seq += trim
            self.parse_offset = 0

        if skipped:
            packets = packets + skipped
        return packets

    def _qkGapSkipIfStalled(self) -> list[Be21Packet]:
        """qkGapSkip: 缺口长期补不上时放弃缺口，避免整条方向流永久停摆。

        触发条件（任一）：
          * 缺口字节数超过 RKPP_GAP_SKIP_BYTES
          * 待处理缓存超过 RKPP_GAP_SKIP_PENDING_BYTES
          * 连续 RKPP_GAP_SKIP_STALL_FEEDS 次收包都没有任何进展
        正常无缺口的流不会触发（已用成功轮 pcap 回归：触发次数为 0）。
        """
        if not self._pending or self._next_contig_seq is None:
            self._stall_feeds = 0
            return []

        smallest = min(self._pending)
        gap = smallest - self._next_contig_seq
        if gap <= 0:
            self._stall_feeds = 0
            return []

        self._stall_feeds += 1
        if not (
            gap > RKPP_GAP_SKIP_BYTES
            or self._pending_bytes > RKPP_GAP_SKIP_PENDING_BYTES
            or self._stall_feeds >= RKPP_GAP_SKIP_STALL_FEEDS
        ):
            return []

        self.gap_skipped += 1
        self.gap_bytes_dropped += gap
        self._stall_feeds = 0
        logger.warning(
            "DirectionState[%s] gap skipped: abandoning %d missing bytes at seq=%d "
            "(pending=%d segments / %d bytes)",
            self.direction,
            gap,
            self._next_contig_seq,
            len(self._pending),
            self._pending_bytes,
        )
        self._next_contig_seq = smallest
        self._drain_pending()
        packets, new_off = parse_be21_from_buffer(self.buffer, self.direction, self.parse_offset,
                                                 integrity_state=self)
        self.parse_offset = new_off
        for packet in packets:
            packet.stream_offset += self.stream_base
        return packets

    def _ingest_segment(self, seq: int, payload: bytes) -> None:
        assert self._base_seq is not None
        assert self._next_contig_seq is not None

        end = seq + len(payload)
        if seq < self._base_seq:
            if end < self._base_seq:
                logger.debug(
                    "DirectionState[%s] dropping non-contiguous old segment seq=%d end=%d base=%d",
                    self.direction,
                    seq,
                    end,
                    self._base_seq,
                )
                return
            prepend_len = self._base_seq - seq
            if prepend_len > 0:
                self.buffer = bytearray(payload[:prepend_len]) + self.buffer
                self._base_seq = seq
                self.parse_offset += prepend_len
                self.stream_base = max(0, self.stream_base - prepend_len)
            if end <= self._next_contig_seq:
                return
            payload = payload[self._next_contig_seq - seq:]
            seq = self._next_contig_seq
            if not payload:
                return

        if seq <= self._next_contig_seq:
            start = seq - self._base_seq
            overlap = self._next_contig_seq - seq
            if overlap > 0 and start >= 0:
                overlap = min(overlap, len(payload))
                existing = bytes(self.buffer[start:start + overlap])
                incoming = payload[:overlap]
                if existing != incoming:
                    if start < self.parse_offset:
                        logger.debug(
                            "DirectionState[%s] ignoring conflicting retransmit over parsed bytes seq=%d",
                            self.direction,
                            seq,
                        )
                        return
                    log_func = logger.debug if existing and all(b == 0 for b in existing) else logger.warning
                    log_func(
                        "DirectionState[%s] replacing conflicting overlap at seq=%d "
                        "(existing=%s incoming=%s)",
                        self.direction,
                        seq,
                        existing[:8].hex(),
                        incoming[:8].hex(),
                    )
                    del self.buffer[start:]
                    self.buffer.extend(payload)
                    self._next_contig_seq = seq + len(payload)
                    self.parse_offset = min(self.parse_offset, start)
                    self._drain_pending()
                    return
            if overlap >= len(payload):
                return
            self.buffer.extend(payload[overlap:])
            self._next_contig_seq += len(payload) - overlap
            self._drain_pending()
            return

        self._store_pending(seq, payload)

    def _store_pending(self, seq: int, payload: bytes) -> None:
        end = seq + len(payload)

        for old_seq, old_payload in list(self._pending.items()):
            old_end = old_seq + len(old_payload)
            if old_seq <= seq and old_end >= end:
                return
            if seq <= old_seq and end >= old_end:
                self._pending_bytes -= len(old_payload)
                del self._pending[old_seq]

        existing = self._pending.get(seq)
        if existing is not None:
            if len(existing) >= len(payload):
                return
            self._pending_bytes -= len(existing)

        self._pending[seq] = payload
        self._pending_bytes += len(payload)

        while self._pending_bytes > _MAX_PENDING_BYTES and self._pending:
            farthest_seq = max(self._pending)
            dropped = self._pending.pop(farthest_seq)
            self._pending_bytes -= len(dropped)
            self.dropped_pending_segments += 1
            logger.warning(
                "DirectionState[%s] pending cache exceeded %d bytes, dropping segment at seq=%d",
                self.direction,
                _MAX_PENDING_BYTES,
                farthest_seq,
            )

    def _drain_pending(self) -> None:
        assert self._next_contig_seq is not None

        while self._pending:
            seq = min(self._pending)
            if seq > self._next_contig_seq:
                return

            payload = self._pending.pop(seq)
            self._pending_bytes -= len(payload)

            overlap = self._next_contig_seq - seq
            if overlap >= len(payload):
                continue
            self.buffer.extend(payload[overlap:])
            self._next_contig_seq += len(payload) - overlap

    def _trim_buffer(self) -> None:
        if not self.buffer:
            return

        logger.warning(
            "DirectionState[%s] buffer exceeded %d bytes, trimming buffered stream",
            self.direction,
            _MAX_BUFFER_SIZE,
        )
        self.trimmed_buffers += 1
        desired = _MAX_BUFFER_SIZE // 2
        if self.parse_offset > 0:
            trim = min(self.parse_offset, max(0, len(self.buffer) - desired))
        else:
            trim = max(0, len(self.buffer) - desired)
        if trim <= 0:
            return

        del self.buffer[:trim]
        self.stream_base += trim
        self.parse_offset = max(0, self.parse_offset - trim)
        if self._base_seq is not None:
            self._base_seq += trim


class _BoundedAckSet:
    """有界去重集合，淘汰最早的条目防止内存泄漏。"""

    def __init__(self, maxsize: int = RKPP_MAX_SEEN_ACKS) -> None:
        self._data: OrderedDict[tuple[int, str], None] = OrderedDict()
        self._maxsize = maxsize

    def __contains__(self, item: tuple[int, str]) -> bool:
        return item in self._data

    def add(self, item: tuple[int, str]) -> None:
        if item in self._data:
            return
        if len(self._data) >= self._maxsize:
            self._data.popitem(last=False)
        self._data[item] = None


@dataclass
class FlowState:
    flow_id: str
    client_ip: str
    client_port: int
    server_ip: str
    server_port: int
    c2s: DirectionState = field(default_factory=lambda: DirectionState("c2s"))
    s2c: DirectionState = field(default_factory=lambda: DirectionState("s2c"))
    seen_acks: _BoundedAckSet = field(default_factory=_BoundedAckSet)
    key: bytes | None = None
    _capture_integrity_generation: int = field(default=0, init=False, repr=False, compare=False)
    _capture_integrity_observation: int = field(default=0, init=False, repr=False, compare=False)
    _capture_integrity_busy: int = field(default=0, init=False, repr=False, compare=False)
    _capture_integrity_failed: bool = field(default=False, init=False, repr=False, compare=False)
    _capture_integrity_decoder_observed: bool = field(default=False, init=False, repr=False, compare=False)
    _capture_integrity_decode_failures: int = field(default=0, init=False, repr=False, compare=False)

    def capture_integrity_note_decode(self, packet: Be21Packet, *, failed: bool) -> None:
        """Called by the actual analyzer, never infer decoder success from TCP success.

        Known failures increment the flow baseline rather than permanently poisoning
        later fresh openings. The failed packet itself is not a certified event.
        """
        with _capture_integrity_lock:
            self._capture_integrity_decoder_observed = True
            if failed:
                self._capture_integrity_decode_failures += 1
            key = (self.flow_id, packet.direction, packet.stream_offset, packet.seq)
            record = _capture_integrity_packets.get(key)
            if (record is not None and not record["ambiguous"] and
                    record["snapshot"]["streamGeneration"] == self._capture_integrity_generation):
                record["snapshot"] = (
                    _capture_integrity_unknown("", self.flow_id, self._capture_integrity_generation)
                    if failed else _capture_integrity_flow_snapshot(self, "", 0))

    def __post_init__(self) -> None:
        # A generation is a FlowState instance, not a claim of seeing TCP SYN.
        with _capture_integrity_lock:
            self._capture_integrity_generation = next(_capture_integrity_generations)
            self.c2s._capture_integrity_owner = weakref.ref(self)
            self.s2c._capture_integrity_owner = weakref.ref(self)
            _capture_integrity_flows[self.flow_id] = weakref.ref(self)
            _capture_integrity_flows.move_to_end(self.flow_id)
            while len(_capture_integrity_flows) > _CAPTURE_INTEGRITY_MAX_FLOWS:
                _capture_integrity_flows.popitem(last=False)

    def direction_state(self, direction: str) -> DirectionState:
        return self.c2s if direction == "c2s" else self.s2c
