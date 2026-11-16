"""Does replacing Python >= 3.12's compensated float sum() by the plain left-to-right sum of
Python <= 3.11 turn this machine's digests into the reviewer's? Usage: naive_sum.py <round> <cell> [first:stop] [naive|builtin]"""
from hashlib import sha256
import json
import sys

from extensions.toolmaze_recovery import autoresearch, autoresearch_rounds, belief, belief_rounds, gate34a
from extensions.toolmaze_recovery import multipath, multipath_rounds, simple_rules


def plain(values, start=0):
    total = start
    for value in values:
        total = total + value
    return total


rnd, cell = sys.argv[1], sys.argv[2]
part = range(*map(int, sys.argv[3].split(":"))) if len(sys.argv) > 3 and ":" in sys.argv[3] else None
mode = sys.argv[-1] if sys.argv[-1] in ("naive", "builtin") else "naive"
if mode == "naive":
    for module in (autoresearch, autoresearch_rounds, belief, belief_rounds, gate34a, multipath, multipath_rounds,
                   simple_rules):
        module.sum = plain
result = belief_rounds.ROUNDS[rnd](cell, part) if part else belief_rounds.ROUNDS[rnd](cell)
stored = json.loads(json.dumps(result, ensure_ascii=False))
digest = sha256(json.dumps(stored, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
print(f"{rnd} {cell} {sys.argv[3] if part else ''} sum={mode} python {sys.version.split()[0]} digest {digest}", flush=True)
if len(sys.argv) > 4 and sys.argv[4].endswith(".json") or (len(sys.argv) > 3 and sys.argv[3].endswith(".json")):
    out = [a for a in sys.argv if a.endswith(".json")][0]
    with open(out, "x", encoding="utf-8") as stream:
        json.dump({"sum": mode, "python": sys.version, "round": rnd, "cell": cell, "result": stored}, stream, indent=1,
                  ensure_ascii=False)
