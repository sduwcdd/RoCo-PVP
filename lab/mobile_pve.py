"""Current enemy metadata projection, without combat forecasts or stat inference."""
from __future__ import annotations

from copy import deepcopy
import threading
from types import SimpleNamespace

from . import battle_data
from .live_battle import _execution_order, _hex_name, _pos_is_field, _same_band_as_enemy, _walk_pet_infos

_EDGES = {"init_info", "enemy_team", "player_team", "pets", "base", "state_info",
          "perform_cmd", "perform_info", "sync_data", "pet_sync_info", "pet_info",
          "battle_inside_pet_info", "battle_common_pet_info", "change_pet", "battle_pet_info",
          "supply_pet", "pet_infos", "data_update", "change_model", "model_change",
          "dead_info", "settle_info"}
_VALUES = {"battle_id", "pet_id", "owner_uin", "role_uin", "is_player_enemy", "pos",
           "base_conf_id", "conf_id", "conf_name", "name", "nature", "height", "weight", "voice",
           "wear_medal_conf_id", "changed_nature_pos_attr_type", "changed_nature_neg_attr_type",
           "exec_index", "pet_pos", "battle_pet_id", "rest_pet_id", "target_id", "dead_type", "hp_result"}
_STAT_NAMES = {"hp": "生命", "patk": "物攻", "matk": "魔攻", "pdef": "物防", "mdef": "魔防", "spd": "速度"}
_OVERRIDES = {1: "hp", 2: "patk", 3: "matk", 4: "pdef", 5: "mdef", 6: "spd"}


class PveMetadata:
    def __init__(self, catalog):
        self.forms = {str(f["id"]): f for f in catalog.get("forms", [])}
        self.natures = {n["id"]: n for n in catalog.get("natures", [])}
        self.schemas = {}
        self.lock = threading.RLock()
        self.generation = 0
        self.reset()

    def reset(self, notice="等待当前敌方精灵"):
        with self.lock:
            self.generation += 1
            self.battle_id = None
            self.pets = {}
            self.my_ids = set()
            self.enemy_owner = None
            self.active_id = None
            self.notice = notice
            self.enemy = None

    def _schema(self, name):
        if name not in self.schemas:
            import rkpp_analysis as analysis
            full = analysis._codec_schema_for_message(analysis._ensure_loaded()[1]["messages"], name)
            self.schemas[name] = None if full is None else {"fields": [f for f in full["fields"]
                if f["name"] in (_EDGES if f["type"] == "message" else _VALUES)]}
        return self.schemas[name]

    def decode(self, record):
        import rkpp_analysis as analysis
        import rkpp_codec as codec
        from rkpp_proto_core import parse_proto_message
        info = analysis.lookup_opcode(record["opcode"])
        schema = self._schema(info.get("decode_as") or info.get("full_name") or info.get("name"))
        if schema is None:
            raise ValueError("PVE metadata message schema unavailable")

        def decode_message(current, raw, resolve, depth=0):
            root = parse_proto_message(raw, max_depth=0)
            if depth > 64 or not root["clean"] or root["consumed"] != len(raw):
                raise ValueError("PVE metadata wire is incomplete")
            if any(not 0 < f["field"] <= 0x1FFFFFFF or
                   (f["wire"] == 0 and f["value"] >= 1 << 64) for f in root["fields"]):
                raise ValueError("PVE metadata field is invalid")
            fields = {f["no"]: f for f in current["fields"]}
            for entry in root["fields"]:
                field = fields.get(entry["field"])
                if field is None:
                    continue
                expected = codec.wire_type_for(field["type"])
                if entry["wire"] != expected:
                    if not (field.get("repeated") and entry["wire"] == 2 and expected in (0, 1, 5)):
                        raise ValueError("PVE metadata field type changed")
                    codec._decode_packed_values(field, bytes.fromhex(entry["raw_hex"]))
                elif field["type"] == "string":
                    bytes.fromhex(entry["raw_hex"]).decode("utf8")
            decoded, consumed, _matched, _unknown = codec.decode_payload_once(current, raw, resolve,
                decode_message=lambda s, b, r: decode_message(s, b, r, depth + 1), preserve_unknown=False)
            if consumed != len(raw):
                raise ValueError("PVE metadata did not consume its message")
            return decoded

        return decode_message(schema, bytes.fromhex(record["payload_hex"]), self._schema)

    def _absorb(self, node):
        for inside, common in _walk_pet_infos(node):
            key = str(inside.get("pet_id"))
            if key == "None" or key in self.my_ids:
                continue
            owner = str(inside.get("owner_uin"))
            known = key in self.pets or inside.get("is_player_enemy") is True
            known = known or (self.enemy_owner not in (None, "0") and owner == self.enemy_owner)
            if not known:
                band = [SimpleNamespace(pet_id=int(p)) for p in self.pets if p.isdigit()]
                known = _same_band_as_enemy(inside.get("pet_id"), band)
            if known:
                pet = self.pets.setdefault(key, {"inside": {}, "common": {}})
                pet["inside"].update(inside)
                pet["common"].update(common)

    def _position(self, node):
        active = {str(i.get("pet_id")) for i, _ in _walk_pet_infos(node)
                  if str(i.get("pet_id")) in self.pets and _pos_is_field(i.get("pos"))}
        if len(active) == 1:
            self.active_id = active.pop()
        elif len(active) > 1:
            self.active_id = None

    def handle(self, opcode, content):
        with self.lock:
            if opcode == 0x1316:
                self.reset("正在识别当前精灵")
                init = content.get("init_info") or {}
                self.battle_id = init.get("battle_id")
                for member in init.get("player_team") or []:
                    self.my_ids.update(str(i.get("pet_id")) for i, _ in _walk_pet_infos(member))
                for member in init.get("enemy_team") or []:
                    self.enemy_owner = str((member.get("base") or {}).get("role_uin") or "0")
                    for inside, common in _walk_pet_infos(member):
                        key = str(inside.get("pet_id"))
                        if key != "None":
                            self.pets[key] = {"inside": dict(inside), "common": dict(common)}
                self._position(init.get("enemy_team"))
            else:
                if self.battle_id is None:
                    return
                identity = (content.get("battle_id") or (content.get("state_info") or {}).get("battle_id")
                            or (content.get("settle_info") or {}).get("battle_id"))
                if identity is not None and str(identity) != str(self.battle_id):
                    return
                if opcode == 0x132C:
                    self.reset("对局已结束")
                    return
                self._absorb(content)
                state = content.get("state_info") or {}
                for key, node in content.items():
                    if key != "perform_cmd":
                        self._position(node)
                for command in (content.get("perform_cmd"), state.get("perform_cmd"), content.get("perform_info")):
                    if not isinstance(command, dict):
                        continue
                    for item in _execution_order(command.get("perform_info")):
                        self._position(item.get("data_update"))
                        self._position((item.get("sync_data") or {}).get("pet_info"))
                        for entry in (item.get("sync_data") or {}).get("pet_sync_info") or []:
                            key = str(entry.get("pet_id"))
                            if key not in self.my_ids and _pos_is_field(entry.get("pos")):
                                self.active_id = key if key in self.pets else None
                            if key == self.active_id and entry.get("hp_result") == 0:
                                self.active_id = None
                        change = item.get("change_pet") or {}
                        incoming = str(change.get("battle_pet_id"))
                        if change and incoming not in self.my_ids:
                            matching = [str(i.get("pet_id")) for i, _ in _walk_pet_infos(change.get("battle_pet_info"))]
                            self.active_id = incoming if incoming in self.pets and (not matching or matching == [incoming]) else None
                        for supplied in (item.get("supply_pet") or {}).get("pet_infos") or []:
                            key = str(supplied.get("pet_id"))
                            if key not in self.my_ids and _pos_is_field(supplied.get("pet_pos")):
                                self.active_id = key if key in self.pets else None
                        dead = item.get("dead_info") or {}
                        if str(dead.get("target_id")) == self.active_id and dead.get("dead_type") == 0:
                            self.active_id = None
            self._update_view()

    def _update_view(self):
        pet = self.pets.get(self.active_id)
        self.enemy = None
        if pet is None:
            self.notice = "等待确认当前敌方精灵"
            return
        inside, common = pet["inside"], pet["common"]
        base = inside.get("base_conf_id") or common.get("base_conf_id")
        form = self.forms.get(str(base), {})
        native_form = battle_data.pet_form(base) if not form else {}
        name = ((form.get("name") or {}).get("zh") or native_form.get("name")
                or inside.get("conf_name") or common.get("conf_name")
                or _hex_name(inside.get("name")) or _hex_name(common.get("name")))
        nature = self.natures.get(common.get("nature"), {})
        up = _OVERRIDES.get(common.get("changed_nature_pos_attr_type")) or nature.get("up")
        down = _OVERRIDES.get(common.get("changed_nature_neg_attr_type")) or nature.get("down")
        if (up, down) != (nature.get("up"), nature.get("down")):
            nature = next((n for n in self.natures.values() if (n.get("up"), n.get("down")) == (up, down)), nature)
        physical = battle_data.physical_info(base, **{f: common.get(f) for f in ("height", "weight", "voice")},
                                             worn_medal_id=common.get("wear_medal_conf_id"))
        medals = [m["name"] + ({"predicted": "（范围提示）", "boundary": "（边界待确认）"}.get(m["status"], ""))
                  for m in physical["medals"]]
        self.enemy = {"name": name or (f"未收录精灵（ID {base}）" if base else "精灵身份未下发"),
                      "formId": base,
                      "identitySource": "BWIKI" if form else native_form.get("data_source") or ("reported_name" if name else "unresolved"),
                      "icon": f"/roco-pet-avatars-id/{base}.png" if base else "",
                      "natureName": (nature.get("name") or {}).get("zh") or "性格未下发",
                      "natureUp": _STAT_NAMES.get(up, ""), "natureDown": _STAT_NAMES.get(down, ""),
                      "weightText": physical.get("weight", {}).get("text", "未下发"),
                      "voiceText": physical.get("voice", {}).get("text", "未下发"), "medals": medals}
        self.notice = ""

    def snapshot(self, ready=True):
        with self.lock:
            return {"generation": self.generation, "ready": bool(ready and self.enemy),
                    "enemy": deepcopy(self.enemy) if ready else None,
                    "notice": self.notice if ready else "正在同步当前精灵"}
