import sys
from pathlib import Path

from extensions.route_recovery.run_2017 import run
from extensions.toolmaze_recovery.gate42a import ARCHIVE, ALTWRITE

if __name__ == "__main__":
    root = Path(sys.argv[1])
    for index in range(16):
        seed = 24000 + index
        out = root / str(seed)
        out.mkdir()
        cases = [("M3", ARCHIVE), ("M4", ALTWRITE)]
        for case, entry in cases[::1 if index % 2 == 0 else -1]:
            arms = [("direct", None),
                    ("reminder", "Please review the public tool contracts again for an available continuation."),
                    ("first", f"Candidate continuation in order: {entry}.")]
            offset = index % len(arms)
            for arm, hint in arms[offset:] + arms[:offset]:
                run(case, arm, out, post_prefix=hint, temperature=0.6, seed=seed)
