"""Repeat the registered 2_020 conditions on the official AWQ checkpoint."""
import sys
from pathlib import Path

from extensions.route_recovery.run_2020 import run_conditions

if __name__ == "__main__":
    run_conditions(Path(sys.argv[1]), model="Qwen3-8B-AWQ")
