"""离线回放真实抓包消息，验证 BattleTracker 的字段映射。

用法：python scripts/replay_battle_track.py
读取 artifacts/_battle_*.json（由 scripts/dump_opcode_rows.py 从真实 CSV 里导出），
按 enter → round_start → cmd_sync → perform_start → finish 顺序喂给 tracker，
打印断言结果并写出 artifacts/_battle_snapshot.json。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lab.live_battle import BattleTracker  # noqa: E402

ART = ROOT / "artifacts"
ORDER = (
    "_battle_enter.json",
    "_battle_round_start.json",
    "_battle_cmd_sync.json",
    "_battle_perform_start.json",
    "_battle_finish.json",
)


def load_events() -> list[dict]:
    events: list[dict] = []
    for name in ORDER:
        path = ART / name
        if not path.exists():
            print(f"skip (missing) {name}")
            continue
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("content") is not None:
                events.append(item)
    return events


def main() -> int:
    events = load_events()
    if not events:
        print("no events to replay")
        return 1
    tracker = BattleTracker()
    for event in events:
        changed = tracker.handle_event(event.get("opencode"), event.get("content") or {})
        print(f"  {event.get('opencode')} {event.get('meaning')} changed={changed}")
    snapshot = tracker.snapshot()
    if snapshot is None:
        print("FAIL snapshot is None")
        return 1
    with open(ART / "_battle_snapshot.json", "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2)

    rt = snapshot["runtime"]
    my_team = rt["myTeam"]
    enemy_team = rt["enemyTeam"]
    checks: list[tuple[str, bool, str]] = []

    checks.append(("我方 6 只", len(my_team) == 6, f"len={len(my_team)}"))
    checks.append(("敌方 1 只", len(enemy_team) == 1, f"len={len(enemy_team)}"))

    first = my_team[0] if my_team else {}
    # 形态名优先：base_conf_id=5028 在 petbase 里叫「水灵」，报文里的 conf_name
    # 只是基础名「水蓝蓝」。两者都算对，但不能是空的。
    checks.append(("首发显示名称（形态名优先）",
                   first.get("petName") in ("水灵", "水蓝蓝"), str(first.get("petName"))))
    checks.append(("最大生命 335", first.get("maxHp") == 335, str(first.get("maxHp"))))
    checks.append(("四个技能槽", len(first.get("moves") or []) == 4,
                   str([m.get("skillName") for m in first.get("moves") or []])))
    slot_names = [m.get("skillName") for m in first.get("moves") or []]
    checks.append(("槽位按 pos 排序", slot_names[:1] == ["气泡"], str(slot_names)))
    checks.append(("六维非空", bool(first.get("stats")), str(first.get("stats"))))

    # perform 里 401（敌方石肤蜥）受到 26 点伤害，剩余 134
    foe = enemy_team[0] if enemy_team else {}
    checks.append(("敌方血量结算 134", foe.get("currentHp") == 134, str(foe.get("currentHp"))))
    # 敌方只暴露「已经打出来过」的招式，没打过的技能一个都不能出现。
    # dump 里敌方石肤蜥打过「应对！硬化」，所以允许 1 条观测行，但不能是 4 条配招。
    foe_moves = foe.get("moves") or []
    checks.append(("敌方只暴露已观测招式",
                   len(foe_moves) < 4 and all(
                       m.get("observedOnly") or m.get("observedSkillId") is not None
                       for m in foe_moves),
                   str([m.get("skillName") for m in foe_moves])))

    # 我方施法者（pet_id=6 迪莫）应该被标记为在场；能量先扣 3（→7），
    # 回合结束 type=6 再回 2（→9），最终以 sync 结算为准。
    diem = next((p for p in my_team if p.get("petName") == "迪莫"), None)
    checks.append(("迪莫在场", rt["active"]["my"]["rosterIndex"] == (diem or {}).get("rosterIndex"),
                   str(rt["active"])))
    checks.append(("迪莫能量按 sync 结算为 9", (diem or {}).get("energy") == 9,
                   str((diem or {}).get("energy"))))
    diem_hp = (diem or {}).get("currentHp")
    checks.append(("迪莫受伤 14 后剩 259", diem_hp == 259, str(diem_hp)))
    checks.append(("迪莫 buff 有名字",
                   any(b.get("name") for b in (diem or {}).get("buffs") or []),
                   str([(b.get("id"), b.get("name"), b.get("layers"))
                        for b in (diem or {}).get("buffs") or []])))

    # 存活精灵不得显示 0%
    hp_pct_ok = all((p.get("hpPercent") or 0) >= 1 for p in my_team + enemy_team
                    if (p.get("currentHp") or 0) > 0)
    checks.append(("存活精灵 hpPercent>=1", hp_pct_ok, ""))

    raw_timeline = rt.get("battleTimeline") or []
    checks.append(("timeline 有施法记录",
                   any(item.get("kind") == "skill_cast" for item in raw_timeline),
                   f"{len(raw_timeline)} items"))
    checks.append(("timeline 有伤害记录",
                   any(item.get("kind") == "damage" for item in raw_timeline), ""))

    ok = True
    for name, passed, detail in checks:
        mark = "PASS" if passed else "FAIL"
        if not passed:
            ok = False
        print(f"[{mark}] {name} {detail}")

    print(f"\nsnapshot -> {ART / '_battle_snapshot.json'}")
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
