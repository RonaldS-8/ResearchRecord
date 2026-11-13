import json, sys
def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                yield path + "/" + k, a.get(k), b.get(k)
            else:
                yield from walk(a[k], b[k], path + "/" + k)
    elif repr(a) != repr(b):
        yield path, a, b
old = json.load(open(sys.argv[1], encoding="utf-8"))["result"]
new = json.load(open(sys.argv[2], encoding="utf-8"))["result"]
rows = list(walk(old, new))
def leaves(x): return sum(leaves(v) for v in x.values()) if isinstance(x, dict) else 1
print(f"{sys.argv[1].split('/')[-1]}: {len(rows)} of {leaves(old)} fields differ")
for path, a, b in rows:
    print("  ", path, a, "->", b)
