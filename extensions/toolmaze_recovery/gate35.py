"""Two frozen post-hoc feedback controls, using the existing Agent execution chain."""
import argparse
import json
from pathlib import Path

from .gate34b import PAIRS, episode, p05_checkpoint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    # Validate the pair before any model request, including the exact first-request delta.
    old_session, old, _ = p05_checkpoint(args.source, "original")
    new_session, new, _ = p05_checkpoint(args.source, "specific")
    new["messages"][-1]["content"] = old["messages"][-1]["content"]
    if old != new or old_session.view()["remaining_calls"] != 2 or new_session.view()["remaining_calls"] != 2:
        raise ValueError("Checkpoint controls differ beyond the registered rejection")
    args.out.mkdir(parents=True, exist_ok=False)
    for condition in ("original", "specific"):
        result = episode(args.out / condition, PAIRS[4], "react", "http://127.0.0.1:8000/v1",
                         write_feedback=condition, resume_source=args.source)
        print(condition, result["strict_success"], result["obligations_complete"], flush=True)
        if result["sdk_error"]:
            raise RuntimeError("SDK failure retained; no further experimental runs")
    (args.out / "completed.json").write_text(json.dumps({"conditions": ["original", "specific"]}))


if __name__ == "__main__":
    main()
