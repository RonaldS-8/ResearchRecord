"""Experiment 055: a local model ranks or proposes recovery routes (offline, no agent loop).

Setting: ToolMaze C3 tasks with same-domain distractor tools (experiment 054, section 8.2).
L: the model ranks the rule generator's candidates. P: the model proposes routes from the tool list.
The model sees only the task text and public tool contracts; ground truth stays on the scoring side.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import route_discovery as rd

ARMS = ("L", "P")
BEAM = 200
K = 20
COMPLEXITY = "c3"
SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "max_tokens": 8192, "timeout": 600}
SEED = 550001
SYSTEM = "You help a tool-using agent recover after a route of tool calls has failed."


def card(contract):
    params = contract["params"]
    req = [p for p in contract["required"]]
    opt = [p for p in params if p not in req]
    lines = [f"- {contract['name']}: {contract['description'].strip()}",
             "  required inputs: " + (", ".join(f"{p} ({params[p]['description']})" for p in req) or "none")]
    if opt:
        lines.append("  optional inputs: " + ", ".join(opt))
    lines.append("  returns: " + ", ".join(contract["outputs"]))
    return "\n".join(lines)


def _head(q, contracts):
    failed = "\n".join(f"{i}. {contracts[t]['name']}" for i, t in enumerate(q["failed"], 1))
    return (f"Task given to the agent:\n{q['query']}\n\n"
            f"The agent tried this route and it failed; none of its tools may be reused:\n{failed}\n\n"
            "Details of the failed tools:\n" + "\n".join(card(contracts[t]) for t in q["failed"]))


def judge_messages(q, contracts, candidates):
    listed = "\n".join(f"C{i}: " + " -> ".join(contracts[t]["name"] for t in c) for i, c in enumerate(candidates, 1))
    tools = sorted({t for c in candidates for t in c})
    user = (_head(q, contracts) + "\n\nCandidate replacement routes (tools run in the order listed; earlier "
            f"results can feed later inputs):\n{listed}\n\nDetails of the candidate tools:\n"
            + "\n".join(card(contracts[t]) for t in tools)
            + "\n\nRank the candidates that would complete the same part of the task as the failed route, "
              "best first. Leave out candidates that would do something else. "
              'Answer with JSON only: {"ranking": ["C2", "C1"]}')
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def propose_messages(q, contracts):
    tools = [t for t in q["pool"] if t not in set(q["failed"])]
    user = (_head(q, contracts) + "\n\nAvailable tools:\n" + "\n".join(card(contracts[t]) for t in tools)
            + "\n\nPropose up to 3 replacement routes that complete the same part of the task as the failed "
              "route, using only the available tools in the order they should run, best first. "
              'Answer with JSON only: {"routes": [["tool_a", "tool_b"], ["tool_c"]]}')
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def parse(text, arm, candidates, names):
    """Return a list of routes (tuples of tool keys) or None when the answer is unusable."""
    text = (text or "").split("</think>")[-1]
    blocks = re.findall(r"\{.*\}", text, re.S)
    for block in reversed(blocks):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if arm == "L" and isinstance(data.get("ranking"), list):
            idx = [int(m.group(1)) - 1 for x in data["ranking"] if (m := re.fullmatch(r"C?(\d+)", str(x).strip()))]
            return [candidates[i] for i in dict.fromkeys(idx) if 0 <= i < len(candidates)]
        if arm == "P" and isinstance(data.get("routes"), list):
            routes = []
            for r in data["routes"]:
                if isinstance(r, list) and r and all(str(t) in names for t in r):
                    routes.append(tuple(names[str(t)] for t in r))
            return list(dict.fromkeys(routes))
    return None


def queries(data_dir):
    """C3 queries in the distractor pool, each with its rule candidates and registered split."""
    contracts = rd.load_contracts()
    dev = {frozenset(g["paths"]) for g in rd.split(rd.load_groups())[0]}
    for q in rd.task_queries(data_dir, "domain", complexities=(COMPLEXITY,)):
        d = rd.Deriver({k: v for k, v in contracts.items() if k in set(q["pool"])}, {"beam": BEAM})
        q["candidates"] = d.candidates(q["failed"], q["inputs"], k=K)
        q["b1"] = d.rank(q["failed"], q["inputs"], "B1", k=3)
        q["split"] = "dev" if frozenset([q["failed"], q["gold"][0]]) in dev else "test"
        q["id"] = f"{q['task']}:{'-'.join(q['failed'])}"
        yield q


def observe(client, model, q, arm, contracts):
    names = {c["name"]: k for k, c in contracts.items() if k in set(q["pool"]) - set(q["failed"])}
    messages = judge_messages(q, contracts, q["candidates"]) if arm == "L" else propose_messages(q, contracts)
    digest = hashlib.sha256(json.dumps(messages).encode()).hexdigest()
    try:
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=SAMPLING["temperature"], top_p=SAMPLING["top_p"],
            max_tokens=SAMPLING["max_tokens"], seed=SEED, timeout=SAMPLING["timeout"],
            extra_body={"top_k": SAMPLING["top_k"]})
    except Exception as e:  # recorded, never retried or replaced
        return {"id": q["id"], "arm": arm, "routes": None, "error": f"{type(e).__name__}: {e}", "prompt_sha256": digest}
    choice = response.choices[0]
    routes = parse(choice.message.content, arm, q["candidates"], names)
    usage = getattr(response, "usage", None)
    return {"id": q["id"], "arm": arm, "routes": [list(r) for r in routes] if routes is not None else None,
            "finish_reason": choice.finish_reason, "content": choice.message.content,
            "reasoning": getattr(choice.message, "reasoning_content", None),
            "usage": usage.model_dump() if usage is not None and hasattr(usage, "model_dump") else None,
            "error": None, "prompt_sha256": digest}


def score(qs, results):
    """Recall@1/@3 per split for B1 (rule), L and P; unusable answers count as misses."""
    subs = rd.substitutes()
    by = {(r["id"], r["arm"]): r for r in results}
    out = {}
    for split in ("dev", "test"):
        sub = [q for q in qs if q["split"] == split]
        if not sub:
            continue
        row = {"n": len(sub), "candidate_ceiling": sum(any(rd.hit(c, q["gold"][0], subs) for c in q["candidates"])
                                                        for q in sub) / len(sub)}
        for arm in ("B1",) + ARMS:
            def routes(q):
                if arm == "B1":
                    return q["b1"]
                r = by.get((q["id"], arm))
                return [tuple(x) for x in r["routes"]] if r and r["routes"] is not None else []
            for k in (1, 3):
                row[f"{arm}@{k}"] = sum(any(rd.hit(c, q["gold"][0], subs) for c in routes(q)[:k]) for q in sub) / len(sub)
            if arm != "B1":
                row[f"{arm}_unusable"] = sum(by.get((q["id"], arm), {}).get("routes") is None for q in sub) / len(sub)
                row[f"{arm}_errors"] = sum(bool(by.get((q["id"], arm), {}).get("error")) for q in sub) / len(sub)
        out[split] = row
    return out


def verdict(summary):
    """Registered in docs/experiments/055: test split, C3, Recall@3."""
    t = summary["test"]
    if max(t["L_errors"], t["P_errors"]) > 0.05:
        return {"verdict": "invalid_request_errors", "best_gain_over_rule": None}
    gain = max(t["L@3"], t["P@3"]) - t["B1@3"]
    v = "go" if gain >= 0.10 else "no_go" if gain < 0.05 else "inconclusive"
    return {"verdict": v, "best_gain_over_rule": gain}


def main(argv=None):
    from openai import OpenAI
    from .run import MODEL, MODEL_REVISION
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    a.output.mkdir(parents=True, exist_ok=False)
    contracts = rd.load_contracts()
    qs = list(queries(a.data))
    if len(qs) != 200:
        raise SystemExit(f"Expected 200 C3 queries (100 tasks x 2), found {len(qs)}; check the data directory")
    freeze = {"experiment": "055", "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "model": MODEL, "revision": MODEL_REVISION, "sampling": SAMPLING, "seed": SEED, "beam": BEAM, "k": K,
              "queries": [{k: q[k] for k in ("id", "task", "split", "failed", "candidates", "b1")} for q in qs]}
    (a.output / "freeze.json").write_text(json.dumps(freeze, indent=1), encoding="utf-8")
    client = OpenAI(base_url=a.base_url, api_key="EMPTY", max_retries=0)
    jobs = [(q, arm) for q in qs for arm in ARMS]
    with ThreadPoolExecutor(a.workers) as pool, (a.output / "responses.jsonl").open("w", encoding="utf-8") as f:
        results = []
        for r in pool.map(lambda j: observe(client, MODEL, j[0], j[1], contracts), jobs):
            results.append(r)
            f.write(json.dumps(r) + "\n")
            f.flush()
    summary = score(qs, results)
    result = {"summary": summary, **verdict(summary)}
    (a.output / "summary.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
