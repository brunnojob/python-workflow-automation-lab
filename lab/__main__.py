import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .core import GitHubReader, LabError, Policy, simulate
from .collector import Collector, Store, demo_transport


def main():
    parser = argparse.ArgumentParser(description="Isolated workflow simulation and public repository audit")
    commands = parser.add_subparsers(dest="command", required=True)
    offline = commands.add_parser("simulate")
    offline.add_argument("--output", type=Path)
    remote = commands.add_parser("audit")
    remote.add_argument("repository")
    remote.add_argument("--allow-owner", action="append", required=True)
    remote.add_argument("--output", type=Path)
    collect = commands.add_parser("collect", help="Collect public repository metadata with resumable pagination")
    collect.add_argument("owner")
    collect.add_argument("--allow-owner", action="append", required=True)
    collect.add_argument("--database", type=Path, default=Path("reports/collector.sqlite3"))
    collect.add_argument("--output", type=Path, default=Path("reports/repositories"))
    collect.add_argument("--per-page", type=int, default=30)
    collect.add_argument("--max-pages", type=int, default=5)
    collect.add_argument("--interval", type=float, default=1.0)
    collect.add_argument("--refresh", action="store_true")
    collect.add_argument("--demo", action="store_true", help="Use local fixtures and send zero network requests")
    export = commands.add_parser("export", help="Export an existing checkpoint without making requests")
    export.add_argument("owner")
    export.add_argument("--allow-owner", action="append", required=True)
    export.add_argument("--database", type=Path, default=Path("reports/collector.sqlite3"))
    export.add_argument("--output", type=Path, default=Path("reports/repositories"))
    args = parser.parse_args()
    try:
        if args.command in {"collect", "export"}:
            policy = Policy(tuple(args.allow_owner))
            policy.validate(f"{args.owner}/scope-check")
            if args.command == "collect" and args.demo and args.owner.lower() != "secondary-a":
                raise LabError("Demo mode uses owner secondary-a and a separate fixture database.")
            database = Path(str(args.database) + ".demo") if getattr(args, "demo", False) else args.database
            store = Store(database)
            try:
                result = {}
                if args.command == "collect":
                    client = Collector(policy, store, transport=demo_transport if args.demo else None, interval=args.interval)
                    result.update(client.collect(args.owner, args.per_page, args.max_pages, args.refresh))
                    result["mode"] = "offline-fixtures" if args.demo else "public-api"
                result.update(store.export(args.owner.lower(), args.output))
                print(json.dumps(result, indent=2))
                return 0
            finally:
                store.close()
        result = simulate() if args.command == "simulate" else GitHubReader(Policy(tuple(args.allow_owner))).repository(args.repository)
        rendered = json.dumps(result, indent=2)
        if args.output:
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except (LabError, OSError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
