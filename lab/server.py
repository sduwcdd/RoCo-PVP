"""Local, read-only catalog service and stateless belief calculations.

Run: python -m lab.server --port 8766
The historic NRC_AI server is deliberately not started by this entry point.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from lab.belief import BeliefFilter
from lab.team_code import parse_team_code
from lab.team_import import parse_team_codes, recognize_opponent, search_opponent_teams
from lab.ruleset import BwikiRuleset
from lab.turn_plan import plan_joint_actions
from lab.action_runtime import execute_joint_actions, execute_action_status_sequence
from lab.status_runtime import execute_status_phase
from lab.switch_runtime import execute_switch_fragment

ROOT = Path(__file__).resolve().parents[1]
from lab.release_paths import build_identity, user_root
_RELEASE_IDENTITY = build_identity()
_DESKTOP_SOURCE_HASH = (_RELEASE_IDENTITY['source_hash'] if _RELEASE_IDENTITY else
    hashlib.sha256(b"".join(p.name.encode("utf-8") + b"\0" + p.read_bytes()
                           for p in sorted((ROOT / "lab").glob("*.py")))).hexdigest())
DATA = ROOT / "data" / "bwiki"
TEAM_LIBRARY = ROOT / "data" / "reference" / "team-code-20261025" / "user-team-codes.txt"
USER_TEAM_LIBRARY = ROOT / "data" / "external" / "user-teams-20261030" / "team-codes.txt"
if _RELEASE_IDENTITY:
    TEAM_LIBRARY = USER_TEAM_LIBRARY = user_root() / 'teams/team-codes.txt'
    TEAM_LIBRARY.parent.mkdir(parents=True, exist_ok=True)
    if not TEAM_LIBRARY.exists():
        TEAM_LIBRARY.write_text('', encoding='utf8')

# 工作台发布给 HUD 的局面快照。原先只放在 localStorage，浏览器标签之间够用；
# 桌面悬浮 HUD 是独立进程，localStorage 不互通，所以这里做一进程中转。
# 只保存在内存，重启即清空；HUD 侧读不到就沿用本地缓存。
HUD_LOCK = threading.Lock()
HUD_SNAPSHOT: dict = {"at": 0.0, "payload": None}
HUD_SNAPSHOT_LIMIT = 1_500_000
WEB_ASSETS = ROOT / "web" / "assets" / "roco"
EXTERNAL_DATA = ROOT / "data" / "external"
# 第三方「青空洛克PVP助手」的前端根目录（只读）。它的 HUD 页面 battle-hud-full.html
# 完全靠 localStorage 渲染，且引用的图标/数据都是绝对路径，所以这里把整个 wwwroot
# 以只读静态目录暴露出来，缺的图标也能回退到这里，不必复制 400MB 资源。
TP_ROOT = ROOT / "vendor" / "洛克PVP助手" / "app" / "wwwroot"
# /hud-pro?split=1 用：把原版的「我方一行 / 敌方一行」改成「左我方 / 右敌方」两栏。
# 只注入 CSS，不改 vendor 里的 html。
SPLIT_CSS = (
    "<style>"
    "body{padding:18px 8px 8px 8px !important;align-items:stretch !important;}"
    ".hud{width:100% !important;height:100% !important;"
    "grid-template-columns:1fr 1fr !important;grid-template-rows:1fr !important;gap:10px !important;}"
    "</style>"
)
STATIC_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


def release_public_body(path, body):
    """Keep UI inputs/results while withholding developer-only rule dumps."""
    if os.environ.get('ROCO_RELEASE') != '1' or not isinstance(body, dict):
        return body
    if path.startswith('/api/simulation/'):
        private = {'source_defaults', 'damage_traces', 'numeric_policy', 'weather_numeric_policy', 'status_damage_policy'}
        return {k: v for k, v in body.items() if k not in private}
    if path == '/api/pvp/rules':
        return {**{k: body[k] for k in ('profile_id', 'version', 'settings', 'battle', 'uncertainty') if k in body},
                'damage': {'runtime': 'shared-runtime', 'critical_enabled': False}}
    if path == '/api/action-mechanics':
        def trim(value):
            if isinstance(value, dict):
                return {k: trim(v) for k, v in value.items() if k not in {'raw', 'historical_pool', 'slot_update_source'}}
            return [trim(v) for v in value] if isinstance(value, list) else value
        result = trim({k: v for k, v in body.items() if k != 'game_evidence'})
        for row in result.get('response_energy', {}).values():
            row['effects'] = [{k: effect[k] for k in ('op', 'target', 'amount') if k in effect}
                              for effect in row.get('effects', [])]
        return result
    if path == '/api/preview/damage':
        return {**body, 'results': [{k: v for k, v in row.items() if k != 'formula_trace'} for row in body.get('results', [])]}
    return body

BLOCKERS = [
    "研究引擎已接入多类特性、印记、天气、换人与技能组合；未覆盖全部技能及跨机制组合，不能认定完整复刻。",
    "游戏文件的历史资源版本、触发时机和部分参数语义尚待核对。",
    "研究伤害候选可显式试算，但尚未从游戏文件确认完整公式或通过实战校准。",
    "已接入2026-09-28天梯单维使用率快照，尚无完整联合配置先验或训练完成的策略模型。",
]


_SKILL_ICON_ALIAS = None


def hud_payload(payload):
    """Keep solver diagnostics server-side; the HUD only needs established results."""
    if not isinstance(payload, dict):
        return payload
    result = dict(payload)
    for name in ("runtime", "state"):
        if not isinstance(payload.get(name), dict):
            continue
        block = dict(payload[name])
        for key in ("myTeam", "enemyTeam"):
            if not isinstance(block.get(key), list):
                continue
            block[key] = [dict(p) for p in block[key]]
            for entry in block[key]:
                info = entry.get("configurationInference")
                if isinstance(info, dict):
                    entry["configurationInference"] = {k:info[k] for k in
                        ("status", "known_talents", "known_nature", "protocol_selection", "panel_ranges") if k in info}
        result[name] = block
    return result


def skill_icon_alias(skill_id):
    """Catalog skill id -> the game icon resource id used as the file name."""
    global _SKILL_ICON_ALIAS
    if _SKILL_ICON_ALIAS is None:
        try:
            manifest = json.loads((WEB_ASSETS / "manifest.json").read_text(encoding="utf-8"))
            _SKILL_ICON_ALIAS = dict(manifest.get("skill_icons") or {})
        except (OSError, ValueError, AttributeError):
            _SKILL_ICON_ALIAS = {}
    key = str(skill_id)
    alias = _SKILL_ICON_ALIAS.get(key)
    if alias:
        return alias
    # Runtime/unpublished moves also carry an icon resource; wire IDs add two digits.
    from lab import battle_data
    raw = battle_data._skills().get(key)
    if raw is None and key.isdigit() and int(key) > 9_999_999:
        raw = battle_data._skills().get(str(int(key) // 100))
    icon = str((raw or {}).get("icon") or "").rsplit("/", 1)[-1].split(".")[0]
    return icon + ".png" if icon.isdigit() else None


from lab.catalog_store import load_catalog


def status(data_root=DATA):
    result = dict(mode="research", training_allowed=False, blockers=list(BLOCKERS),
                  snapshot_id=None, counts=dict(forms=0, moves=0, details=0, traits=0, natures=0),
                  calibrated_real_battles=0, policy_available=False,
                  primary_source="https://wiki.biligame.com/nrc/精灵图鉴",
                  rules_authority="BWIKI is authoritative for current catalog fields; calibrated mechanisms and historical extracted evidence remain explicitly version-bound",
                  research_execution={"ordinary_skill_turn": True, "manual_faint_replacement": True,
                                      "game_file_effects": True, "complete_battle": False,
                                      "battle_page_auto_simulation": True,
                                      "automatic_weather": True},
                  reward={"win": 1, "loss": 0, "draw": 0, "intermediate": 0, "truncated": 0})
    from lab.simulation import ENGINE_REVISION
    result["engine_revision"] = ENGINE_REVISION
    result["progress_document"] = "docs/PROJECT_STATUS.md"
    result["desktop_support"] = {"protocol": 1, "workspace": str(ROOT), "source_hash": _DESKTOP_SOURCE_HASH}
    result["calibration_scope"] = "Partial real packet/panel checks exist; no complete battle calibration report accepted by RL gate."
    try:
        catalog, digest, path = load_catalog(data_root)
        result.update(snapshot_id=catalog.get("snapshot_id", path.parent.name),
                      snapshot_sha256=digest, source=catalog.get("source"),
                      validation=catalog.get("validation"),
                      source_version=catalog.get("source_version"),
                      counts={k: len(catalog[k]) for k in ("forms", "moves", "details", "traits", "natures")})
    except (OSError, ValueError, KeyError) as exc:
        result["blockers"].insert(0, "图鉴快照尚未发布或校验失败：" + str(exc))
    return result


def policy_advice():
    """An unavailable policy has no probability distribution or simulated result."""
    return {"status": "model_unavailable", "actions": [], "model": None,
            "reason": "策略模型尚未训练；目前没有可验证的行动概率或后果预测。",
            "training_allowed": False, "calibrated": False}


def rules_coverage():
    catalog, digest, _ = load_catalog()
    programs = BwikiRuleset(catalog).programs()
    from lab.rule_config import load_bundle
    bundle = load_bundle(catalog)
    capability_counts = {category: {name: sum(rule["capabilities"][name] for rule in records.values())
                         for name in ("description_structured", "isolated_components_supported",
                                      "full_battle_executable", "real_game_calibrated")}
                         for category, records in bundle["records"].items()}
    return {key: programs[key] for key in ("snapshot_id", "source_version", "compiler_version", "counts",
                                          "training_allowed", "executable", "real_game_verified")} | {
        "snapshot_sha256": digest,
        "configuration_schema": bundle["schema_version"], "capability_counts": capability_counts,
        "coverage_scope": "bwiki_declarative_config_only; excludes reviewed game-file runtime components",
        "skill_runtime_natural_language_parsing": False,
        "legacy_term_classification_remaining": ["mark glossary prefix index; no new effect execution"],
        "notice": "compiled 仅表示完整描述已有结构化操作；不是可执行完整对战或实战验证。未支持效果不回退为普通伤害。"}


def public_catalog(catalog):
    """Keep complete audit data on disk; omit repeated records from the UI payload."""
    result = {key: value for key, value in catalog.items() if key not in ("details", "config")}
    result["details"] = {
        key: {"learnset": detail["learnset"], "trait": detail.get("trait"),
              "source_learnset_id": detail.get("source_learnset_id")}
        for key, detail in catalog["details"].items()
    }
    return result


def update_belief(payload):
    if not isinstance(payload, dict):
        raise ValueError("请求应为对象")
    belief = BeliefFilter.from_dict(payload["belief"]) if "belief" in payload else BeliefFilter(payload.get("candidates"))
    event = payload.get("event")
    if event:
        if not isinstance(event, dict):
            raise ValueError("event 应为对象")
        if event.get("kind") == "revealed_move":
            # Borrowed or generated moves must not eliminate carried-build candidates.
            if event.get("confirmed_carried") is not True:
                raise ValueError("只有确认属于原配招的技能才能用于排除候选")
            belief = belief.observe_revealed_move(event["id"], event["move_id"])
        elif event.get("kind") == "damage":
            belief = belief.observe_damage(event["id"], event["damage"], event["predictions"],
                                           event.get("measurement_tolerance", 0))
        elif event.get("kind") == "damage_distribution":
            belief = belief.observe_damage_distribution(event["id"], event["damage"], event["predictions"],
                                                        event.get("measurement_tolerance", 0),
                                                        prediction_source=event.get("prediction_source"))
        else:
            raise ValueError("未知观测类型")
    return {"belief": belief.to_dict(), "summary": belief.summary(),
            "prediction_verified": False, "training_allowed": False,
            "notice": "候选条件概率，不是天梯使用率；伤害预测由调用者提供，未核实其游戏准确性。"}


def import_request(path, payload):
    """Re-parse on the server; never accept client-supplied validity claims."""
    if not isinstance(payload, dict):
        raise ValueError("请求应为对象")
    catalog, digest, _ = load_catalog()
    if path == "/api/team-code/parse":
        result = parse_team_code(payload.get("code"), catalog)
    elif path == "/api/team-codes/parse":
        result = parse_team_codes(payload.get("text"), catalog)
    elif path == "/api/opponent/recognize":
        result = recognize_opponent(payload.get("text"), catalog)
    elif path == "/api/opponent/search":
        sources, batches = [], []
        for library in (TEAM_LIBRARY, USER_TEAM_LIBRARY):
            raw = library.read_bytes()
            source = {"path": library.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}
            batch = search_opponent_teams(payload.get("text"), catalog, raw.decode("utf-8-sig"))
            for match in batch["matches"]:
                match["library_source"] = source
            sources.append(source)
            batches.append(batch)
        result = {**batches[0], "matches": [m for batch in batches for m in batch["matches"]],
                  "total_teams": sum(b["total_teams"] for b in batches),
                  "matched_teams": sum(b["matched_teams"] for b in batches)}
        result["library_source"] = {"kind": "user_supplied_codes", "sources": sources,
                                    "sha256": hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()}
    elif path == "/api/rules/skill":
        result = BwikiRuleset(catalog).plan(payload.get("skill_id"), payload.get("defender_form_id"))
    elif path == "/api/rules/turn-plan":
        result = plan_joint_actions(catalog, payload.get("state"), payload.get("actions"))
    elif path == "/api/rules/execute-actions":
        # HTTP clients cannot inject a formula or pass observed damage as prediction.
        # Attacks remain blocked here until a reviewed numeric resolver is available.
        result = execute_joint_actions(catalog, payload.get("state"), payload.get("actions"), payload.get("context"))
    elif path == "/api/rules/execute-statuses":
        result = execute_status_phase(catalog, payload.get("state"), payload.get("context"))
    elif path == "/api/rules/execute-switch":
        result = execute_switch_fragment(catalog, payload.get("state"), payload.get("side"),
                                         payload.get("target_slot"), payload.get("context"))
    elif path == "/api/rules/execute-action-status-sequence":
        result = execute_action_status_sequence(catalog, payload.get("state"), payload.get("actions"), payload.get("context"))
    elif path in ("/api/research/turn", "/api/research/replace", "/api/research/game-skill"):
        from lab.research_api import research_request
        result = research_request(path, payload, catalog)
    elif path == "/api/weather/replay":
        from lab.weather_replay import replay_weather_records
        result = replay_weather_records(catalog, payload.get("session"))
    elif path == "/api/inference/damage":
        from lab.damage_inference import infer_damage_candidates
        result = infer_damage_candidates(catalog, payload.get("session"))
    elif path == "/api/preview/damage":
        from lab.damage_preview import preview_damage
        result = preview_damage(catalog, payload)
    elif path in ("/api/simulation/prepare", "/api/simulation/demo", "/api/simulation/start", "/api/simulation/act", "/api/simulation/replace", "/api/simulation/magic"):
        from lab.simulation import simulation_request
        result = simulation_request(path, payload, catalog)
    else:
        raise ValueError("未知导入接口")
    result["snapshot_sha256"] = digest
    return result


def form_skill_pool(catalog, form_id):
    """Possible skills and learning conditions, never an observed carried set."""
    detail = catalog["details"].get(str(form_id))
    if not detail or not detail.get("learnset"):
        raise ValueError("该具体形态没有可核对的技能学习资料")
    rows = {}
    for category in ("pool", "native", "stones", "legacy", "legendary"):
        for entry in detail["learnset"].get(category, []):
            source = {"category": category, **(entry if isinstance(entry, dict) else {"move": entry})}
            mid = source.get("move")
            if type(mid) is not int:
                continue
            record = catalog["moves"].get(str(mid), {})
            row = rows.setdefault(mid, {"skillId": mid, "name": record.get("name", {}).get("zh") or f"技能 {mid}",
                "type": record.get("type"), "kind": record.get("kind"), "energy": record.get("energy"),
                "power": record.get("power"), "description": record.get("desc", {}).get("zh", ""), "sources": []})
            row["sources"].append({key: value for key, value in source.items() if key in ("category", "level", "stage", "bloodline")})
    return {"form_id": form_id, "snapshot_id": catalog["snapshot_id"],
            "source_learnset_id": detail.get("source_learnset_id"),
            "skills": sorted(rows.values(), key=lambda row: (row["name"], row["skillId"])),
            "notice": "图鉴可学习技能，包含需满足血脉、等级、阶段等条件的候选，不代表实际携带。"}


class Handler(BaseHTTPRequestHandler):
    server_version = "RocoResearch/0.1"

    def local_request_allowed(self):
        authorities = {f"{host}:{self.server.server_port}" for host in ("127.0.0.1", "localhost", "[::1]")}
        hosts = self.headers.get_all("Host", [])
        origins = self.headers.get_all("Origin", [])
        if (len(hosts) != 1 or hosts[0] not in authorities or len(origins) > 1
                or (origins and origins[0] not in {f"http://{host}" for host in authorities})
                or any(value.strip().lower() == "cross-site" for value in self.headers.get_all("Sec-Fetch-Site", []))):
            self.close_connection = True
            self.send_body(403, {"error": "仅允许本机工作台请求"})
            return False
        if os.environ.get('ROCO_RELEASE') == '1' and urlparse(self.path).path.startswith(('/api/rules/', '/api/research/', '/native-data/')):
            self.close_connection = True
            self.send_body(404, {'error': '发布版本不提供开发调试接口'})
            return False
        return True

    def relay_query(self):
        query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        if os.environ.get("ROCO_RELEASE") == "1" and ("relay" in query or "reset" in query):
            raise ValueError("发布版本不允许覆盖中继连接")
        base = (query.get("relay") or [""])[0] or "http://127.0.0.1:8765"
        parsed = urlparse(base)
        if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                or parsed.port is None or not 0 < parsed.port <= 65535):
            raise ValueError("中继必须是带端口的本机 HTTP 地址")
        return base.rstrip("/"), query

    def send_body(self, code, body, content_type="application/json; charset=utf-8", cache_control="no-store"):
        if code == 200:
            body = release_public_body(urlparse(self.path).path, body)
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, target, root):
        """Serve one file only when it really sits inside the allowed root."""
        if _RELEASE_IDENTITY and Path(root).resolve() == TP_ROOT.resolve():
            if Path(target).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.ico', '.woff', '.woff2'}:
                return False  # Pinned implementation evidence is not a browser asset.
        try:
            resolved = Path(target).resolve()
            root = Path(root).resolve()
        except OSError:
            return False
        if resolved != root and root not in resolved.parents:
            return False
        if not resolved.is_file():
            return False
        self.send_body(200, resolved.read_bytes(),
                       STATIC_TYPES.get(resolved.suffix.lower(), "application/octet-stream"),
                       "public, max-age=3600" if resolved.suffix.lower() in (".png", ".webp", ".svg", ".jpg", ".ico") else "no-store")
        return True

    def static_target(self, path):
        """Map the carried-over HUD asset URLs onto the copied local files."""
        table = (
            ("/tp/", TP_ROOT, ""),
            ("/assets/roco/", WEB_ASSETS, ""),
            ("/roco-pet-avatars-id/", WEB_ASSETS / "pet-avatars", ""),
            ("/roco-skill-icons/", WEB_ASSETS / "skill-icons", ""),
            ("/roco-type-icons/", WEB_ASSETS / "type-icons", ""),
        )
        for prefix, root, _ in table:
            if path.startswith(prefix):
                name = unquote(path[len(prefix):])
                target = root / name
                if root == WEB_ASSETS / "skill-icons" and not target.is_file():
                    # Catalog skill ids are mapped to the game's icon resource ids.
                    alias = skill_icon_alias(Path(name).stem)
                    if alias:
                        target = root / alias
                if not target.is_file() and prefix != "/tp/":
                    # 我们自己的副本没有的图标，回退到第三方 wwwroot 的同名目录（只读）。
                    folder = prefix.strip("/").rstrip("/")
                    fallback = TP_ROOT / folder / name
                    if fallback.is_file():
                        return fallback, TP_ROOT
                return target, root
        native = {
            "/native-data/roco_buff_calc_map.json": EXTERNAL_DATA / "roco_buff_calc_map.json",
            "/native-data/authority/buff.json": EXTERNAL_DATA / "buff.json",
        }
        if path in native:
            return native[path], EXTERNAL_DATA
        return None

    def do_GET(self):
        if not self.local_request_allowed():
            return
        path = urlparse(self.path).path
        static = self.static_target(path)
        if static is not None:
            if not self.send_static(*static):
                self.send_body(404, {"error": "没有这个资源"})
            return
        pages = {"/": "lab.html", "/lab": "lab.html", "/dex": "lab.html",
                 "/battle": "battle_workspace.html", "/hud": "hud.html",
                 "/hud-duel": "hud_duel.html"}
        scripts = {"/battle.js": "battle.js", "/simulation.js": "simulation.js",
                   "/simulation.css": "simulation.css", "/battle_mechanics.js": "battle_mechanics.js",
                   "/weather_view.js": "weather_view.js", "/hud_bridge.js": "hud_bridge.js",
                   "/live_view.js": "live_view.js"}
        if path in pages or path in scripts:
            try:
                filename = pages.get(path) or scripts[path]
                content_type = "text/javascript; charset=utf-8" if filename.endswith(".js") else "text/css; charset=utf-8" if filename.endswith(".css") else "text/html; charset=utf-8"
                self.send_body(200, (ROOT / "web" / filename).read_bytes(), content_type)
            except OSError:
                self.send_body(503, {"error": "工作台页面尚未就绪"})
        elif path == "/hud-pro":
            # 第三方原版 HUD 页面（vendor 只读，不改其文件）。它自己每 50ms 从
            # localStorage 读 roco.battleHud.*，所以这里只把我们的 hud_bridge.js
            # 注进去，由它负责把 /api/hud/snapshot 转写成对方期望的 key。
            # ?split=1 换成「左我方 / 右敌方」两栏（原版是上下两行）。
            try:
                html = (TP_ROOT / "battle-hud-full.html").read_text(encoding="utf-8")
                query = parse_qs(urlparse(self.path).query)
                if query.get("split"):
                    html = html.replace("</head>", SPLIT_CSS + "</head>", 1)
                tag = '<script src="/hud_bridge.js"></script>'
                if "</body>" in html:
                    html = html.replace("</body>", tag + "\n</body>", 1)
                else:
                    html += tag
                self.send_body(200, html.encode("utf-8"), "text/html; charset=utf-8")
            except OSError:
                self.send_body(503, {"error": "第三方 HUD 页面不可用（vendor 目录缺失）"})
        elif path == "/api/pvp/rules":
            from lab.pvp_rules import load_pvp_rules
            self.send_body(200, load_pvp_rules())
        elif path == "/api/status":
            self.send_body(200, status())
        elif path == "/api/hud/snapshot":
            with HUD_LOCK:
                at = HUD_SNAPSHOT["at"]
                payload = HUD_SNAPSHOT["payload"]
            from lab.live_battle import shared_feed
            state = shared_feed().state()
            body = {"at": at, "age_seconds": (time.time() - at) if at else None,
                    "state": {k:state[k] for k in ("relay_ok", "capture", "key_missing", "hint", "last_error", "events_seen", "replay_archive") if k in state}}
            try:
                after = float((parse_qs(urlparse(self.path).query).get("after") or ["nan"])[0])
            except ValueError:
                after = float("nan")
            if at and after == at:
                body["unchanged"] = True
            else:
                body["payload"] = payload
            self.send_body(200, body)
        elif path == "/api/hud/revision":
            # 常驻悬浮窗靠这个自己重载：前端文件一改（或后端重启），revision 就变。
            # 只读文件元数据，不读内容，成本可以忽略。
            page = ROOT / "web" / "hud_duel.html"
            try:
                stat = page.stat()
                revision = f"{int(stat.st_mtime)}-{stat.st_size}"
            except OSError:
                revision = ""
            self.send_body(200, {"revision": revision, "page": "hud_duel.html"})
        elif path == "/api/advice":
            self.send_body(200, policy_advice())
        elif path == "/api/rules/coverage":
            try:
                self.send_body(200, rules_coverage())
            except (OSError, ValueError, KeyError) as exc:
                self.send_body(503, {"error": "规则资料不可用", "detail": str(exc)})
        elif path == "/api/action-mechanics":
            try:
                from lab.action_mechanics import build_action_mechanics
                catalog, _, _ = load_catalog()
                self.send_body(200, build_action_mechanics(catalog))
            except (OSError, ValueError, KeyError) as exc:
                self.send_body(503, {"error": "技能变化资料暂不可用", "detail": str(exc)})
        elif path == "/api/buff/moves":
            try:
                from lab.buff_preview import buff_summary
                self.send_body(200, buff_summary())
            except (OSError, ValueError, KeyError) as exc:
                self.send_body(503, {"error": "状态换算表不可用", "detail": str(exc)})
        elif path == "/api/usage/pets":
            try:
                from lab.usage_prior import UsageTable
                query = parse_qs(urlparse(self.path).query)
                text = (query.get("q") or [""])[0]
                limit = int((query.get("limit") or ["40"])[0])
                table = UsageTable()
                self.send_body(200, {"provenance": table.provenance(),
                                     "pets": table.find(text, max(1, min(limit, 200)))})
            except (OSError, ValueError, KeyError) as exc:
                self.send_body(503, {"error": "天梯使用率快照不可用", "detail": str(exc)})
        elif path == "/api/usage/pet":
            try:
                from lab.usage_prior import UsageTable
                query = parse_qs(urlparse(self.path).query)
                raw_id = (query.get("id") or [""])[0]
                form = (query.get("form") or [""])[0] or None
                catalog, _, _ = load_catalog()
                table = UsageTable()
                self.send_body(200, table.build(int(raw_id), form, catalog))
            except (OSError, ValueError, KeyError) as exc:
                self.send_body(400, {"error": "无法给出该精灵的天梯配置", "detail": str(exc)})
        elif path == "/api/usage/team":
            try:
                from lab.usage_prior import UsageError, UsageTable
                query = parse_qs(urlparse(self.path).query)
                raw = (query.get("ids") or [""])[0]
                ids = [int(x) for x in raw.replace(" ", "").split(",") if x]
                if not ids:
                    raise UsageError("ids 不能为空")
                catalog, _, _ = load_catalog()
                table = UsageTable()
                builds, errors = [], []
                for base_id in ids:
                    try:
                        builds.append(table.build(base_id, None, catalog))
                    except UsageError as exc:
                        errors.append({"base_id": base_id, "error": str(exc)})
                self.send_body(200, {"provenance": table.provenance(), "builds": builds, "errors": errors})
            except (OSError, ValueError, KeyError) as exc:
                self.send_body(400, {"error": "无法生成天梯参考阵容", "detail": str(exc)})
        elif path == "/api/live/status":
            try:
                from lab.live_bridge import shared
                base, query = self.relay_query()
                self.send_body(200, shared(base).state())
            except ValueError as exc:
                self.send_body(400, {"error": str(exc)})
            except OSError as exc:
                self.send_body(503, {"error": "抓包中继状态不可读", "detail": str(exc)})
        elif path == "/api/live/battle":
            # 抓包解出来的对局快照（rkpp → live_battle.BattleTracker）。
            try:
                from lab.live_battle import shared_feed
                feed = shared_feed()
                body = {"state": feed.state()}
                if (parse_qs(urlparse(self.path).query).get("state") or [""])[0] != "1":
                    body["snapshot"] = feed.snapshot()
                self.send_body(200, body)
            except (OSError, ValueError, KeyError) as exc:
                self.send_body(503, {"error": "对局解码不可用", "detail": str(exc)})
        elif path == "/api/live/events":
            try:
                from lab.live_bridge import shared
                base, query = self.relay_query()
                limit = int((query.get("limit") or ["200"])[0])
                bridge = shared(base)
                if (query.get("reset") or ["0"])[0] == "1":
                    bridge = type(bridge)(bridge.base)
                    from lab import live_bridge as module
                    module._SHARED = bridge
                self.send_body(200, bridge.poll(max(1, min(limit, 500))))
            except ValueError as exc:
                self.send_body(400, {"error": str(exc)})
            except OSError as exc:
                self.send_body(503, {"error": "抓包事件不可读", "detail": str(exc)})
        elif path == "/api/forms/skill-pool":
            try:
                query = parse_qs(urlparse(self.path).query)
                form_id = int((query.get("form_id") or [""])[0])
                catalog, _, _ = load_catalog()
                self.send_body(200, form_skill_pool(catalog, form_id))
            except (ValueError, KeyError) as exc:
                self.send_body(400, {"error": str(exc)})
            except OSError:
                self.send_body(503, {"error": "技能图鉴暂不可读"})
        elif path == "/api/catalog":
            try:
                catalog, _, _ = load_catalog()
                self.send_body(200, public_catalog(catalog))
            except (OSError, ValueError, KeyError) as exc:
                self.send_body(503, {"error": "图鉴尚未就绪", "detail": str(exc)})
        else:
            self.send_body(404, {"error": "没有这个页面"})

    def do_POST(self):
        if not self.local_request_allowed():
            return
        path = urlparse(self.path).path
        if path not in ("/api/hud/world-stars", "/api/hud/preview-target", "/api/hud/publish", "/api/weather/replay", "/api/inference/damage", "/api/preview/damage", "/api/belief", "/api/team-code/parse", "/api/team-codes/parse", "/api/opponent/recognize", "/api/opponent/search", "/api/rules/skill", "/api/rules/turn-plan", "/api/rules/execute-actions", "/api/rules/execute-statuses", "/api/rules/execute-action-status-sequence", "/api/rules/execute-switch", "/api/research/turn", "/api/research/replace", "/api/research/game-skill", "/api/simulation/prepare", "/api/simulation/demo", "/api/simulation/start", "/api/simulation/act", "/api/simulation/replace", "/api/simulation/magic"):
            self.send_body(404, {"error": "没有这个接口"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2_000_000:
                raise ValueError("请求体大小不符合要求")
            payload = json.loads(self.rfile.read(length))
            if path == '/api/hud/world-stars':
                from lab.live_battle import shared_feed
                self.send_body(200, shared_feed().set_world_stars(payload))
                return
            if path == '/api/hud/preview-target':
                from lab.live_battle import shared_feed
                from lab.live_damage import preview_target
                from lab.trait_runtime import query_scope
                if not isinstance(payload, dict):
                    raise ValueError('请求应为对象')
                with query_scope():
                    result = preview_target(shared_feed().snapshot(), payload)
                self.send_body(200, result)
                return
            if path == "/api/hud/publish":
                # 悬浮 HUD 的唯一数据入口：写入内存快照，不落盘。
                if not isinstance(payload, dict):
                    raise ValueError("快照应为对象")
                encoded = json.dumps(payload, ensure_ascii=False)
                if len(encoded.encode("utf-8")) > HUD_SNAPSHOT_LIMIT:
                    raise ValueError("快照过大")
                with HUD_LOCK:
                    HUD_SNAPSHOT["at"] = time.time()
                    HUD_SNAPSHOT["payload"] = payload
                self.send_body(200, {"ok": True, "at": HUD_SNAPSHOT["at"]})
                return
            self.send_body(200, update_belief(payload) if path == "/api/belief" else import_request(path, payload))
        except OSError as exc:
            self.send_body(503, {"error": "资料快照不可用", "detail": str(exc)})
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            self.send_body(400, {"error": str(exc)})


def _start_live_battle_feed(relay: str = "") -> None:
    """起后台订阅线程：rkpp 中继 → 战斗解码 → 直接写成 HUD 快照。

    中继没起也不影响工作台，线程只会把 ``relay_ok`` 报成 False。
    """
    try:
        from lab.live_battle import shared_feed
    except ImportError:
        return

    def publish(payload, meta) -> None:
        with HUD_LOCK:
            HUD_SNAPSHOT["at"] = time.time()
            HUD_SNAPSHOT["payload"] = hud_payload(payload)
            HUD_SNAPSHOT["source"] = "rkpp-live"
            HUD_SNAPSHOT["battle"] = {
                "battle_id": meta.get("battle_id"), "round": meta.get("round"),
                "finished": meta.get("finished"),
            }

    shared_feed(on_snapshot=publish, base=relay).start()


def main():
    parser = argparse.ArgumentParser(description="洛克 PVP 本地研究工作台")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--relay", default="", help="抓包中继地址，默认 http://127.0.0.1:8765")
    parser.add_argument("--no-live", action="store_true", help="不订阅抓包中继")
    args = parser.parse_args()
    if not args.no_live:
        _start_live_battle_feed(args.relay)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"工作台：http://127.0.0.1:{args.port}，模式：研究；正式训练未开放。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
