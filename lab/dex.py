"""Read-only Rocoduel snapshot utilities; no JavaScript execution is used."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class SnapshotError(ValueError):
    """A source document cannot be interpreted without guessing."""


def decode_router_html(html: str) -> dict[str, Any]:
    """Decode the plain JSON reference subset of turbo-stream v2.

    Constants are from turbo-stream/v2.4.1/src/utils.ts: -5 NULL,
    -7 UNDEFINED and -1 HOLE. Only NULL is accepted by this JSON catalog.
    Unknown sentinels, typed values, cycles and deferred streams fail closed.
    """
    chunks = re.findall(r'streamController\.enqueue\(("(?:[^"\\]|\\.)*")\)', html)
    if len(chunks) != 1:
        raise SnapshotError(f"Expected one complete data chunk, found {len(chunks)}")
    try:
        nodes = json.loads(json.loads(chunks[0]))
    except (ValueError, TypeError) as exc:
        raise SnapshotError("Malformed stream JSON") from exc
    if not isinstance(nodes, list) or not nodes:
        raise SnapshotError("Expected nonempty reference array")
    done: dict[int, Any] = {}
    visiting: set[int] = set()

    def decode(index: int) -> Any:
        if type(index) is not int:
            raise SnapshotError(f"Reference must be integer: {index!r}")
        if index == -5:
            return None
        if index < 0:
            raise SnapshotError(f"Unsupported special reference {index}")
        if index >= len(nodes):
            raise SnapshotError(f"Reference out of bounds: {index}")
        if index in visiting:
            raise SnapshotError("Cyclic reference is not a JSON catalog")
        if index in done:
            return done[index]
        visiting.add(index)
        value = nodes[index]
        if isinstance(value, dict):
            result = {}
            for key, ref in value.items():
                if not re.fullmatch(r"_\d+", key):
                    raise SnapshotError(f"Unexpected encoded key {key!r}")
                name = decode(int(key[1:]))
                if not isinstance(name, str) or name in result:
                    raise SnapshotError("Non-string or duplicate object key")
                result[name] = decode(ref)
        elif isinstance(value, list):
            result = [decode(ref) for ref in value]
        elif value is None or isinstance(value, (str, bool, int, float)):
            result = value
        else:
            raise SnapshotError(f"Unsupported node: {type(value).__name__}")
        visiting.remove(index)
        done[index] = result
        return result

    root = decode(0)
    if not isinstance(root, dict) or not isinstance(root.get("loaderData"), dict):
        raise SnapshotError("Missing loaderData")
    if root.get("errors"):
        raise SnapshotError(f"Server supplied route errors: {root['errors']!r}")
    return root["loaderData"]


def load_catalog(root: str | Path | None = None) -> dict[str, Any]:
    base = Path(root) if root else Path(__file__).resolve().parents[1] / "data" / "rocoduel"
    if (base / "catalog.json").exists():
        target = base / "catalog.json"
    else:
        pointer = json.loads((base / "latest.json").read_text(encoding="utf-8"))
        target = (base / pointer["snapshot_id"] / "catalog.json").resolve()
        if base.resolve() not in target.parents:
            raise SnapshotError("Snapshot path leaves data directory")
    return json.loads(target.read_text(encoding="utf-8"))
