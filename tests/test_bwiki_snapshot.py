import unittest
from lab.bwiki import WikiDataError, parse_lua_data


class TestLuaData(unittest.TestCase):
    def test_literals(self):
        value = parse_lua_data('return {name="迪莫", stats={hp=120}, enabled=true, xs={1,2,3}, [1001]="a\\n\\065", empty={}}')
        self.assertEqual(value["stats"], {"hp": 120})
        self.assertEqual(value["xs"], [1, 2, 3])
        self.assertEqual(value[1001], "a\nA")
        self.assertTrue(value["enabled"])

    def test_rejects_execution(self):
        for source in ['return os.execute("bad")', 'return {}; print(1)', 'return {a=function() end}', 'return {a=1,a=2}', 'return {a=1,2}', 'return {1+2}']:
            with self.subTest(source=source), self.assertRaises(WikiDataError):
                parse_lua_data(source)

    def test_comments_and_trailing_separator(self):
        self.assertEqual(parse_lua_data('-- generated\nreturn {a=1,}'), {"a": 1})


if __name__ == "__main__":
    unittest.main()
