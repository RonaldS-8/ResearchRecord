"""Transfer In-N-Out's parameter edges to one frozen publication checkpoint."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import time

from .reproduce_in_n_out import LocalModel, load_module
from extensions.toolmaze_recovery.gate42a import evaluate
from extensions.toolmaze_recovery.gate44a import RULE, restored
from extensions.toolmaze_recovery.gate44obs import tokenizer_renderer
from extensions.toolmaze_recovery.gate47 import observe
from extensions.toolmaze_recovery.run import MODEL, VLLMAgent


def public_parameters(view):
    cards = {tool["name"]: tool["paradigms"]["function_call"]["spec"]
             for tool in view["tools"]}
    inputs = {name: card["parameters"]["properties"] for name, card in cards.items()}
    fields = set().union(*inputs.values())
    outputs = {
        name: sorted(fields.intersection(re.findall(r"\b\w+\b", " ".join(
            re.findall(r"\breturns\b ([^.]+)", card["description"], re.I)))))
        for name, card in cards.items()
    }
    return cards, inputs, outputs


def available_receipts(view):
    values = {}
    for event in view["history"]:
        if "error" not in event["result"]:
            values.update(event["result"])
    return values


def derive(view, classify, select, prompt_prefix):
    cards, inputs, outputs = public_parameters(view)
    available = available_receipts(view)
    # Task-specified readback is the goal. Exclude an endpoint with an observed
    # unavailable receipt for this fixed no-retry development comparison.
    blocked = {event["tool"] for event in view["history"]
               if "unavailable" in event["result"].get("error", "").lower()}
    goals = [name for name, card in cards.items()
             if card["description"].startswith("Read ")
             and "previous publication" in card["description"]]
    if len(goals) != 1:
        raise ValueError("Expected one publicly described publication readback")

    edges = defaultdict(list)
    predictions = []
    for source in sorted(cards.keys() - blocked):
        for target in sorted(cards.keys() - blocked - {source}):
            for field in sorted(set(outputs[source]) & inputs[target].keys() - available.keys()):
                def doc(name):
                    return dict(name=name, description=cards[name]["description"],
                                input_params=sorted(inputs[name]), output_params=outputs[name])
                prompt = (
                    prompt_prefix + "\nSource API Information:\n" + json.dumps(doc(source))
                    + "\nTarget API Information:\n" + json.dumps(doc(target))
                    + f"\nPlease classify the edge between:\n{source} (output: {field}) -> "
                    + f"{target} (input: {field} ({inputs[target][field]['description']}))"
                )
                result = classify(prompt)
                predictions.append(dict(source=source, target=target, field=field, result=result))
                if result.get("edge_type") in {"strong-edge", "weak-edge"}:
                    edges[target, field].append(source)

    goal = goals[0]
    chain = [goal]
    notes = []
    while len(chain) <= view["remaining_calls"]:
        target = chain[0]
        missing = set(cards[target]["parameters"]["required"]) - available.keys()
        if not missing:
            return chain, list(reversed(notes)), predictions
        providers = {source for field in missing for source in edges[target, field]}
        if len(missing) != 1 or not providers or providers.intersection(chain):
            break
        field = next(iter(missing))
        source = select(view["task"], target, field, sorted(providers), cards, inputs, outputs)
        if source not in providers:
            break
        notes.append(f"{source} produces {field} for {target}.")
        chain.insert(0, source)
    return [], [], predictions


def verify_shadow(view, chain, factory):
    session = factory()
    initial_values = available_receipts(view)
    values = dict(initial_values)
    cards, _, _ = public_parameters(view)
    evidence = []
    for tool in chain:
        args = {name: values[name] for name in cards[tool]["parameters"]["required"]}
        receipt = session.call(tool, args)
        illegal = session.events[-1]["illegal"]
        evidence.append(dict(tool=tool, arguments=args, receipt=receipt, illegal=illegal))
        if "error" in receipt or illegal:
            return evidence, False
        values.update(receipt)
    # Verification only. This result supplies no arguments or identifiers to the policy.
    final = evidence[-1]["receipt"] if evidence else {}
    return evidence, bool(evidence and final.get("record_id") == initial_values.get("record_id")
                          and final.get("content") == initial_values.get("content")
                          and final.get("status") == "active")


def native_advised(url, advice):
    agent = VLLMAgent(MODEL, url, temperature=0, max_tokens=6144, request_timeout=120)
    original_step = agent.step

    def step():
        nonlocal advice
        if advice:
            agent.messages.append({"role": "user", "content": "Recovery information:\n" + advice})
            advice = None
        return original_step()

    agent.step = step
    return agent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    out = args.output
    out.mkdir(exist_ok=False)
    url = f"http://127.0.0.1:{args.port}/v1"
    os.environ['OPENAI_API_KEY'] = 'local'
    os.environ['OPENAI_BASE_URL'] = url
    graph = load_module("upstream_edge_classifier",
                        args.upstream / "src/graph_construction/test_zero-shot_models.py")
    retrieval = load_module("upstream_tool_retrieval",
                            args.upstream / "src/tool_retrieval/run_experiment.py")
    local = LocalModel(url, MODEL, out, request_limit=12)
    local.phase = "M4-graph"
    graph.openai_client = retrieval.openai_client = local
    public_test = json.loads(
        (args.upstream / "data/nestful/graph_construction/test_data.json").read_text())
    prefix = public_test["input"][0].split("Source API Information:", 1)[0]
    factory = lambda: restored("M4")
    view = factory().view()
    started = time.monotonic()
    def select(task, target, field, providers, cards, inputs, outputs):
        # This development scope only expands graph neighbors. It has no evaluation labels.
        apis = [dict(name=name, description=card["description"],
                     input_params=[dict(name=k, description=v["description"])
                                   for k, v in inputs[name].items()],
                     output_params=[dict(name=k) for k in outputs[name]])
                for name, card in cards.items()]
        descriptions, documentation, parameters, _ = retrieval.prepare_api_metadata(apis)
        return retrieval.select_gold_api_with_llm(
            task, target, field, providers, descriptions, documentation,
            parameters)["prerequisite_api"]

    chain, notes, predictions = derive(
        view, lambda prompt: graph.classify_edge(MODEL, prompt), select, prefix)
    evidence, confirmed = verify_shadow(view, chain, factory)
    (out / "build.json").write_text(json.dumps(dict(chain=chain, notes=notes, predictions=predictions,
                                                   evidence=evidence, confirmed=confirmed,
                                                   seconds=time.monotonic() - started), indent=2))
    if not chain:
        raise RuntimeError("Automatic graph did not supply a complete chain")

    manual = ("The existing evidence authorizes the same publication. Prepare it via the "
              "independent writer (prepare_alternate_publication), then confirm via "
              "confirm_alternate_publication using the new preparation receipt. "
              "Use read_published_record with the confirmation's publication ID. "
              "That is one publication.")
    automatic = "Candidate continuation: " + " → ".join(chain) + ". " + " ".join(notes)
    arms = {"native": None, "rule": RULE, "manual": RULE + "\n" + manual,
            "graph": RULE + "\n" + automatic}
    if confirmed:
        arms["verified_graph"] = RULE + "\n" + automatic + (
            " In a reset copy of this checkpoint, the chain completed one publication and "
            "read back the matching active record. Use new receipts from this run.")
    render = tokenizer_renderer(args.model_path)
    (out / "arms.json").write_text(json.dumps(arms, indent=2))
    for arm, advice in arms.items():
        result = observe(native_advised(url, advice), factory, evaluate, out / arm,
                         seed=201001, render=render)
        if result["protocol"] != "pass":
            raise RuntimeError(f"Protocol stopped in {arm}")


if __name__ == "__main__":
    main()
