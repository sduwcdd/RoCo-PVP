"""打印 JSON 的骨架结构（键名 + 类型/长度），用于读懂不认识的消息字段，避免整份 dump。

用法：
    python scripts/json_skeleton.py <json文件> [--depth 4] [--max-list 2]
    python scripts/json_skeleton.py <json文件> --path content.battle_info
"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")


def describe(value: object, depth: int, max_depth: int, max_list: int, indent: int, prefix: str) -> None:
    pad = "  " * indent
    if isinstance(value, dict):
        if depth >= max_depth:
            print(f"{pad}{prefix}{{...{len(value)} keys}}")
            return
        print(f"{pad}{prefix}{{")
        for key, item in list(value.items())[:40]:
            describe(item, depth + 1, max_depth, max_list, indent + 1, f"{key}: ")
        if len(value) > 40:
            print(f"{pad}  ... +{len(value) - 40} more keys")
        print(f"{pad}}}")
    elif isinstance(value, list):
        if not value:
            print(f"{pad}{prefix}[]")
            return
        print(f"{pad}{prefix}[len={len(value)}]")
        for index, item in enumerate(value[:max_list]):
            describe(item, depth + 1, max_depth, max_list, indent + 1, f"[{index}] ")
    else:
        text = repr(value)
        if len(text) > 80:
            text = text[:77] + "..."
        print(f"{pad}{prefix}{type(value).__name__} = {text}")


def resolve(root: object, path: str) -> object:
    current = root
    for part in [p for p in path.split(".") if p]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            current = current[int(part)] if part.isdigit() and int(part) < len(current) else None
        else:
            return None
    return current


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    depth = 4
    max_list = 2
    sub_path = ""
    argv = sys.argv[2:]
    for index, arg in enumerate(argv):
        if arg == "--depth" and index + 1 < len(argv):
            depth = int(argv[index + 1])
        if arg == "--max-list" and index + 1 < len(argv):
            max_list = int(argv[index + 1])
        if arg == "--path" and index + 1 < len(argv):
            sub_path = argv[index + 1]

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    target = resolve(data, sub_path) if sub_path else data
    print(f"== {path} path={sub_path or '<root>'} ==")
    describe(target, 0, depth, max_list, 0, "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
