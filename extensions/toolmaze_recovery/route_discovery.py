"""Experiment 054: recover ToolMaze alternate routes from public tool contracts (CPU only).

The deriver sees only what an agent sees: tool name, description, parameters and output fields,
plus the task input names. Ground truth (alternatives.yaml, `substitutes`) is read only by the
evaluator side of this module (`load_groups`, `hit`).
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFS = ROOT / "benchmarks" / "ToolMaze" / "tools" / "definitions"
FILES = ("source", "processor", "action")
FORBIDDEN = ("substitutes", "domain", "category")
ARMS = ("B0", "B1", "D")
MAX_DEPTH = 6
STOP = {"a", "an", "the", "of", "for", "to", "and", "or", "with", "from", "by", "in", "on", "using",
        "api", "call", "this", "tool", "parameter", "is", "type", "string", "integer", "number",
        "representing", "returns", "dictionary", "containing", "keys", "key", "e", "g", "it", "as",
        "be", "that", "which", "list", "object", "array", "value", "values", "specified", "given"}

# Tuned on the development split only (section 4 of the registration).
PARAMS = {"match": 0.5, "beam": 40, "coverage": 0.5, "w_cov": 1.0, "w_desc": 0.6, "w_ctx": 0.3,
          "w_len": 0.02, "w_overlap": 1.0}


@lru_cache(maxsize=None)
def _tokens(text):
    words = re.findall(r"[a-z]+|[A-Z][a-z]*|\d+", text.replace("_", " "))
    return tuple(w.lower() for w in words if w.lower() not in STOP and len(w) > 1)


def tokens(text):
    return list(_tokens(str(text)))


# ---------------------------------------------------------------- public contracts (deriver side)
def load_contracts(mask_names=False):
    """Agent-visible contract per tool. Forbidden metadata is dropped here and never returned."""
    raw = [t for f in FILES for t in yaml.safe_load((DEFS / f"{f}.yaml").read_text(encoding="utf-8"))["tools"]]
    alias = {t["name"]: f"T{i:04d}" for i, t in enumerate(sorted(raw, key=lambda t: t["name"]))}
    out = {}
    for t in raw:
        spec = t["paradigms"]["function_call"]["spec"]
        mcp = t["paradigms"]["mcp"]
        name = alias[t["name"]] if mask_names else t["name"]
        desc = f"{spec.get('description', '')} {mcp.get('prompt_description', '')}"
        if mask_names:
            desc = desc.replace(t["name"], name)
        props = spec["parameters"].get("properties", {})
        out[t["name"]] = {
            "name": name,
            "description": desc,
            "params": {p: {"description": v.get("description", ""), "enum": bool(v.get("enum"))}
                       for p, v in props.items()},
            "required": list(spec["parameters"].get("required", [])),
            "outputs": list(mcp.get("output_schema", {})),
        }
    return out


# ---------------------------------------------------------------- ground truth (evaluator side)
def load_groups():
    data = yaml.safe_load((DEFS / "alternatives.yaml").read_text(encoding="utf-8"))["alternatives"]
    groups = []
    for kind, block in data.items():
        for gid, g in block.items():
            paths = [tuple(x["tool_name"] for x in p["tools"]) for p in g["paths"]]
            inputs = sorted({v for p in g["paths"] for x in p["tools"] for v in (x.get("params") or {}).values()
                             if isinstance(v, str) and not v.startswith(("$", "'"))})
            groups.append({"id": gid, "kind": kind, "paths": paths, "inputs": inputs})
    return groups


def split(groups):
    """Registered split: within each kind, order by sha256('054:'+id); first half dev, rest test."""
    dev, test = [], []
    for kind in sorted({g["kind"] for g in groups}):
        ordered = sorted((g for g in groups if g["kind"] == kind),
                         key=lambda g: hashlib.sha256(f"054:{g['id']}".encode()).hexdigest())
        half = len(ordered) // 2
        dev += ordered[:half]
        test += ordered[half:]
    return dev, test


def substitutes():
    raw = [t for f in FILES for t in yaml.safe_load((DEFS / f"{f}.yaml").read_text(encoding="utf-8"))["tools"]]
    return {t["name"]: set(t.get("substitutes") or []) for t in raw}


def hit(candidate, gold, subs):
    return len(candidate) == len(gold) and all(c == g or c in subs.get(g, ()) for c, g in zip(candidate, gold))


def queries(groups):
    for g in groups:
        for i, failed in enumerate(g["paths"]):
            yield {"group": g["id"], "kind": g["kind"], "failed": failed, "inputs": g["inputs"],
                   "gold": [p for j, p in enumerate(g["paths"]) if j != i]}


# ---------------------------------------------------------------- deriver
class Deriver:
    def __init__(self, contracts, params=None):
        self.c = contracts
        self.p = dict(PARAMS, **(params or {}))
        self._match = {}
        self._supports = {}
        n = len(contracts)
        df = Counter(f for t in contracts.values() for f in set(t["outputs"]))
        self.idf = {f: math.log((1 + n) / (1 + k)) + 1 for f, k in df.items()}
        self.bag = {k: Counter(tokens(t["name"]) + tokens(t["description"]) + [w for o in t["outputs"] for w in tokens(o)])
                    for k, t in contracts.items()}

    # -- parameter satisfaction
    def match(self, param, info, field):
        key = (param, info["description"], field)
        if key not in self._match:
            self._match[key] = self._score(param, info, field)
        return self._match[key]

    def _score(self, param, info, field):
        if param == field:
            return 1.0
        a, b = set(tokens(param)), set(tokens(field))
        jac = len(a & b) / len(a | b) if a | b else 0.0
        if a & b - {"id"} or (a == b == {"id"}):
            jac = max(jac, 0.5 if a & b - {"id"} else jac)
        desc = set(tokens(info["description"]))
        if b and b - {"id"} and (b - {"id"}) <= desc:
            jac = max(jac, 0.5)
        return jac

    def supports(self, field):
        """(tool, param) pairs that this field can fill (cached per field)."""
        if field not in self._supports:
            self._supports[field] = frozenset(
                (k, p) for k, t in self.c.items() for p in t["required"]
                if self.match(p, t["params"][p], field) >= self.p["match"])
        return self._supports[field]

    def filled(self, fields):
        return frozenset().union(*(self.supports(f) for f in fields)) if fields else frozenset()

    def satisfied(self, tool, available, consume=None):
        """All required params matched by available fields; if `consume`, at least one by those fields."""
        t = self.c[tool]
        have = self.filled(available)
        for p in t["required"]:
            if (tool, p) not in have and not t["params"][p]["enum"]:
                return False
        if consume is None:
            return True
        prev = self.filled(consume)
        return any((tool, p) in prev for p in t["required"])

    # -- similarity helpers
    def cos(self, x, y):
        num = sum(x[w] * y[w] for w in x.keys() & y.keys())
        den = math.sqrt(sum(v * v for v in x.values())) * math.sqrt(sum(v * v for v in y.values()))
        return num / den if den else 0.0

    def coverage(self, target, outputs):
        tgt = set(target)
        if not tgt:
            return 0.0
        got = {f for f in tgt if any(f == o or (set(tokens(f)) - {"id"} and set(tokens(f)) <= set(tokens(o))) for o in outputs)}
        return sum(self.idf.get(f, 1) for f in got) / sum(self.idf.get(f, 1) for f in tgt)

    # -- chain search
    def chains(self, inputs, context, avoid=()):
        frontier = [((t,), set(inputs) | set(self.c[t]["outputs"])) for t in self.c if self.satisfied(t, inputs)]
        out = []
        for depth in range(1, MAX_DEPTH + 1):
            frontier.sort(key=lambda x: -(self.cos(sum((self.bag[t] for t in x[0]), Counter()), context)
                                          - self.p["w_overlap"] * len(set(x[0]) & set(avoid)) / len(x[0])))
            frontier = frontier[: self.p["beam"]]
            out += [c for c, _ in frontier]
            if depth == MAX_DEPTH:
                break
            nxt = []
            for chain, avail in frontier:
                have = self.filled(avail)
                prev = self.filled(self.c[chain[-1]]["outputs"])
                cand = {k for k, _ in prev} - set(chain)
                for t in cand:
                    req = self.c[t]["required"]
                    if all((t, p) in have or self.c[t]["params"][p]["enum"] for p in req):
                        nxt.append((chain + (t,), avail | set(self.c[t]["outputs"])))
            frontier = nxt
        return out

    def rank(self, failed, inputs, arm, k=5):
        term = self.c[failed[-1]]
        if arm == "B0":
            ref = set(tokens(term["name"]))
            scored = []
            for t, v in self.c.items():
                if (t,) == failed:
                    continue
                a = set(tokens(v["name"]))
                scored.append((len(a & ref) / len(a | ref) if a | ref else 0.0, (t,)))
            return [c for s, c in sorted(scored, key=lambda x: (-x[0], x[1])) if s > 0][:k]
        context = sum((self.bag[t] for t in failed), Counter())
        scored = []
        for chain in self.chains(inputs, context, avoid=failed):
            if chain == failed:
                continue
            outs = self.c[chain[-1]]["outputs"]
            # Shared by B1 and D: the failed route's tools are presumed unavailable.
            overlap = self.p["w_overlap"] * len(set(chain) & set(failed)) / len(set(chain))
            if arm == "B1":
                inter = set(outs) & set(term["outputs"])
                if not inter:
                    continue
                s = len(inter) / len(set(outs) | set(term["outputs"])) - self.p["w_len"] * len(chain) - overlap
            else:
                cov = self.coverage(term["outputs"], outs)
                if cov < self.p["coverage"]:
                    continue
                s = (self.p["w_cov"] * cov + self.p["w_desc"] * self.cos(self.bag[chain[-1]], self.bag[failed[-1]])
                     + self.p["w_ctx"] * self.cos(sum((self.bag[t] for t in chain), Counter()), context)
                     - self.p["w_len"] * len(chain) - overlap)
            scored.append((s, chain))
        seen, ranked = set(), []
        for s, c in sorted(scored, key=lambda x: (-x[0], x[1])):
            if c not in seen:
                seen.add(c)
                ranked.append(c)
        return ranked[:k]


# ---------------------------------------------------------------- evaluation
def evaluate(groups, *, arms=ARMS, mask_names=False, params=None):
    contracts = load_contracts(mask_names)
    d = Deriver(contracts, params)
    subs = substitutes()
    rows = []
    for q in queries(groups):
        for arm in arms:
            ranked = d.rank(q["failed"], q["inputs"], arm, k=5)
            pos = next((i + 1 for i, c in enumerate(ranked) if any(hit(c, g, subs) for g in q["gold"])), None)
            rows.append({"group": q["group"], "kind": q["kind"], "arm": arm, "failed": list(q["failed"]),
                         "rank": pos, "false_top3": sum(not any(hit(c, g, subs) for g in q["gold"]) for c in ranked[:3]),
                         "top3": [list(c) for c in ranked[:3]]})
    return rows


def summarize(rows):
    out = {}
    for arm in sorted({r["arm"] for r in rows}):
        rs = [r for r in rows if r["arm"] == arm]
        def rec(sub, k):
            return sum(r["rank"] is not None and r["rank"] <= k for r in sub) / len(sub) if sub else None
        out[arm] = {"n": len(rs), "recall@1": rec(rs, 1), "recall@3": rec(rs, 3), "recall@5": rec(rs, 5),
                    "false_top3": sum(r["false_top3"] for r in rs) / len(rs),
                    "by_kind": {k: {"n": len(s), "recall@3": rec(s, 3)}
                                for k in sorted({r["kind"] for r in rs}) for s in [[r for r in rs if r["kind"] == k]]}}
    return out


def verdict(summary):
    d = summary["D"]
    r3, m2m = d["recall@3"], d["by_kind"].get("many_to_many", {}).get("recall@3", 0.0)
    if r3 >= 0.80 and m2m >= 0.60:
        v = "go"
    elif r3 < 0.50:
        v = "no_go"
    else:
        v = "inconclusive"
    b1 = summary.get("B1")
    no_increment = bool(b1) and (r3 - b1["recall@3"] < 0.05) and d["false_top3"] >= b1["false_top3"]
    return {"verdict": v, "obligation_matching_no_increment": no_increment}
