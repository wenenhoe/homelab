"""A small JSON5 reader: the subset renovate.json5 uses, standard library only.

Comments (`//` and `/* */`), unquoted identifier keys, single- or
double-quoted strings, and trailing commas, on top of JSON. Anything else
(hex numbers, `Infinity`, `NaN`, multi-line string continuations) is an error
rather than a guess.
"""

from __future__ import annotations

import re

_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "0": "\0"}


class Json5Error(ValueError):
    """The text isn't in the supported JSON5 subset."""


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def fail(self, message: str) -> Json5Error:
        line = self.text.count("\n", 0, self.pos) + 1
        return Json5Error(f"{message} (line {line})")

    def skip(self) -> None:
        text = self.text
        while self.pos < len(text):
            if text[self.pos].isspace():
                self.pos += 1
            elif text.startswith("//", self.pos):
                end = text.find("\n", self.pos)
                self.pos = len(text) if end == -1 else end + 1
            elif text.startswith("/*", self.pos):
                end = text.find("*/", self.pos + 2)
                if end == -1:
                    raise self.fail("unterminated /* comment")
                self.pos = end + 2
            else:
                return

    def peek(self) -> str:
        self.skip()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def expect(self, char: str) -> None:
        if self.peek() != char:
            raise self.fail(f"expected {char!r}")
        self.pos += 1

    def value(self) -> object:
        char = self.peek()
        if char == "{":
            return self.object()
        if char == "[":
            return self.array()
        if char and char in "\"'":
            return self.string()
        for literal, result in (("true", True), ("false", False), ("null", None)):
            if self.text.startswith(literal, self.pos):
                self.pos += len(literal)
                return result
        match = _NUMBER.match(self.text, self.pos)
        if match:
            self.pos = match.end()
            number = match.group()
            return float(number) if any(c in number for c in ".eE") else int(number)
        raise self.fail("unsupported value")

    def object(self) -> dict[str, object]:
        self.expect("{")
        result: dict[str, object] = {}
        while self.peek() != "}":
            char = self.peek()
            if char and char in "\"'":
                key = self.string()
            else:
                match = _IDENTIFIER.match(self.text, self.pos)
                if not match:
                    raise self.fail("expected an object key")
                key, self.pos = match.group(), match.end()
            self.expect(":")
            result[key] = self.value()
            if self.peek() == ",":
                self.pos += 1
            elif self.peek() != "}":
                raise self.fail("expected ',' or '}'")
        self.pos += 1
        return result

    def array(self) -> list[object]:
        self.expect("[")
        result: list[object] = []
        while self.peek() != "]":
            result.append(self.value())
            if self.peek() == ",":
                self.pos += 1
            elif self.peek() != "]":
                raise self.fail("expected ',' or ']'")
        self.pos += 1
        return result

    def string(self) -> str:
        quote = self.text[self.pos]
        self.pos += 1
        out: list[str] = []
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == quote:
                self.pos += 1
                return "".join(out)
            if char == "\n":
                raise self.fail("unterminated string")
            if char == "\\":
                self.pos += 1
                escape = self.text[self.pos : self.pos + 1]
                if escape == "u":
                    digits = self.text[self.pos + 1 : self.pos + 5]
                    if len(digits) != 4 or not all(c in "0123456789abcdefABCDEF" for c in digits):
                        raise self.fail("bad \\u escape")
                    out.append(chr(int(digits, 16)))
                    self.pos += 5
                    continue
                if escape == "\n" or not escape:
                    raise self.fail("line continuations aren't supported")
                out.append(_ESCAPES.get(escape, escape))
                self.pos += 1
                continue
            out.append(char)
            self.pos += 1
        raise self.fail("unterminated string")


def loads(text: str) -> object:
    parser = _Parser(text)
    result = parser.value()
    if parser.peek():
        raise parser.fail("unexpected text after the value")
    return result
