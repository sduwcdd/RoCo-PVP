import copy
import unittest

from lab.bwiki import WikiDataError, parse_lua_data
from lab.bwiki_seasons import decode_shard, merge_seasons, validate_manifest


def packed(value):
    fields = []

    def encode(node):
        if isinstance(node, dict):
            entries = []
            for key, child in node.items():
                if key not in fields:
                    fields.append(key)
                index = fields.index(key) + 1
                entries.append([index, encode(child)])
            return [1, entries]
        if isinstance(node, list):
            return [2, [encode(child) for child in node]]
        return node

    root = encode(value)
    return ["dragon-tuples-1", fields, root]


class TestSeasonData(unittest.TestCase):
    def setUp(self):
        self.season = {"namespace": "精灵图鉴/S5/数据", "codec": "dragon-tuples-1"}

    def test_decodes_literal_fields_and_preserves_array_order(self):
        source = 'return {"dragon-tuples-1", {"row", "moves", 496}, {1, {{1, {1, {{2, {2, {"second", "first", false}}}}}}, {3, {1, {}}}}}}'
        self.assertEqual(decode_shard(parse_lua_data(source), self.season), {
            "row": {"moves": ["second", "first", False]}, 496: {}})
        self.assertEqual(decode_shard(["dragon-tuples-1", {}, [2, {}]], self.season), [])

    def test_invalid_codec_tags_indices_and_duplicate_keys_fail(self):
        cases = [
            ["unknown", ["a"], [1, []]],
            ["dragon-tuples-1", ["a"], [3, []]],
            ["dragon-tuples-1", ["a"], [True, []]],
            ["dragon-tuples-1", ["a"], [1, [[True, 1]]]],
            ["dragon-tuples-1", ["a"], [1, [[0, 1]]]],
            ["dragon-tuples-1", ["a"], [1, [[2, 1]]]],
            ["dragon-tuples-1", ["a"], [1, [[1, 1], [1, 2]]]],
            ["dragon-tuples-1", ["a", "a"], [1, [[1, 1], [2, 2]]]],
            ["dragon-tuples-1", [False], [1, [[1, 1]]]],
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(WikiDataError):
                decode_shard(value, self.season)

    def test_rejects_unsafe_manifest_module_names(self):
        for path in ("../private", "valid//bad", "a|Module:bad", "a\\bad", "a\nbad"):
            with self.subTest(path=path), self.assertRaises(WikiDataError):
                validate_manifest({"seasons": [{**self.season, "modules": {"Roster": path}}]})
        for change in ({"object_tag": True}, {"array_tag": 1}):
            with self.subTest(change=change), self.assertRaises(WikiDataError):
                decode_shard(packed({}), {**self.season, **change})

    def shards(self, season, code="S5", route="正式技能页"):
        rows = {
            "Roster": {"pet": {"name": "new"}},
            "Arts": {"move": {"name": "art"}},
            "Gifts": {"move": {"name": "gift"}},
            "Aux": {"CatalogSeasons": {code: ["pet"]}, "Learnsets": {"pet": ["move"]},
                    "History": {"pet": {"new": 2}}, "Config": {"versions": ["new"]}},
            "Links": {"Targets": {"skill": {"move": route}}, "Links": {"skill": {"move": route}}},
        }
        return {(season["namespace"], name): packed(value) for name, value in rows.items()}

    def test_merge_order_nested_tables_routes_and_input_immutability(self):
        base = {"Catalog": {"pet": {"old": True}}, "Skills": {},
                "History": {"pet": {"old": 1}}, "Config": {"versions": ["old", "keep"]}}
        before = copy.deepcopy(base)
        result = merge_seasons(base, {"seasons": [self.season]}, self.shards(self.season))
        self.assertEqual(result["Catalog"]["pet"], {"name": "new"})
        self.assertEqual(result["Skills"]["move"], {"name": "gift"})
        self.assertEqual(result["History"]["pet"], {"old": 1, "new": 2})
        self.assertEqual(result["Config"]["versions"], ["new", "keep"])
        self.assertEqual(result["Learnsets"], {"pet": ["move"]})
        self.assertEqual(result["SkillSeasons"], {"move": "S5"})
        self.assertEqual(result["Targets"]["skill"], {"move": "正式技能页"})
        self.assertEqual(base, before)

    def test_cross_season_route_conflicts_and_missing_shards_fail(self):
        later = {**self.season, "namespace": "精灵图鉴/S6/数据"}
        manifest = {"seasons": [self.season, later]}
        shards = {**self.shards(self.season), **self.shards(later, "S6")}
        self.assertEqual(merge_seasons({}, manifest, shards)["SkillSeasons"], {"move": "S6"})
        shards.update(self.shards(later, "S6", "冲突页"))
        with self.assertRaisesRegex(WikiDataError, "Conflicting"):
            merge_seasons({}, manifest, shards)
        with self.assertRaisesRegex(WikiDataError, "Missing season shard"):
            merge_seasons({}, {"seasons": [self.season]}, {})


if __name__ == "__main__":
    unittest.main()
