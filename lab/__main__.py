import argparse
import json
import sys
from pathlib import Path

from .core import GitHubReader, LabError, Policy, simulate


def main():
    parser = argparse.ArgumentParser(description="Isolated workflow simulation and public repository audit")
    commands = parser.add_subparsers(dest="command", required=True)
    offline = commands.add_parser("simulate")
    offline.add_argument("--output", type=Path)
    remote = commands.add_parser("audit")
    remote.add_argument("repository")
    remote.add_argument("--allow-owner", action="append", required=True)
    remote.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = simulate() if args.command == "simulate" else GitHubReader(Policy(tuple(args.allow_owner))).repository(args.repository)
        rendered = json.dumps(result, indent=2)
        if args.output:
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except (LabError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
