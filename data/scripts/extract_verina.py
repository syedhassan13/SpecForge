"""
Extract VERINA-BASIC tasks into language-neutral raw records.

Input : data/raw/verina.parquet (see download_data.py)
Output: data/raw/verina_basic/<verina_id>.json

For each task we keep the description, the Lean reference (for reading the
intended spec), the signature mapped to neutral types, and the positive test
cases converted from Lean literals to JSON. Tasks whose types have no clean
counterpart in both Dafny and Python (Float, Option, Map, UInt8, function
arguments, nested arrays) are skipped and listed in skipped.json.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.tasks.types import check_value, parse_type  # noqa: E402

RAW = ROOT / "data" / "raw"
OUT = RAW / "verina_basic"
UP = RAW / "upstream"

BAD_TYPES = ("Float", "Option", "Map", "UInt8", "->", "Array (Array", "Array(Array")


def lean_to_neutral(t: str) -> str:
    t = t.strip()
    while t.startswith("(") and t.endswith(")") and _balanced(t[1:-1]):
        t = t[1:-1].strip()
    parts = _split_prod(t)
    if len(parts) > 1:
        return "tuple<" + ", ".join(lean_to_neutral(p) for p in parts) + ">"
    simple = {"Int": "int", "Nat": "nat", "Bool": "bool", "Char": "char", "String": "string"}
    if t in simple:
        return simple[t]
    m = re.match(r"^(Array|List)\s+(.+)$", t)
    if m:
        return f"list<{lean_to_neutral(m.group(2))}>"
    raise ValueError(f"unmapped Lean type {t!r}")


def _balanced(s: str) -> bool:
    d = 0
    for c in s:
        d += c == "("
        d -= c == ")"
        if d < 0:
            return False
    return d == 0


def _split_prod(t: str) -> list[str]:
    parts, d, cur = [], 0, ""
    for c in t:
        if c == "(":
            d += 1
        elif c == ")":
            d -= 1
        if c == "×" and d == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += c
    parts.append(cur.strip())
    return parts


# ---------------------------------------------------------------------------
# Lean literal parser (type directed)
# ---------------------------------------------------------------------------

class _P:
    def __init__(self, s: str):
        self.s, self.i = s, 0

    def ws(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def peek(self) -> str:
        self.ws()
        return self.s[self.i] if self.i < len(self.s) else ""

    def eat(self, ch: str):
        self.ws()
        if not self.s.startswith(ch, self.i):
            raise ValueError(f"expected {ch!r} at {self.i} in {self.s!r}")
        self.i += len(ch)

    def value(self, t):
        k = t.kind
        if k in ("int", "nat"):
            self.ws()
            if self.peek() == "(":
                self.eat("(")
                v = self.value(t)
                self.eat(")")
                return v
            m = re.match(r"-?\s*\d+", self.s[self.i:])
            if not m:
                raise ValueError(f"int expected in {self.s!r}")
            self.i += m.end()
            return int(m.group(0).replace(" ", ""))
        if k == "bool":
            self.ws()
            m = re.match(r"(true|false|True|False)", self.s[self.i:])
            if not m:
                raise ValueError(f"bool expected in {self.s!r}")
            self.i += m.end()
            return m.group(1).lower() == "true"
        if k == "char":
            self.eat("'")
            if self.s[self.i] == "\\":
                c = {"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"'}[self.s[self.i + 1]]
                self.i += 2
            else:
                c = self.s[self.i]
                self.i += 1
            self.eat("'")
            return c
        if k == "string":
            self.eat('"')
            out = []
            while self.s[self.i] != '"':
                if self.s[self.i] == "\\":
                    out.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}[self.s[self.i + 1]])
                    self.i += 2
                else:
                    out.append(self.s[self.i])
                    self.i += 1
            self.i += 1
            return "".join(out)
        if k == "list":
            if self.peek() == "#":
                self.eat("#")
            self.eat("[")
            items = []
            if self.peek() != "]":
                while True:
                    items.append(self.value(t.args[0]))
                    if self.peek() == ",":
                        self.eat(",")
                        continue
                    break
            self.eat("]")
            return items
        if k == "tuple":
            self.eat("(")
            items = []
            for j, a in enumerate(t.args):
                items.append(self.value(a))
                if j < len(t.args) - 1:
                    self.eat(",")
            self.eat(")")
            return items
        raise ValueError(k)


def parse_literal(v, ntype: str):
    t = parse_type(ntype)
    if t.kind in ("int", "nat") and isinstance(v, int):
        return v
    if t.kind == "bool" and isinstance(v, bool):
        return v
    s = str(v)
    if t.kind == "string":
        # top-level strings are given raw; occasionally they are quoted
        if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
            return _P(s).value(t)
        return s
    if t.kind == "char" and len(s) == 1:
        return s
    p = _P(s)
    val = p.value(t)
    p.ws()
    if p.i != len(s):
        raise ValueError(f"trailing text in {s!r}")
    return val


def upstream_path(meta: dict) -> str:
    name, tid = meta["upstream"]["name"], meta["upstream"]["task_id"]
    if name == "clover":
        d = UP / "Clover" / "dataset" / "CloverBench" / "textbook_algo" / tid.replace("Clover_", "")
        files = sorted(d.glob("*_strong.dfy")) or sorted(d.glob("*.dfy"))
        return str(files[0].relative_to(ROOT)) if files else ""
    p = UP / "dafny-synthesis" / "MBPP-DFY-153" / "src" / f"{tid}.dfy"
    return str(p.relative_to(ROOT)) if p.exists() else ""


def main():
    df = pd.read_parquet(RAW / "verina.parquet")
    basic = df[df.difficulty == "basic"]
    OUT.mkdir(parents=True, exist_ok=True)
    skipped, kept = [], 0
    for _, row in basic.iterrows():
        sig = row["signature"]
        names = list(sig["parameters"]["param_name"])
        ltypes = list(sig["parameters"]["param_type"])
        all_types = ltypes + [sig["return_type"]]
        if any(b in t for t in all_types for b in BAD_TYPES):
            skipped.append({"id": row["id"], "reason": "type", "types": all_types})
            continue
        try:
            params = [{"name": n, "type": lean_to_neutral(t)} for n, t in zip(names, ltypes)]
            ret = lean_to_neutral(sig["return_type"])
            tests = []
            tt = row["tests"]
            for inp, exp, unexp in zip(tt["input"], tt["expected"], tt["unexpected"]):
                args = json.loads(inp)
                conv = {p["name"]: parse_literal(args[p["name"]], p["type"]) for p in params}
                e = parse_literal(list(exp)[0], ret)
                for p in params:
                    assert check_value(conv[p["name"]], parse_type(p["type"])), (p, conv)
                assert check_value(e, parse_type(ret)), (ret, e)
                wrong = []
                for u in list(unexp):
                    try:
                        uv = parse_literal(u, ret)
                        if check_value(uv, parse_type(ret)) and uv != e:
                            wrong.append(uv)
                    except Exception:  # noqa: BLE001 - some negatives are not well typed
                        pass
                tests.append({"input": conv, "expected": e, "unexpected": wrong})
        except Exception as ex:  # noqa: BLE001
            skipped.append({"id": row["id"], "reason": f"parse: {ex}"})
            continue
        rec = {
            "verina_id": row["id"],
            "name": sig["name"],
            "description": row["description"],
            "lean_code": row["lean_code"],
            "params": params,
            "returns": ret,
            "tests": tests,
            "reject_inputs": list(row["reject_inputs"]["input"]),
            "upstream": f"{row['metadata']['upstream']['name']}/{row['metadata']['upstream']['task_id']}",
            "upstream_dafny": upstream_path(row["metadata"]),
        }
        with open(OUT / f"{row['id']}.json", "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2, ensure_ascii=False)
        kept += 1
    with open(OUT / "skipped.json", "w", encoding="utf-8") as f:
        json.dump(skipped, f, indent=2)
    print(f"kept {kept}, skipped {len(skipped)}")


if __name__ == "__main__":
    main()
