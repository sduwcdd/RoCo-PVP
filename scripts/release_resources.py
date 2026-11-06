"""Static, read-only inventory for the desktop release builder.

``discover(root)`` returns JSON-compatible resources, licenses, missing and
forbidden lists. It never imports application code, executes a referenced
script, copies data, or reads excluded personal files. Game Lua/disassembly
is inert provenance data; Python sources are reported for the compiler.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote, urlsplit


EXTERNAL = frozenset({"buff.json", "level_skill.json", "petbase.json",
                      "pokedex_pvp_usage.json", "roco_buff_calc_map.json", "skill.json"})
WEB = ("lab.html", "battle_workspace.html", "hud.html", "hud_duel.html",
       "battle.js", "simulation.js", "simulation.css", "battle_mechanics.js",
       "weather_view.js", "hud_bridge.js", "live_view.js")
STATIC_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
                             ".ico", ".woff", ".woff2", ".html", ".css", ".js", ".json"})
EXECUTABLE_SUFFIXES = frozenset({".py", ".pyc", ".pyo", ".pyd", ".exe", ".dll",
                                 ".ps1", ".bat", ".cmd", ".sh", ".cs", ".c", ".cpp"})
PRIVATE_PARTS = frozenset({"key", "keys", "user-data", "userdata", "replays", "logs",
                          "node_modules", ".git", "__pycache__"})
TP = "vendor/洛克PVP助手/app/wwwroot/"
PATH_KEYS = frozenset({"path", "local_path", "source_path", "manifest", "output",
                       "parser_path", "binary_path", "schema_path", "localization_path",
                       "files", "sources", "source_files", "manifest_path", "resource_group"})
PROJECT_PREFIXES = ("data/", "artifacts/", "vendor/", "web/", "lab/", "docs/")


def _values(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _values(key)
            yield from _values(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _values(item)
    elif isinstance(value, (str, Path)):
        yield str(value)


def _constant(node, names):
    """Evaluate only pathlib construction and literal constants, never Python."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return names[node.id]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_constant(item, names) for item in node.elts]
    if isinstance(node, ast.Dict):
        return {_constant(k, names): _constant(v, names) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.BinOp):
        left, right = _constant(node.left, names), _constant(node.right, names)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Div):
            return Path(left) / right
    if isinstance(node, ast.Attribute):
        value = _constant(node.value, names)
        if isinstance(value, Path) and node.attr in ("parent", "parents"):
            return getattr(value, node.attr)
    if isinstance(node, ast.Subscript):
        return _constant(node.value, names)[_constant(node.slice, names)]
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "Path":
            return Path(*[_constant(arg, names) for arg in node.args])
        if isinstance(node.func, ast.Attribute) and node.func.attr == "resolve" and not node.args:
            value = _constant(node.func.value, names)
            if isinstance(value, Path):
                return value.resolve()
    raise ValueError("Not a static resource expression")


def collect_licenses(root):
    """Return existing notices from the actual selected runtimes, not vendor trees."""
    root = Path(root).resolve()
    selected = [("project", root / "LICENSE"),
                ("third-party-helper", root / "vendor/洛克PVP助手/app/THIRD-PARTY-NOTICES.txt"),
                ("electron", root / "overlay/node_modules/electron/dist/LICENSE"),
                ("chromium", root / "overlay/node_modules/electron/dist/LICENSES.chromium.html")]
    package_root = root / ".venv-rkpp/Lib/site-packages"
    for package in ("scapy", "pycryptodome", "protobuf", "msgpack"):
        for info in sorted(package_root.glob(package + "-*.dist-info")):
            for path in sorted(info.rglob("*")):
                if path.is_file() and re.match(r"^(licen[cs]e|copying|notice)(\.|$)", path.name, re.I):
                    selected.append((info.name, path))
    return [{"name": name, "path": path.relative_to(root).as_posix()}
            for name, path in selected if path.is_file() and path.resolve().is_relative_to(root)]


def discover(root):
    """Find release data without scanning whole artifacts/vendor directories.

    Reports contain ``path``, ``source`` and ``reason``. Missing/forbidden files
    are never included. A caller must review these reports before packaging;
    Python-source reports identify compile-time provenance dependencies.
    """
    root = Path(root).resolve()
    resources, pending, visited, attempted = set(), [], set(), set()
    reports = {"missing": set(), "forbidden": set()}

    def report(kind, value, source, reason):
        reports[kind].add((str(value), str(source), reason))

    def normalize(value, source):
        text = str(value).replace("\\", "/")
        if "\0" in text:
            report("forbidden", text, source, "invalid_path")
            return None
        windows = PureWindowsPath(text)
        native = Path(text)
        if windows.drive and (not native.is_absolute() or not native.resolve().is_relative_to(root)):
            parts = windows.parts
            markers = [i for i, part in enumerate(parts) if part.casefold() == root.name.casefold()]
            if not markers:
                report("forbidden", text, source, "outside_project")
                return None
            text = "/".join(parts[markers[-1] + 1:])
        path = Path(text)
        if ":" in text and not PureWindowsPath(text).drive:
            report("forbidden", text, source, "invalid_path")
            return None
        if not path.is_absolute() and not text.startswith(PROJECT_PREFIXES):
            path = root / Path(source).parent / path
        elif not path.is_absolute():
            path = root / path
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            report("forbidden", text, source, "outside_project")
            return None
        return resolved.relative_to(root).as_posix()

    def add(value, source="release_seed"):
        request = (str(value), str(source))
        if request in attempted:
            return
        attempted.add(request)
        relative = normalize(value, source)
        if relative is None:
            return
        if relative == "data/rules/reviewed-*.json":
            matches = sorted((root / "data/rules").glob("reviewed-*.json"))
            if not matches:
                report("missing", relative, source, "glob_no_matches")
            for match in matches:
                add(match, source)
            return
        path = root / relative
        parts = [part.casefold() for part in Path(relative).parts]
        name = path.name.casefold()
        if (set(parts) & PRIVATE_PARTS or "user-team" in relative.casefold()
                or name in {"rkpp_settings.json", "key.txt"}
                or name.startswith(("decoded_packets", "opencode_summary", "move_summary", "_probe_"))
                or path.suffix.lower() in {".key", ".pcap", ".pcapng", ".log"}
                or any(part.startswith("rkpp_") and part not in {"rkpp_data.sqlite"} for part in parts[:-1])):
            report("forbidden", relative, source, "personal_or_runtime_state")
            return
        if path.suffix.lower() in EXECUTABLE_SUFFIXES:
            report("forbidden", relative, source, "compile_or_install_separately")
            return
        allowed = (relative.startswith(("data/rules/", "data/bwiki/", "artifacts/", "web/", TP))
                   or relative in {"vendor/rkpp/rkpp_data.sqlite", "vendor/洛克PVP助手/app/rkpp/rkpp_data.sqlite"}
                   or (relative.startswith("docs/verification/") and path.suffix.lower() == ".json")
                   or (relative.startswith("data/external/") and path.name in EXTERNAL
                       and path.parent == root / "data/external"))
        if not allowed:
            report("forbidden", relative, source, "not_a_runtime_resource_root")
        elif not path.is_file():
            report("missing", relative, source, "not_a_file")
        elif relative not in resources:
            resources.add(relative)
            pending.append(relative)

    def references(value, owner, key=""):
        if isinstance(value, dict):
            for name, item in value.items():
                # Extraction manifests distinguish archive member names from
                # actual files on disk through output/local_path.
                if name == "path" and ("output" in value or "local_path" in value
                                       or ("pak" in value and isinstance(item, str)
                                           and item.startswith(("../../../NRC/", "../../../Engine/")))):
                    continue
                if name in {"resource_path", "archive_path"} and isinstance(item, str) and item.startswith("../../../NRC/"):
                    continue
                if name == "probe_dir" and isinstance(item, str):
                    probe = normalize(item, owner)
                    if probe is not None:
                        add(probe + "/battle_analysis/provenance.json", owner)
                        add(probe + "/parse_roco_tables.py", owner)
                    continue
                if isinstance(name, str) and name.startswith(PROJECT_PREFIXES):
                    references(name, owner)
                if isinstance(item, (dict, list)):
                    # Embedded extraction entries retain the original manifest's
                    # relative output layout, not the enclosing bundle's folder.
                    context = owner
                    if name == "extraction" and isinstance(value.get("manifest"), str):
                        context = normalize(value["manifest"], owner) or owner
                    references(item, context, str(name))
                elif isinstance(item, str) and (name in PATH_KEYS or item.startswith(PROJECT_PREFIXES + ("../", "/"))
                                               or (len(item) > 1 and item[1] == ":")):
                    references(item, owner, str(name))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list, str)):
                    references(item, owner, key)
        elif isinstance(value, str):
            text = value.replace("\\", "/")
            if "://" in text or text.startswith(("local:", "$PROJECT/")):
                return
            if text.startswith(("/Game/", "/Script/")):
                return
            if text.startswith(PROJECT_PREFIXES + ("../", "/")) or (len(text) > 1 and text[1] == ":"):
                if Path(text).suffix:
                    add(text, owner)
            elif key in PATH_KEYS and Path(text).suffix:
                add(text, owner)

    add("data/bwiki/latest.json")
    pointer = root / "data/bwiki/latest.json"
    try:
        data = json.loads(pointer.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("Snapshot pointer must be an object")
        snapshot = data.get("path") or data.get("snapshot_id") or data.get("directory")
        if not isinstance(snapshot, str) or not snapshot or any(c in snapshot for c in "\\/:") or snapshot in (".", ".."):
            report("forbidden", str(snapshot), "data/bwiki/latest.json", "invalid_snapshot_id")
        else:
            add(f"data/bwiki/{snapshot}/catalog.json", "data/bwiki/latest.json")
            for name in ("phase-config-1.json", "phase-config-1.manifest.json",
                         "rule-config-1.json", "rule-config-1.manifest.json"):
                add(f"data/rules/{snapshot}/{name}")
    except (OSError, ValueError, TypeError) as error:
        report("missing", "data/bwiki/latest.json", "release_seed", type(error).__name__)
    for path in sorted((root / "data/rules").glob("*.json")):
        add(path)
    for name in sorted(EXTERNAL):
        add("data/external/" + name)
    for name in WEB:
        add("web/" + name)
    add("web/assets/roco/manifest.json")
    for folder in ("web/assets/roco/pet-avatars", "web/assets/roco/skill-icons", "web/assets/roco/type-icons", "web/assets/roco/bloodline-icons",
                   TP + "roco-pet-avatars-id", TP + "roco-skill-icons", TP + "roco-type-icons"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and path.suffix.lower() in STATIC_SUFFIXES:
                add(path)
    add("vendor/rkpp/rkpp_data.sqlite")
    if (root / (TP + "battle-hud-full.html")).is_file():
        add(TP + "battle-hud-full.html")

    # Parse application imports and module constants without loading the app,
    # opening sockets, reading capture logs or starting a replay database.
    modules, todo = set(), ["server"]
    while todo:
        module = todo.pop()
        if module in modules:
            continue
        modules.add(module)
        path = root / "lab" / (module + ".py")
        if not path.is_file():
            report("missing", path.relative_to(root), "python_import", "source_unavailable_to_inventory")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        names = {"__file__": str(path), "ROOT": root, "_ROOT": root}
        for statement in tree.body:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                try:
                    value = _constant(statement.value, names)
                except (ValueError, TypeError, KeyError, AttributeError, IndexError):
                    continue
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        names[target.id] = value
                for candidate in _values(value):
                    text = candidate.replace("\\", "/")
                    if Path(text).suffix and (text.startswith(PROJECT_PREFIXES) or Path(text).is_absolute()):
                        add(text, path.relative_to(root).as_posix())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if module_name.startswith("lab.") or (node.level and module_name):
                    todo.append(module_name.removeprefix("lab.").split(".")[0])
                elif module_name == "lab" or (node.level and not module_name):
                    todo.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                todo.extend(alias.name.split(".")[1] for alias in node.names if alias.name.startswith("lab."))

    while pending:
        relative = pending.pop()
        if relative in visited:
            continue
        visited.add(relative)
        path = root / relative
        if path.suffix.lower() == ".json":
            try:
                references(json.loads(path.read_text(encoding="utf-8-sig")), relative)
            except (OSError, ValueError) as error:
                report("missing", relative, relative, "unreadable_json:" + type(error).__name__)
        elif path.suffix.lower() in {".html", ".css", ".js"}:
            text = path.read_text(encoding="utf-8-sig")
            urls = re.findall(r'''(?:src|href)\s*=\s*["']([^"']+)["']|url\(\s*["']?([^)'"\s]+)''', text)
            for groups in urls:
                url = next(part for part in groups if part)
                parsed = urlsplit(url)
                if parsed.scheme or parsed.netloc or not Path(parsed.path).suffix or "${" in url:
                    continue
                target = unquote(parsed.path)
                if target.startswith("/assets/roco/"):
                    add("web" + target, relative)
                elif target.startswith("/tp/"):
                    add(TP + target[4:], relative)
                elif target.startswith("/"):
                    if target[1:] in WEB:
                        add("web/" + target[1:], relative)
                    elif relative.startswith(TP):
                        add(TP + target.lstrip("/"), relative)
                else:
                    add(target, relative)

    result = {"resources": sorted(resources), "licenses": collect_licenses(root)}
    for kind, rows in reports.items():
        result[kind] = [{"path": path, "source": source, "reason": reason}
                        for path, source, reason in sorted(rows)]
    return result
