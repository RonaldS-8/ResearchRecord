"""Run the upstream edge classifier and prerequisite retrieval on public NESTful."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import time

from openai import OpenAI


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LocalModel:
    def __init__(self, url, model, output):
        self.client = OpenAI(base_url=url, api_key="local", max_retries=0, timeout=120)
        self.model = model
        self.output = output
        self.phase = None
        self.requests = 0

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, *, messages, model):
        if self.requests >= 80:
            raise RuntimeError("Public sample reached its request budget")
        self.requests += 1
        request = dict(messages=messages, model=self.model, max_tokens=6144, temperature=0)
        started = time.monotonic()
        response = self.client.chat.completions.create(**request)
        with (self.output / "requests.jsonl").open("a") as log:
            log.write(json.dumps(dict(phase=self.phase, request=request,
                                     response=response.model_dump(), seconds=time.monotonic() - started)) + "\n")
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--embedding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    embedding_path = args.embedding.resolve()
    os.chdir(args.upstream)
    os.environ["OPENAI_API_KEY"] = "local"
    url = f"http://127.0.0.1:{args.port}/v1"
    os.environ["OPENAI_BASE_URL"] = url
    graph = load_module("upstream_edge_classifier", "src/graph_construction/test_zero-shot_models.py")
    retrieval = load_module("upstream_tool_retrieval", "src/tool_retrieval/run_experiment.py")
    model = LocalModel(url, "Qwen3-4B-Thinking-2507", output)
    graph.openai_client = retrieval.openai_client = model
    embedding = retrieval.SentenceTransformer(str(embedding_path), device="cpu")
    test_data = json.loads(Path("data/nestful/graph_construction/test_data.json").read_text())
    model.phase = "edge"
    results = []
    for prompt, label in list(zip(test_data["input"], test_data["output"]))[:12]:
        prediction = graph.classify_edge(model.model, prompt)
        results.append(dict(expected=json.loads(label)["edge_type"], prediction=prediction))
        (output / "edges.json").write_text(json.dumps(results, indent=2) + "\n")

    for label, enabled, gold in [("plain", False, False), ("automated", True, False), ("gold", True, True)]:
        model.phase = label
        tasks, apis = retrieval.load_experiment_data("nestful", enabled, gold)
        # The upstream grader reads the first labeled prerequisite per target parameter.
        retrieval.retrieve_top_k_apis(tasks[:8], apis, embedding, enabled, 5, os.path.relpath(output / label))


if __name__ == "__main__":
    main()
