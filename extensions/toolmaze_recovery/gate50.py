"""Experiment 050: lost-receipt checkpoint M5, prompt arms and a local-model runner.

A publication call timed out; it may have committed. Three private worlds share one
public prefix: C committed with the receipt lost, T not committed and a retry works,
P not committed and the writer keeps timing out. Only public()/view() and the arm text
may reach a policy. world, checkpoint() and evaluate() belong to the execution side.
"""
import argparse
from copy import deepcopy
from fractions import Fraction as F
import json
from pathlib import Path
import subprocess
from time import perf_counter
from types import SimpleNamespace

from .environment import ContractExecutor, invalid
from .gate34a import ITEMS, CONTENT, MAIN, RESOURCE, VERIFY, WRITE, TOOLS, MechanismSession
from .gate34b import initialize, run_episode
from .gate42a import ALTWRITE, CONFIRM
from .gate44a import BTM, AdviceAgent, digest
from .tasks import definition

LOOKUP = "list_record_publications"
WORLDS = ("C", "T", "P")
TIMEOUT = {"error": "Upstream request timed out."}
PREFIX_CALLS = 2
RECOVERY_CALLS = 5
NAMESPACE = "gate50-M5"
TASK = (f"For record {RESOURCE}, publish exactly one copy of its current item-level content using an "
        "actual primary evidence receipt. Read back the actual publication and check that its record, "
        "content and active status match. Give a final response.")
BASE = {d["name"]: d for d in TOOLS}
DEFINITIONS = (
    deepcopy(BASE[MAIN]),
    definition(WRITE, "Publish exactly the current record content using an actual primary evidence_ref. "
               "Not idempotent: every accepted call creates a new publication, and the endpoint does not "
               "detect earlier publications. The task forbids duplicate publications. A timeout does not "
               "show whether the publication was committed. Returns publication_id. The caller must read "
               "it back to verify publication.",
               record_id="Record authorized in the task.", content="Exact current content.",
               evidence_ref="Actual primary evidence receipt."),
    definition(ALTWRITE, "Prepare publication through an independent writer using exact source content "
               "and an actual primary evidence_ref. Returns pending_publication_ref. Preparation does not "
               "publish; confirm_alternate_publication must receive this actual reference to commit.",
               record_id="Record authorized in the task.", content="Exact current source content.",
               evidence_ref="Actual primary evidence receipt."),
    definition(CONFIRM, "Confirm and commit an actual pending_publication_ref from "
               "prepare_alternate_publication in this task. Creates a new publication and does not detect "
               "publications made by other writers. Returns publication_id. Read back that ID.",
               record_id="Record authorized in the task.",
               pending_publication_ref="Actual uncommitted preparation receipt."),
    definition(VERIFY, "Read an actual publication_id, taken from a write receipt or from "
               "list_record_publications in this task. Returns its record_id, content and active status.",
               publication_id="Actual publication ID from this task."),
    definition(LOOKUP, "List the committed publications of a record in this task, including any whose "
               "write receipt was lost. Read-only and does not change state. Returns publication_id, "
               "content and status for each.", "Diagnostic",
               record_id="Record authorized in the task."),
)


class LostReceiptSession(MechanismSession):
    def __init__(self, world, *, recovery_calls=RECOVERY_CALLS, _namespace=None):
        if world not in WORLDS or recovery_calls not in (4, 5, 6):
            raise ValueError("Unregistered experiment 050 world or budget")
        self._world, self.pending_publications = world, {}
        super().__init__(world == "T", _namespace=_namespace)
        self.call_budget = PREFIX_CALLS + recovery_calls
        definitions = {d["name"]: deepcopy(d) for d in DEFINITIONS}
        self.engine.task_description = TASK
        self.engine.tool_definitions = list(definitions.values())
        self.engine.tool_executor = ContractExecutor(definitions, RESOURCE, "", {"record_id": RESOURCE})
        self.tools = set(definitions)
        for name in definitions:
            def execute(arguments, context, tool=name):
                return self._execute(tool, arguments)
            self.engine.tool_executor.plugins[name] = SimpleNamespace(execute=execute)

    def fault_result(self, tool):
        return None  # Writer faults are decided after argument validation, in _execute.

    def charge_kind(self, tool):
        return "diagnosis" if tool == LOOKUP else "execution"

    def _writable(self, args):
        source = self.acquisitions.get(args["evidence_ref"])
        return (source is not None and source["tool"] == MAIN and source["record_id"] == args["record_id"] == RESOURCE
                and source["content"] == args["content"] == CONTENT)

    def _commit(self, operation, args, lost=False):
        identifier = self._reference()
        state = {"publication_id": identifier, "record_id": RESOURCE, "content": args["content"],
                 "status": "active", "evidence_ref": args["evidence_ref"]}
        self.publications[identifier] = state
        self.effects.append({"call": len(self.events) + 1, "operation": operation, "state": deepcopy(state),
                             "receipt_lost": lost})
        return identifier

    def _execute(self, tool, args):
        if tool == WRITE:
            if not self._writable(args):
                return invalid("An actual primary evidence_ref with the exact record content is required.")
            first = self.attempts[WRITE] == 1
            if self._world == "P" or (self._world == "T" and first):
                return dict(TIMEOUT)
            identifier = self._commit(WRITE, args, lost=self._world == "C" and first)
            return dict(TIMEOUT) if self._world == "C" and first else {"publication_id": identifier}
        if tool == ALTWRITE:
            if not self._writable(args):
                return invalid("An actual primary evidence_ref with the exact record content is required.")
            ref = self._reference()
            self.pending_publications[ref] = {"call": len(self.events) + 1, **deepcopy(args)}
            return {"pending_publication_ref": ref}
        if tool == CONFIRM:
            job = self.pending_publications.get(args["pending_publication_ref"])
            if job is None or job["record_id"] != args["record_id"]:
                return invalid("An actual publication preparation from this task is required.")
            payload = {k: job[k] for k in ("record_id", "content", "evidence_ref")}
            return {"publication_id": self._commit(CONFIRM, payload)}
        if tool == LOOKUP:
            return {"record_id": RESOURCE, "publications": [
                {k: s[k] for k in ("publication_id", "content", "status")} for s in self.publications.values()]}
        return super()._execute(tool, args)  # MAIN and VERIFY are the frozen gate34a behaviour.


def checkpoint(world, *, recovery_calls=RECOVERY_CALLS):
    """Registered exogenous prefix: a successful primary read, then one timed-out publication."""
    session = LostReceiptSession(world, recovery_calls=recovery_calls, _namespace=NAMESPACE)
    read = session.call(MAIN, {"record_id": RESOURCE})
    session.call(WRITE, {"record_id": RESOURCE, "content": read["content"], "evidence_ref": read["evidence_ref"]})
    return session


def evaluate(session, answer):
    """Independent acceptance from receipt edges, the ledger and committed effects."""
    events, issues = session.events, []
    effect = session.effects[0] if len(session.effects) == 1 else None
    if effect is None or len(session.publications) != 1:
        issues.append("Expected exactly one committed publication.")
    else:
        state, call = effect["state"], effect["call"]
        commit, ref = events[call - 1], state["evidence_ref"]
        payload = {"record_id": RESOURCE, "content": CONTENT, "evidence_ref": ref}
        anchor = call
        if effect["operation"] == CONFIRM:
            job_ref = commit["arguments"].get("pending_publication_ref")
            job = session.pending_publications.get(job_ref)
            if job is None:
                issues.append("Missing real preparation.")
            else:
                prepared, anchor = events[job["call"] - 1], job["call"]
                if (job != {"call": anchor, **payload} or not anchor < call or prepared["tool"] != ALTWRITE
                        or prepared["arguments"] != payload or prepared["illegal"]
                        or prepared["result"] != {"pending_publication_ref": job_ref}
                        or commit["arguments"] != {"record_id": RESOURCE, "pending_publication_ref": job_ref}
                        or commit["result"] != {"publication_id": state["publication_id"]}):
                    issues.append("Invalid preparation/confirmation edge.")
        elif effect["operation"] != WRITE or commit["arguments"] != payload or commit["result"] != (
                TIMEOUT if effect["receipt_lost"] else {"publication_id": state["publication_id"]}):
            issues.append("Invalid writer arguments or receipt.")
        if (commit["tool"] != effect["operation"] or commit["illegal"]
                or state != {"publication_id": state["publication_id"], **payload, "status": "active"}
                or session.publications != {state["publication_id"]: state}):
            issues.append("Invalid commit or publication state.")
        source = session.acquisitions.get(ref)
        if source is None or source["tool"] != MAIN:
            issues.append("Missing actual primary source.")
        else:
            read = events[source["call"] - 1]
            if (source != {"call": source["call"], "tool": MAIN, "record_id": RESOURCE, "content": CONTENT,
                           "granularity": "item", "items": list(ITEMS)} or not source["call"] < anchor
                    or read["tool"] != MAIN or read["illegal"] or read["arguments"] != {"record_id": RESOURCE}
                    or read["result"] != {"record_id": RESOURCE, "content": CONTENT, "evidence_ref": ref}):
                issues.append("Invalid source edge.")
        expected = {k: state[k] for k in ("publication_id", "record_id", "content", "status")}
        if not any(check == {"call": check["call"], **expected} and check["call"] > call
                   and events[check["call"] - 1]["tool"] == VERIFY and not events[check["call"] - 1]["illegal"]
                   and events[check["call"] - 1]["arguments"] == {"publication_id": state["publication_id"]}
                   and events[check["call"] - 1]["result"] == expected for check in session.checks):
            issues.append("Missing actual post-commit readback.")
    ledger = session.engine.context.history
    if len(events) > session.call_budget or len(ledger) != len(events) or any(
            event["call"] != i + 1 or entry.tool_name != event["tool"] or entry.arguments != event["arguments"]
            or entry.output != event["result"] for i, (event, entry) in enumerate(zip(events, ledger))):
        issues.append("Budget or native ledger mismatch.")
    if any(e["kind"] != session.charge_kind(e["tool"])
           or F(e["fee"]) != (session.call_fee(e["tool"]) if session.billable_call(e["tool"], e["arguments"]) else 0)
           for e in events):
        issues.append("Per-call fee or category mismatch.")
    valid = bool(isinstance(answer, str) and answer.strip()
                 and not answer.lstrip().startswith(("Error:", "Error during execution:"))
                 and not answer.strip().casefold().startswith("blocked:"))
    illegal = sum(e["illegal"] for e in events)
    fee = {kind: sum((F(e["fee"]) for e in events[PREFIX_CALLS:] if e["kind"] == kind), F())
           for kind in ("execution", "diagnosis")}
    suffix = events[PREFIX_CALLS:]
    return {"strict_success": not issues and not illegal and valid, "obligations_complete": not issues,
            "valid_answer": valid, "issues": issues, "illegal_calls": illegal,
            "publications": len(session.publications),
            "rewrites": sum(e["tool"] in (WRITE, CONFIRM) and not e["illegal"] for e in suffix),
            "lookups": sum(e["tool"] == LOOKUP for e in suffix),
            "budget_exhausted": len(events) >= session.call_budget,
            "suffix_execution_fee": str(fee["execution"]), "suffix_diagnostic_fee": str(fee["diagnosis"]),
            "events": deepcopy(events)}


# ---- Prompt arms. All arms see the same task, tools, prices, budget and prefix. ----

ARMS = ("R0", "BTM", "BTM_NR", "H")
MAPPING = f"{WRITE} -> {ALTWRITE} then {CONFIRM}, same record_id, content and evidence_ref"
MEMORY = {"prior": "Beta(1,1); no history exists for this checkpoint, so every belief is uniform",
          "tool_error": [{"tool": WRITE, "error": "Upstream request timed out.", "n": 0, "beta_mean": 0.5}],
          "switch": [{"source": WRITE, "target": ALTWRITE, "n": 0, "beta_mean": 0.5}],
          "alternatives": [MAPPING]}
BTM_RETRY_LINE = "After a tool failure, try the same tool again at least once before other options, when available."
HINT = (f"{WRITE} timed out, and a timeout does not show whether the publication was committed. The writer "
        f"is not idempotent, so writing again may create a forbidden duplicate. Before any further write, "
        f"call {LOOKUP} for the record. If it lists a publication of the exact content, read that publication "
        f"back with {VERIFY} and do not write again. If it lists none, {WRITE} may time out again, and each "
        f"later timeout would be just as ambiguous; the independent route {ALTWRITE} then {CONFIRM}, followed "
        f"by {VERIFY}, fits the remaining budget.")


def advice(arm):
    if arm not in ARMS:
        raise ValueError("Unregistered arm")
    if arm == "R0":
        return None
    if arm == "H":
        return HINT
    guidance = BTM if arm == "BTM" else BTM.replace(BTM_RETRY_LINE + "\n", "")
    if arm == "BTM_NR" and BTM_RETRY_LINE in guidance:
        raise AssertionError("Retry constraint was not removed")
    return guidance + "\nBayesian Tool Memory:\n" + json.dumps(MEMORY)


# ---- CPU reference continuations: scripted public-view policies on the real executor. ----

def _receipts(view):
    return [e["result"] for e in view["history"]]


def _evidence(view):
    return next(r["evidence_ref"] for r in _receipts(view) if "evidence_ref" in r)


def _write_args(view):
    return {"record_id": RESOURCE, "content": CONTENT, "evidence_ref": _evidence(view)}


def _scripted(view, first):
    """Shared tail after the first recovery action; uses actual receipts only."""
    last = view["history"][-1]
    tools = [e["tool"] for e in view["history"][PREFIX_CALLS:]]
    if "publication_id" in last["result"] and last["tool"] in (WRITE, CONFIRM):
        return VERIFY, {"publication_id": last["result"]["publication_id"]}
    if last["tool"] == VERIFY:
        return None
    if last["tool"] == LOOKUP:
        found = last["result"]["publications"]
        if found:
            return VERIFY, {"publication_id": found[0]["publication_id"]}
        return first(view, "none")
    if last["tool"] == ALTWRITE:
        return CONFIRM, {"record_id": RESOURCE, "pending_publication_ref": last["result"]["pending_publication_ref"]}
    return first(view, "timeout" if tools else "start")


def _policy(kind):
    def first(view, signal):
        tools = [e["tool"] for e in view["history"][PREFIX_CALLS:]]
        if kind == "retry_then_switch":
            return (WRITE, _write_args(view)) if WRITE not in tools else (ALTWRITE, _write_args(view))
        if kind == "switch_first":
            return ALTWRITE, _write_args(view)
        if kind == "lookup_then_switch":
            return (LOOKUP, {"record_id": RESOURCE}) if signal == "start" else (ALTWRITE, _write_args(view))
        if kind == "lookup_then_retry":
            if signal in ("start", "timeout"):
                return LOOKUP, {"record_id": RESOURCE}
            return (WRITE, _write_args(view)) if WRITE not in tools else (ALTWRITE, _write_args(view))
        raise ValueError(kind)
    return lambda view: _scripted(view, first)


POLICIES = ("retry_then_switch", "switch_first", "lookup_then_retry", "lookup_then_switch")
ORACLE = {"C": [(LOOKUP, None), (VERIFY, None)], "T": [(WRITE, None), (VERIFY, None)],
          "P": [(ALTWRITE, None), (CONFIRM, None), (VERIFY, None)]}


def play(policy, world, *, recovery_calls=RECOVERY_CALLS):
    """Run a public-view policy on a fresh checkpoint; the world is used only to build it."""
    session = checkpoint(world, recovery_calls=recovery_calls)
    while len(session.events) < session.call_budget:
        step = policy(deepcopy(session.view()))
        if step is None:
            break
        session.call(*step)
    return evaluate(session, "Published and verified.")


def oracle(world, *, recovery_calls=RECOVERY_CALLS):
    """Knows the world; reported only as a reference, never as an attainable policy."""
    return play(_policy({"C": "lookup_then_switch", "T": "retry_then_switch",
                         "P": "switch_first"}[world]), world, recovery_calls=recovery_calls)


def reference_table():
    rows = {}
    for budget in (4, 5, 6):
        for name in POLICIES + ("oracle",):
            cells = {w: (oracle(w, recovery_calls=budget) if name == "oracle"
                         else play(_policy(name), w, recovery_calls=budget)) for w in WORLDS}
            rows[f"{budget}:{name}"] = {
                w: {"strict": r["strict_success"], "publications": r["publications"],
                    "suffix_fee": str(F(r["suffix_execution_fee"]) + F(r["suffix_diagnostic_fee"])),
                    "calls": len(r["events"]) - PREFIX_CALLS}
                for w, r in cells.items()}
    return rows


# ---- Registered analysis (section 6 of docs/experiments/050). ----

def wilson(k, n, z=1.96):
    if not n:
        return None
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / d
    return [c - h, c + h]


def summarize(results, *, resamples=2000, seed=500050):
    """Equal-weight world average per arm; H minus BTM with a within-cell bootstrap interval."""
    import random
    cells = {(a, w): [r for r in results if r["arm"] == a and r["world"] == w] for a in ARMS for w in WORLDS}

    def weighted(arm, draw=None):
        rates = []
        for w in WORLDS:
            rows = cells[arm, w] if draw is None else [draw.choice(cells[arm, w]) for _ in cells[arm, w]]
            rates.append(sum(r["strict_success"] for r in rows) / len(rows))
        return sum(rates) / len(rates)
    arms = {}
    for a in ARMS:
        rows = [r for w in WORLDS for r in cells[a, w]]
        failures = [r for r in rows if not r["strict_success"]]
        # Conservative mechanism evidence: retain all failures in the denominator,
        # but do not attribute execution-contaminated episodes to recovery decisions.
        # This is an operational lower bound, not a causal label for illegal calls.
        clean_failures = [r for r in failures if r["illegal_calls"] == 0]
        usage = [u for r in rows for u in r["raw_usage"] if u]
        arms[a] = {
            "strict_weighted": weighted(a),
            "by_world": {w: {"k": sum(r["strict_success"] for r in cells[a, w]), "n": len(cells[a, w]),
                             "wilson95": wilson(sum(r["strict_success"] for r in cells[a, w]), len(cells[a, w]))}
                         for w in WORLDS},
            "failures": len(failures),
            "duplicate_failures": sum(r["publications"] >= 2 for r in failures),
            "budget_failures": sum(r["publications"] < 2 and r["budget_exhausted"] for r in failures),
            "execution_contaminated_failures": len(failures) - len(clean_failures),
            "mechanism_duplicate_failures": sum(r["publications"] >= 2 for r in clean_failures),
            "mechanism_budget_failures": sum(r["publications"] < 2 and r["budget_exhausted"]
                                             for r in clean_failures),
            "illegal_calls": sum(r["illegal_calls"] for r in rows),
            "lookups_per_episode": sum(r["lookups"] for r in rows) / len(rows),
            "suffix_execution_fee": sum(float(F(r["suffix_execution_fee"])) for r in rows) / len(rows),
            "suffix_diagnostic_fee": sum(float(F(r["suffix_diagnostic_fee"])) for r in rows) / len(rows),
            "prompt_tokens_per_episode": sum(u["prompt_tokens"] for u in usage) / len(rows),
            "completion_tokens_per_episode": sum(u["completion_tokens"] for u in usage) / len(rows)}
    rng = random.Random(seed)
    diffs = sorted(weighted("H", rng) - weighted("BTM", rng) for _ in range(resamples))
    diff = arms["H"]["strict_weighted"] - arms["BTM"]["strict_weighted"]
    btm = arms["BTM"]
    mechanism = (btm["mechanism_duplicate_failures"] + btm["mechanism_budget_failures"]) / btm["failures"] if btm["failures"] else 0.0
    if arms["H"]["strict_weighted"] < 0.8:
        verdict = "invalid_hint_not_executed"
    elif diff >= 0.10 and mechanism >= 0.5:
        verdict = "go"
    elif diff < 0.05:
        verdict = "no_go"
    else:
        verdict = "inconclusive"
    return {"arms": arms, "h_minus_btm": diff,
            "h_minus_btm_bootstrap95": [diffs[int(0.025 * resamples)], diffs[int(0.975 * resamples) - 1]],
            "btm_failure_share_duplicate_or_budget": mechanism, "verdict": verdict}


# ---- Local-model runner (approved GPU run only; tests use a fake SDK). ----

SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "max_tokens": 6144, "timeout": 120}
SEEDS = tuple(range(500001, 500011))


def plan():
    """Every (arm, world) gets the same seeds; arm order rotates with the seed."""
    rows = []
    for i, seed in enumerate(SEEDS):
        for world in WORLDS[i % 3:] + WORLDS[:i % 3]:
            for arm in ARMS[i % 4:] + ARMS[:i % 4]:
                rows.append({"id": f"{seed}-{world}-{arm}", "seed": seed, "world": world, "arm": arm})
    return rows


def prompt(agent, arm):
    session = checkpoint("C")
    initialize(agent, session)
    text = advice(arm)
    messages = deepcopy(agent.messages) + ([{"role": "user", "content": "Recovery information:\n" + text}]
                                           if text else [])
    return {"messages": messages, "tools": deepcopy(agent.tools)}


def observe(agent, world, arm, output, *, seed, render=None):
    output.mkdir(parents=True, exist_ok=False)
    session = checkpoint(world)
    backend = agent.client.with_options(max_retries=0).chat.completions.create
    calls, errors = [], []

    def create(**kwargs):
        if errors or len(calls) >= 12:
            raise RuntimeError("Experiment 050 request guard stopped; no replacement request")
        if "tool_choice" in kwargs or kwargs.get("parallel_tool_calls") is not False:
            raise ValueError("Native tool contract drift")
        if (kwargs["temperature"], kwargs["max_tokens"], kwargs["timeout"]) != (
                SAMPLING["temperature"], SAMPLING["max_tokens"], SAMPLING["timeout"]):
            raise ValueError("Sampling drift")
        request = deepcopy(kwargs)
        request.update(seed=seed, top_p=SAMPLING["top_p"], extra_body={"top_k": SAMPLING["top_k"]})
        row = {"index": len(calls) + 1, "request": request}
        if render:
            row["rendered_tokens"] = render(request["messages"], request["tools"])[1]
            if row["rendered_tokens"] + SAMPLING["max_tokens"] > 32768:
                errors.append("ContextLimit")
                raise RuntimeError("Local context limit before dispatch")
        calls.append(row)
        start = perf_counter()
        try:
            response = backend(**request)
            row["response"] = response.model_dump(mode="json")
            choices = row["response"].get("choices") or []
            if len(choices) != 1 or choices[0].get("finish_reason") not in ("stop", "tool_calls"):
                raise ValueError("Unexpected choices or truncation")
            return response
        except Exception as exc:
            errors.append(type(exc).__name__)
            row["error"] = f"{type(exc).__name__}: {exc}"
            raise RuntimeError("Experiment 050 protocol stopped") from None
        finally:
            row["seconds"] = perf_counter() - start
            with (output / "requests.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    original = agent.client
    agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    try:
        result = run_episode(AdviceAgent(agent, advice(arm)), session, request_limit=12, scorer=evaluate)
    finally:
        agent.client = original
    replay = checkpoint(world)
    for event in session.events[PREFIX_CALLS:]:
        replay.call(event["tool"], event["arguments"])
    expected = evaluate(replay, result["answer"])
    if any(result[k] != v for k, v in expected.items()):
        raise ValueError("Independent actual-argument replay mismatch")
    result.update(world=world, arm=arm, seed=seed, sdk_requests=len(calls), errors=errors,
                  protocol="pass" if not errors else "blocked",
                  raw_usage=[r.get("response", {}).get("usage") for r in calls])
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    from importlib.metadata import version
    import platform
    from .gate44obs import tokenizer_renderer
    from .run import MODEL, MODEL_REVISION, VLLMAgent
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model-path", type=Path, required=True)
    a = p.parse_args()
    if (platform.python_version(), version("vllm"), version("openai")) != ("3.10.12", "0.31.0", "3.42.0"):
        raise ValueError("Frozen runtime drift")
    for name in ("config.json", "tokenizer_config.json"):
        if (a.model_path / ".cache/huggingface/download" / (name + ".metadata")).read_text().splitlines()[0] != MODEL_REVISION:
            raise ValueError("Frozen model revision drift")
    render = tokenizer_renderer(a.model_path)
    a.output.mkdir(parents=True, exist_ok=False)

    def agent():
        return VLLMAgent(MODEL, "http://127.0.0.1:8000/v1", temperature=SAMPLING["temperature"],
                         max_tokens=SAMPLING["max_tokens"], request_timeout=SAMPLING["timeout"])
    prompts = {}
    for arm in ARMS:
        payload = prompt(agent(), arm)
        prompts[arm] = {"sha256": digest(payload), "rendered_tokens": render(payload["messages"], payload["tools"])[1],
                        **payload}
    freeze = {"experiment": "050", "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "model": MODEL, "revision": MODEL_REVISION, "sampling": SAMPLING, "plan": plan(),
              "prompts": prompts, "reference": reference_table()}
    (a.output / "freeze.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2), encoding="utf-8")
    progress = []
    for row in plan():
        r = observe(agent(), row["world"], row["arm"], a.output / row["id"], seed=row["seed"], render=render)
        progress.append({**row, **{k: r[k] for k in ("strict_success", "publications", "rewrites", "lookups",
                                                     "budget_exhausted", "protocol")}})
        (a.output / "progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
        if r["protocol"] != "pass":
            raise RuntimeError("Protocol blocked; no replacement episode")
    (a.output / "completed.json").write_text(json.dumps({"episodes": len(progress)}), encoding="utf-8")


if __name__ == "__main__":
    main()
