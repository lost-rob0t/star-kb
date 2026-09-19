from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .projection import load_documents, render_projection
from .tools import compile_tool_call, tool_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prolog-star-kb")
    sub = parser.add_subparsers(dest="command", required=True)

    project = sub.add_parser("project", help="project canonical StarIntel JSON/NDJSON into Prolog facts")
    project.add_argument("input", help="JSON/NDJSON file or - for stdin")
    project.add_argument("-o", "--output", help="output .pl file; defaults to stdout")

    sub.add_parser("tools", help="print AI tool definitions as JSON")

    goal = sub.add_parser("goal", help="compile a safe AI tool call into a bounded Prolog goal")
    goal.add_argument("name")
    goal.add_argument("arguments", help="JSON object containing tool arguments")

    args = parser.parse_args(argv)
    if args.command == "project":
        text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        rendered = render_projection(load_documents(text))
        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0
    if args.command == "tools":
        json.dump(tool_catalog(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    if args.command == "goal":
        arguments = json.loads(args.arguments)
        if not isinstance(arguments, dict):
            raise SystemExit("arguments must be a JSON object")
        print(compile_tool_call(args.name, arguments))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
