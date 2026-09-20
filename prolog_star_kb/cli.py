from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ingest.autodig import ingest_autodig, ndjson_bytes
from .projection import ProjectionManifest, load_documents, render_projection
from .tools import compile_tool_call, tool_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prolog-star-kb")
    sub = parser.add_subparsers(dest="command", required=True)

    project = sub.add_parser("project", help="project canonical StarIntel JSON/NDJSON into Prolog facts")
    project.add_argument("input", help="JSON/NDJSON file or - for stdin")
    project.add_argument("-o", "--output", help="output .pl file; defaults to stdout")
    project.add_argument("--manifest", help="StarIntel schema release manifest JSON; defaults to the built-in current core manifest")

    sub.add_parser("tools", help="print AI tool definitions as JSON")

    goal = sub.add_parser("goal", help="compile a safe AI tool call into a bounded Prolog goal")
    goal.add_argument("name")
    goal.add_argument("arguments", help="JSON object containing tool arguments")

    ingest = sub.add_parser(
        "ingest-autodig",
        help="convert AutoDig claim bundles into candidate StarIntel NDJSON documents",
    )
    ingest.add_argument("input", help="JSON/NDJSON claim bundle, Markdown report, or - for stdin")
    ingest.add_argument("-o", "--output", help="output NDJSON file; defaults to stdout")
    ingest.add_argument(
        "--format",
        choices=("auto", "json", "markdown"),
        default="auto",
        help="input format; auto detects Markdown by file suffix",
    )
    ingest.add_argument(
        "--source",
        action="append",
        default=[],
        help="source locator to attach (repeatable; used by archival Markdown ingestion)",
    )
    ingest.add_argument("--dataset", default="autodig-import", help="dataset for generated candidates")

    args = parser.parse_args(argv)
    if args.command == "project":
        text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        manifest = ProjectionManifest()
        if args.manifest:
            raw_manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
            if not isinstance(raw_manifest, dict):
                raise SystemExit("manifest must be a JSON object")
            manifest = ProjectionManifest.from_mapping(raw_manifest)
        rendered = render_projection(load_documents(text), manifest)
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
    if args.command == "ingest-autodig":
        text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        report_format = None if args.format == "auto" else args.format
        documents = ingest_autodig(
            text,
            name=args.input,
            dataset=args.dataset,
            report_format=report_format,
            extra_sources=args.source,
        )
        payload = ndjson_bytes(documents)
        if args.output:
            Path(args.output).write_bytes(payload)
        else:
            sys.stdout.buffer.write(payload)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
