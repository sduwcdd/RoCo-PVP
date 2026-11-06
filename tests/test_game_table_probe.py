"""Read-only regressions for the preserved offline table parser, not game logic."""
import importlib.util
import json
from pathlib import Path
import struct
import unittest


ROOT = Path(__file__).resolve().parents[1] / "artifacts/unpack_probe_20261025"
SPEC = importlib.util.spec_from_file_location("preserved_roco_table_probe", ROOT / "parse_roco_tables.py")
PARSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARSER)


def bare(raw, constants=()):
    result = PARSER.Bin.__new__(PARSER.Bin)
    result.b, result.p, result.constants, result.unresolved = raw, 0, list(constants), []
    return result


class GameTableProbeTests(unittest.TestCase):
    def test_missing_numeric_field_is_distinct_from_explicit_zero(self):
        schema = {"Properties": [{"Name": "id", "Type": "EUint32"}, {"Name": "num", "Type": "EInt32"}]}
        missing = bare(b"\x80" + struct.pack("<I", 42)).parse_struct(schema, None)
        zero = bare(b"\xc0" + struct.pack("<Ii", 42, 0)).parse_struct(schema, None)
        self.assertEqual(missing, {"id": 42})
        self.assertEqual(zero, {"id": 42, "num": 0})

    def test_ordered_array_keeps_zero_and_position(self):
        schema = {"Properties": [{"Name": "params", "Type": "EInt32", "DynamicArray": True, "Size": 4}]}
        reader = bare(b"\x80" + struct.pack("<iiii", 1, 8, 0, 3), [(1, 12, 5)])
        self.assertEqual(reader.parse_struct(schema, None), {"params": [8, 0, 3]})
        self.assertEqual(reader.p, 5)

    def test_nested_absent_field_stays_absent(self):
        schema = {"Properties": [{"Name": "result", "Type": "EStruct", "Struct": {
            "Properties": [{"Name": "cast_moment", "Type": "EInt32"}]}}]}
        reader = bare(b"\x80" + struct.pack("<i", 1) + b"\x00", [(1, 1, 5)])
        self.assertEqual(reader.parse_struct(schema, None), {"result": {}})

    def test_row_length_mismatch_rejected(self):
        reader = bare(b"\x80" + struct.pack("<I", 42) + b"\x00")
        reader.count, reader.rows = 1, [(1, 6, 0)]
        with self.assertRaisesRegex(ValueError, "length mismatch"):
            reader.parse_rows({"UniqueKey": "id", "Properties": [{"Name": "id", "Type": "EUint32"}]}, None)

    def test_unknown_field_type_and_invalid_array_length_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported type"):
            bare(b"\x80").parse_struct({"Properties": [{"Name": "bad", "Type": "EUnknown"}]}, None)
        schema = {"Properties": [{"Name": "params", "Type": "EInt32", "DynamicArray": True, "Size": 4}]}
        with self.assertRaisesRegex(ValueError, "Array size mismatch"):
            bare(b"\x80" + struct.pack("<i", 1) + b"\x00" * 3, [(1, 3, 5)]).parse_struct(schema, None)

    def test_eight_saved_tables_round_trip_without_replacing_outputs(self):
        tables = ROOT / "battle_analysis/tables"
        count = 0
        for path in sorted((tables / "BinConf").glob("*.non")):
            name = path.stem
            schema = json.loads(path.read_text(encoding="utf-8"))
            reader = PARSER.Bin((tables / "BinDataCompressed" / (name + ".bytes")).read_bytes())
            locpath = tables / "BinLocalize/dev_CN" / (name + ".bytes")
            local = PARSER.Bin(locpath.read_bytes(), True) if locpath.exists() else None
            expected = json.loads((tables / "parsed" / (name + ".json")).read_text(encoding="utf-8"))
            self.assertEqual(reader.parse_rows(schema, local), expected, name)
            count += 1
        self.assertEqual(count, 8)
