from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .finder import FellowFinder
from .output import print_summary, write_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find citing articles whose authors appear to hold fellow titles.")
    parser.add_argument("--config", default="config.toml", help="Path to the TOML config file.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    finder = FellowFinder(config)
    try:
        findings = finder.run()
    except Exception as exc:
        print(f"Execution failed: {exc}", file=sys.stderr)
        sys.exit(1)
    write_outputs(findings, config.output_dir)
    print_summary(findings)
