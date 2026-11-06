import json
import unittest

from lab.dex import SnapshotError, decode_router_html


def html(nodes):
    return '<script>window.__reactRouterContext.streamController.enqueue(' + json.dumps(json.dumps(nodes)) + ');</script>'


class TestRouterDecoder(unittest.TestCase):
    def test_nested_and_null(self):
        nodes = [{"_1": 2}, "loaderData", {"_3": 4}, "route", {"_5": 6, "_7": -5}, "items", [8, 9], "missing", 123, "中文"]
        self.assertEqual(decode_router_html(html(nodes)), {"route": {"items": [123, "中文"], "missing": None}})

    def test_rejects_undefined_hole_and_invalid_reference(self):
        for ref in [-7, -1, -2, 99, True]:
            with self.subTest(ref=ref), self.assertRaises(SnapshotError):
                decode_router_html(html([{"_1": ref}, "loaderData"]))

    def test_rejects_cycles_and_tagged_arrays(self):
        for nodes in [[{"_1": 0}, "loaderData"], [{"_1": 2}, "loaderData", ["Date", 3], "2026-10-25"]]:
            with self.assertRaises(SnapshotError):
                decode_router_html(html(nodes))

    def test_rejects_multiple_chunks(self):
        with self.assertRaises(SnapshotError):
            decode_router_html(html([{}]) + html([{}]))

    def test_rejects_server_error(self):
        with self.assertRaises(SnapshotError):
            decode_router_html(html([{"_1": 2, "_3": 4}, "loaderData", {}, "errors", "Oops"]))


if __name__ == "__main__":
    unittest.main()
