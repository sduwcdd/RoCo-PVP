"""Parse BWIKI's generated Lua data literals without running source code."""
from __future__ import annotations

import json
import re
from pathlib import Path


class WikiDataError(ValueError):
    pass


class LuaDataParser:
    """A deliberately restricted literal parser, not a Lua interpreter."""
    SPACE = re.compile(r"\s+|--[^\r\n]*")
    IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
    NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
    KEY = re.compile(r"([A-Za-z_][A-Za-z_0-9]*)\s*=")
    def __init__(self, source):
        self.source = source
        self.pos = 0

    def skip(self):
        while self.pos < len(self.source):
            match = self.SPACE.match(self.source, self.pos)
            if not match:
                return
            self.pos = match.end()

    def eat(self, value):
        self.skip()
        if self.source.startswith(value, self.pos):
            self.pos += len(value)
            return True
        return False

    def expect(self, value):
        if not self.eat(value):
            raise WikiDataError(f"Expected {value!r} at offset {self.pos}")

    def identifier(self):
        self.skip()
        match = self.IDENT.match(self.source, self.pos)
        if not match:
            raise WikiDataError(f"Expected identifier at offset {self.pos}")
        self.pos = match.end()
        return match.group()

    def string(self):
        self.skip()
        quote = self.source[self.pos]
        self.pos += 1
        chars = []
        escapes = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\", "\"": "\"", "'": "'"}
        while self.pos < len(self.source):
            char = self.source[self.pos]
            self.pos += 1
            if char == quote:
                return "".join(chars)
            if char != "\\":
                chars.append(char)
                continue
            if self.pos == len(self.source):
                raise WikiDataError("Truncated escape")
            char = self.source[self.pos]
            self.pos += 1
            if char in escapes:
                chars.append(escapes[char])
            elif char.isdigit():
                digits = char
                while len(digits) < 3 and self.pos < len(self.source) and self.source[self.pos].isdigit():
                    digits += self.source[self.pos]
                    self.pos += 1
                if int(digits) > 255:
                    raise WikiDataError("Out-of-range decimal escape")
                chars.append(chr(int(digits)))
            else:
                raise WikiDataError(f"Unsupported string escape \\{char}")
        raise WikiDataError("Unterminated string")

    def value(self):
        self.skip()
        if self.pos >= len(self.source):
            raise WikiDataError("Unexpected end of data")
        char = self.source[self.pos]
        if char == "{":
            return self.table()
        if char in "\"'":
            return self.string()
        match = self.NUMBER.match(self.source, self.pos)
        if match:
            self.pos = match.end()
            text = match.group()
            return float(text) if any(x in text for x in ".eE") else int(text)
        literal = self.identifier()
        if literal in {"true", "false", "nil"}:
            return {"true": True, "false": False, "nil": None}[literal]
        raise WikiDataError(f"Non-literal expression {literal!r}")

    def table(self):
        self.expect("{")
        keyed, array = {}, []
        while not self.eat("}"):
            self.skip()
            if self.eat("["):
                key = self.value()
                self.expect("]")
                self.expect("=")
                if type(key) not in (str, int):
                    raise WikiDataError("Non-string/non-integer table key")
                if key in keyed:
                    raise WikiDataError(f"Duplicate table key: {key}")
                keyed[key] = self.value()
            else:
                start = self.pos
                match = self.KEY.match(self.source, self.pos)
                if match:
                    self.pos = match.end()
                    key = match[1]
                    if key in keyed:
                        raise WikiDataError(f"Duplicate table key: {key}")
                    keyed[key] = self.value()
                else:
                    self.pos = start
                    array.append(self.value())
            if self.eat("}"):
                break
            if not (self.eat(",") or self.eat(";")):
                raise WikiDataError(f"Expected table separator at offset {self.pos}")
        if keyed and array:
            raise WikiDataError("Mixed keyed/array Lua tables are unsupported")
        return keyed if keyed or not array else array

    def parse(self):
        if self.identifier() != "return":
            raise WikiDataError("Data module must begin with return")
        result = self.value()
        self.skip()
        if self.pos != len(self.source):
            raise WikiDataError(f"Executable or trailing input at offset {self.pos}")
        return result


def parse_lua_data(source):
    return LuaDataParser(source).parse()


def load_catalog(root=None):
    base = Path(root) if root else Path(__file__).resolve().parents[1] / "data" / "bwiki"
    if (base / "catalog.json").exists():
        target = base / "catalog.json"
    else:
        pointer = json.loads((base / "latest.json").read_text(encoding="utf-8"))
        target = (base / pointer["snapshot_id"] / "catalog.json").resolve()
        if base.resolve() not in target.parents:
            raise WikiDataError("Snapshot path leaves data directory")
    return json.loads(target.read_text(encoding="utf-8"))
