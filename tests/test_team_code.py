"""Protocol regressions plus the user's preserved real-code corpus."""
import copy
import json
import unittest
from pathlib import Path

from lab.team_code import ALPHABET, ATTRIBUTES, decode_number, parse_team_code


def encoded(value, width):
    out = "A" if value == 0 else ""
    while value:
        value, rem = divmod(value, 64)
        out = ALPHABET[rem] + out
    if len(out) > width:
        raise ValueError("Fixture field exceeds width")
    return out.ljust(width, "~")


def member(fid=3080, bloodline=5, nature=2, markers=(80, 80, 80), moves=(11, 0, 7060200, 12)):
    return (encoded(fid, 5) + encoded(bloodline, 2) + encoded(nature, 2)
            + "".join(encoded(x, 2) for x in markers)
            + "".join(encoded(x, 5) for x in moves))


def team(records=None, modifiers=None, core=104002, team_type=1):
    records = records or [member()]
    modifiers = modifiers or [(0, 0)] * len(records)
    return ("B~" + encoded(len(records), 1) + "".join(records)
            + encoded(core, 4) + encoded(team_type, 1)
            + "".join(encoded(up, 2)+encoded(down, 2) for up, down in modifiers))


def catalog():
    return {"snapshot_id": "synthetic-test-snapshot", "source_version": "synthetic",
            "forms": [{"id": 3080, "number": "999", "title": "火羽", "stage": 3},
                      {"id": 93080, "title": "火羽（首领）", "stage": 3}],
            "moves": {str(i): {"id": i, "name": {"zh": n}} for i, n in [(11,"甲"),(12,"乙"),(7060200,"虹光冲击"),(15,"传说")]},
            "natures": [{"id": 2, "name": {"zh": "固执"}, "up": "patk", "down": "matk"}],
            "details": {"3080": {"learnset": {"pool": [11],
                "native": [{"move":11,"stage":1,"level":20}], "stones":[12],
                "legacy":[{"move":7060200,"bloodline":"光","level":15}],
                "legendary":[{"move":15,"requires":"龙息帕尔"}]}}}}


class IntegerDecoderTests(unittest.TestCase):
    def test_integer_not_base64_bytes(self):
        self.assertEqual(decode_number("BQ"), 80)
        self.assertEqual(decode_number("G"), 6)
        self.assertEqual(decode_number("+_~"), 62*64+63)
        self.assertEqual(decode_number("/_~"), 63*64+63)

    def test_noncanonical_or_invalid_fields_rejected(self):
        for value in ("", "~~", "A~B", "AB", "AA", "B!", " B", "B\n"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_number(value)

    def test_zero_compatibility_opt_in_and_raw_field_only(self):
        self.assertEqual(decode_number("00000", zero_compat=True), 0)
        self.assertEqual(decode_number("00"), 52*64+52)
        self.assertEqual(decode_number("0~", zero_compat=True), 52)


class TeamCodeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog()

    def parse(self, code=None):
        return parse_team_code(code or team(), self.catalog)

    def codes(self, parsed):
        return {x["code"] for x in parsed["issues"]}

    def test_six_members_are_242_and_order_and_empty_slots_retained(self):
        code = team([member()] * 6)
        self.assertEqual(len(code), 242)
        r = self.parse(code)
        self.assertTrue(r["format_valid"])
        self.assertEqual(r["members"][0]["move_ids"], [11,0,7060200,12])
        self.assertTrue(r["members"][0]["moves"][1]["empty"])
        self.assertEqual([m["slot"] for m in r["members"]], list(range(1,7)))

    def test_length_version_count_team_type_and_ranges(self):
        for code in (team()+"A", team()[:-1], "C~"+team()[2:], "B~A"+team()[3:],
                     team(team_type=0), team(team_type=12), team([member(bloodline=20)]),
                     team([member(nature=31)]), team(modifiers=[(7,0)]), team([member(markers=(78,0,0))])):
            with self.subTest(code=code):
                r = self.parse(code)
                self.assertFalse(r["format_valid"])
                self.assertFalse(r["importable"])
                self.assertTrue(any(x["category"] == "format_error" for x in r["issues"]))

    def test_special_zeros_never_apply_to_bloodline(self):
        raw = member()
        code = team([raw[:5]+"00"+raw[7:]])
        self.assertIn("field_out_of_range", self.codes(self.parse(code)))
        raw = raw[:9]+"000000"+"00000"*4
        r = self.parse(team([raw], core=0))
        self.assertTrue(r["format_valid"])
        self.assertEqual(r["members"][0]["raw_talent_markers"], [0,0,0])
        self.assertEqual(r["members"][0]["move_ids"], [0,0,0,0])

    def test_raw_repeated_markers_and_unknown_full_iv(self):
        r = self.parse()
        m = r["members"][0]
        self.assertEqual(m["raw_fields"]["talent_markers"], ["BQ"]*3)
        self.assertEqual(m["raw_talent_markers"], [80]*3)
        self.assertEqual(m["talents"], dict.fromkeys(ATTRIBUTES))
        self.assertIn("duplicate_talent_markers", self.codes(r))
        self.assertFalse(r["training_eligible"])
        self.assertTrue(r["importable"])

    def test_user_confirmed_error_not_fixed_or_importable(self):
        r = self.parse(team([member(bloodline=4)]))
        m = r["members"][0]
        self.assertEqual((m["form_id"],m["bloodline_id"],m["move_ids"][2]), (3080,4,7060200))
        error = next(x for x in r["issues"] if x["category"] == "user_confirmed_error")
        self.assertEqual(error["message"], "火羽：阵容码指定水血脉，却携带当前图鉴列为光血脉来源的虹光冲击；用户已确认该阵容码有误。")
        self.assertFalse(r["importable"])

    def test_bloodline_does_not_change_form(self):
        r = self.parse(team([member(bloodline=19)]))
        self.assertEqual(r["members"][0]["form_id"], 3080)
        self.assertEqual(r["members"][0]["form_name"], "火羽")
        self.assertIn("learning_condition_conflict", self.codes(r))
        self.assertTrue(r["importable"])

    def test_game_id_not_dex_number_and_ambiguity(self):
        self.assertIn("unknown_form", self.codes(self.parse(team([member(fid=999)]))))
        self.catalog["forms"][0]["game_id"] = 3081
        self.assertIn("unknown_form", self.codes(self.parse()))
        self.catalog["forms"].append({"game_id":3081,"title":"冲突形态"})
        r=self.parse(team([member(fid=3081)]))
        self.assertIn("ambiguous_form",self.codes(r))
        self.assertFalse(r["importable"])

    def test_unknown_duplicate_and_outside_moves_never_fixed(self):
        for ids, expected in [((999,0,11,12),"unknown_move"), ((11,0,11,12),"duplicate_moves")]:
            r=self.parse(team([member(moves=ids)]))
            self.assertEqual(r["members"][0]["move_ids"],list(ids))
            self.assertIn(expected,self.codes(r))
            self.assertFalse(r["importable"])
        r=self.parse(team([member(moves=(999,0,999,12))]))
        self.assertTrue({"unknown_move","duplicate_moves"}.issubset(self.codes(r)))
        self.catalog["details"]["3080"]["learnset"]["stones"] = []
        self.assertIn("outside_learnset",self.codes(self.parse()))

    def test_nature_matches_directions_not_raw_id_name(self):
        self.catalog["natures"][0]["id"] = 200
        r=self.parse(team(modifiers=[(1,6)]))
        n=r["members"][0]["nature"]
        self.assertEqual(n["original"],{"id":2,"bwiki_id":200,"name":"固执","up":"patk","down":"matk"})
        self.assertEqual(n["modifiers"],{"up_id":1,"down_id":6})
        self.assertEqual(n["final"],{"up":"hp","down":"spd"})
        self.assertEqual(self.parse()["members"][0]["nature"]["final"],{"up":"patk","down":"matk"})

    def test_nature_conflicts_and_incomplete(self):
        self.assertIn("nature_direction_conflict", self.codes(self.parse(team(modifiers=[(3,0)]))))
        self.assertIn("nature_direction_incomplete", self.codes(self.parse(team([member(nature=0)],modifiers=[(2,0)]))))
        self.catalog["natures"][0]["down"]="pdef"
        self.assertIn("nature_mapping_conflict", self.codes(self.parse()))

    def test_native_pool_cannot_bypass_level_and_stage_conditions(self):
        r=self.parse()
        paths=r["members"][0]["moves"][0]["learning_sources"]
        self.assertEqual([p["source"] for p in paths],["native"])
        self.assertIn("阵容码不含等级",paths[0]["pending"])
        self.catalog["details"]["3080"]["learnset"]["native"][0]["stage"]=4
        self.assertIn("learning_condition_conflict",self.codes(self.parse()))

    def test_alternative_learning_route_and_legendary_condition(self):
        self.catalog["details"]["3080"]["learnset"]["stones"].append(7060200)
        r=self.parse(team([member(bloodline=3,moves=(15,0,7060200,12))]))
        self.assertNotIn("learning_condition_conflict",self.codes(r))
        path=r["members"][0]["moves"][0]["learning_sources"][0]
        self.assertEqual(path["requires"],"龙息帕尔")
        self.assertIn("传说技能解锁条件未提供",path["pending"])

    def test_generic_pool_never_bypasses_bloodline_condition(self):
        self.catalog["details"]["3080"]["learnset"]["pool"].append(7060200)
        r=self.parse(team([member(bloodline=3)]))
        self.assertIn("learning_condition_conflict",self.codes(r))
        paths=r["members"][0]["moves"][2]["learning_sources"]
        self.assertEqual([p["source"] for p in paths],["legacy"])

    def test_known_core_source_unknown_core_and_code_version(self):
        for mid,name in [(104002,"愿力强化"),(104007,"进化之力")]:
            self.assertEqual(self.parse(team(core=mid))["core_magic"],{"id":mid,"name":name,"source":"user_verified_examples"})
        r=self.parse(team(core=99))
        self.assertIn("unknown_core_magic",self.codes(r))
        self.assertIn("code_version_unknown",self.codes(r))
        self.assertFalse(r["training_eligible"])

    def test_json_safe_and_does_not_mutate_catalog(self):
        before=copy.deepcopy(self.catalog)
        json.dumps(self.parse(),ensure_ascii=False)
        self.assertEqual(self.catalog,before)

    def test_real_bwiki_huoyu_and_eight_nature_examples(self):
        from lab.server import load_catalog
        c,_,_=load_catalog()
        r=parse_team_code(team([member(bloodline=4,moves=(7020780,0,7060200,0))]),c)
        self.assertEqual(r["members"][0]["form_name"],"火羽")
        self.assertEqual(r["members"][0]["moves"][2]["name"],"虹光冲击")
        self.assertIn("user_confirmed_huoyu_bloodline",self.codes(r))
        for nid,name in [(2,"固执"),(11,"聪明"),(16,"警惕"),(21,"胆小"),(23,"开朗"),(24,"莽撞"),(26,"沉默"),(28,"平和")]:
            with self.subTest(nid=nid):
                r=parse_team_code(team([member(nature=nid,moves=(0,0,0,0))]),c)
                self.assertEqual(r["members"][0]["nature"]["original"]["name"],name)

    def test_preserved_33_real_codes_and_both_user_verified_teams(self):
        from lab.server import load_catalog
        c,_,_=load_catalog()
        path=Path(__file__).resolve().parents[1]/"data/reference/team-code-20261025/user-team-codes.txt"
        # This fixture is the unchanged user file; its blank/text lines are not codes.
        entries=[(line_no,line) for line_no,line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(),1) if line.startswith("B~")]
        self.assertEqual(len(entries),33)
        parsed={line_no:parse_team_code(code,c) for line_no,code in entries}
        self.assertEqual([line_no for line_no,r in parsed.items() if not r["format_valid"]],[22,38])
        self.assertEqual(sum(r["format_valid"] for r in parsed.values()),31)
        self.assertEqual(sum(r["member_count"]==5 for r in parsed.values()),4)
        for line_no,raw in entries:
            r=parsed[line_no]
            self.assertEqual(r["raw_code"],raw)
            self.assertFalse(r["training_eligible"])
            if line_no in (22,38):
                self.assertEqual(len(raw),241)
                self.assertIn("invalid_length",self.codes(r))
                self.assertFalse(r["importable"])
            else:
                self.assertTrue(all(len(m["move_ids"])==4 for m in r["members"]))
        self.assertEqual([m["form_name"] for m in parsed[6]["members"]], ["雪灵","幻影灵菇","斑枭","花影羚羊","夜枭","摇铃魔偶"])
        self.assertEqual(parsed[6]["core_magic"]["id"],104002)
        self.assertEqual([m["form_name"] for m in parsed[1]["members"]], ["罗隐","冰钻布鲁斯","龙鱼","火羽","魔力猫","古卷执政官"])
        self.assertEqual(parsed[1]["core_magic"]["id"],104007)
        self.assertIn("user_confirmed_huoyu_bloodline",self.codes(parsed[1]))
        self.assertFalse(parsed[1]["importable"])
        for r in (parsed[1],parsed[6]):
            self.assertTrue(all(m["raw_talent_markers"]==[80,80,80] for m in r["members"]))


if __name__ == "__main__":
    unittest.main()
