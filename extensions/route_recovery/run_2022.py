import sys
from pathlib import Path

from extensions.route_recovery.run_2017 import run

if __name__ == "__main__":
    for case in ("M3", "M4"):
        run(case, "reminder", Path(sys.argv[1]), model="Qwen3-8B-AWQ",
            post_prefix="Please review the public tool contracts again for an available continuation.")
