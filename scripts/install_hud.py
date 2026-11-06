"""Install the third-party in-game HUD page as /hud.

The upstream file is copied verbatim except for one injected script tag that
feeds it a workbench snapshot (the page itself only knows localStorage and a
WebView2 host bridge, neither of which exists in a normal browser tab).

Run:  python scripts/install_hud.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r"E:\洛克PVP助手\app\wwwroot\battle-hud-full.html")
TARGET = ROOT / "web" / "hud.html"

HEADER = """<!--
  battle-hud-full.html 照抄自第三方发行版「青空洛克PVP助手」app\\wwwroot\\battle-hud-full.html。
  原文件除下方一行 /hud_bridge.js 之外未作改动；样式、结构、字段读取逻辑全部保持原样。
  hud_bridge.js 把本工作台发布到 localStorage["roco.workbench.hud.v1"] 的局面快照，
  转写成本页面原本期望的 roco.battleHud.* 键。
-->
"""

BRIDGE = '<script src="/hud_bridge.js"></script>\n'


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def main() -> int:
    if not SOURCE.is_file():
        raise SystemExit(f"source missing: {SOURCE}")
    origin = SOURCE.read_text(encoding="utf-8")
    if "/hud_bridge.js" in origin:
        raise SystemExit("source already contains the bridge tag; refusing to inject twice")
    marker = "<style>"
    if marker not in origin:
        raise SystemExit("unexpected source layout: <style> not found")
    body = origin.replace(marker, BRIDGE + marker, 1)
    text = HEADER + body
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET}")
    print(f"source sha {sha(origin)}  target sha {sha(text)}")
    print(f"chars {len(text)}  bridge tags {text.count('/hud_bridge.js')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
