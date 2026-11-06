"""Detect the live 洛克王国：世界 game process and invalidate capture keys when it exits."""
from __future__ import annotations

import ctypes
import os
import re
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable

GAME_PROCESS_NAMES = {"nrc-win64-shipping.exe"}
GAME_TITLE_RE = re.compile(r"洛克王国|roco world", re.I)
EXCLUDE_TITLE_RE = re.compile(r"PVP助手|洛克沙盘|PVP 对战辅助|ChatGPT|文件资源管理器")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH = 32768

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
psapi.EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
psapi.EnumProcesses.restype = wintypes.BOOL


def _process_image(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(MAX_PATH)
        buf = ctypes.create_unicode_buffer(MAX_PATH)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def list_game_processes() -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    ids = (wintypes.DWORD * 4096)()
    needed = wintypes.DWORD(0)
    if not psapi.EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(needed)):
        return found
    count = min(int(needed.value / ctypes.sizeof(wintypes.DWORD)), len(ids))
    for i in range(count):
        pid = int(ids[i])
        if pid <= 4:
            continue
        image = _process_image(pid)
        name = os.path.basename(image).lower()
        if name in GAME_PROCESS_NAMES:
            found.append({"pid": pid, "name": name, "path": image, "source": "process"})
    return found


def game_process_snapshot() -> dict[str, object]:
    processes = list_game_processes()
    alive = len(processes) > 0
    first = processes[0] if processes else None
    return {
        "game_process_alive": alive,
        "game_process_name": (first or {}).get("name") or "",
        "game_process_pid": (first or {}).get("pid") or 0,
        "game_process_count": len(processes),
    }


def start_game_key_watchdog(invalidate: Callable[[str], None], logger: Callable[[str], None] | None = None) -> threading.Event:
    stop = threading.Event()

    def _run() -> None:
        bound: int | None = None
        while not stop.wait(1.5):
            try:
                snapshot = game_process_snapshot()
                pid = int(snapshot.get("game_process_pid") or 0)
                if pid <= 0:
                    if bound is not None:
                        reason = f"game-process-exited pid={bound}"
                        if logger:
                            logger("[game] " + reason)
                        invalidate(reason)
                        bound = None
                    continue
                if bound is None:
                    bound = pid
                    if logger:
                        logger(f"[game] bound pid={pid} name={snapshot.get('game_process_name')}")
                elif bound != pid:
                    reason = f"game-process-changed {bound} -> {pid}"
                    if logger:
                        logger("[game] " + reason)
                    invalidate(reason)
                    bound = pid
            except Exception as exc:
                if logger:
                    logger(f"[game] watchdog error {exc}")

    thread = threading.Thread(target=_run, name="rkpp-game-watch", daemon=True)
    thread.start()
    return stop
