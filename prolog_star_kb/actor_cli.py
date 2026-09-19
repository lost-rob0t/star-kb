from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .actors import (
    DEFAULT_SCHEMA_VERSION,
    SPEC_DIGEST,
    SPEC_ID,
    SPEC_VERSION,
    EventStore,
    VerificationPolicy,
    audit_event,
    audit_report,
    candidate_event,
    iter_ndjson,
    query_event,
    review_context,
    run_prolog_verification,
    verification_event,
    verification_packet,
    vote_event,
)

ROOT = Path(__file__).resolve().parents[1]


def _json_object(text: str) -> dict:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("expected a JSON object")
    return value


def _json_list(text: str) -> list:
    value = json.loads(text)
    if not isinstance(value, list):
        raise argparse.ArgumentTypeError("expected a JSON array")
    return value


def _dump(value: object) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _policy(args: argparse.Namespace) -> VerificationPolicy:
    return VerificationPolicy.from_ratio(
        approval_ratio=args.approval_ratio,
        spec_id=args.spec_id,
        spec_version=args.spec_version,
        spec_digest=args.spec_digest,
        required_schema=args.required_schema,
        min_approvals=args.min_approvals,
        min_total_votes=args.min_total_votes,
        min_sources=args.min_sources,
        min_evidence=args.min_evidence,
        allow_self_vote=args.allow_self_vote,
    )


def _run_spec_check(starlang: str) -> int:
    spec = ROOT / "spec" / "star-kb-learning.star"
    actors = sorted((ROOT / "spec" / "actors").glob("*.star"))
    commands = [[starlang, "load", str(spec)]] + [[starlang, "check", str(path)] for path in actors]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, text=True)
        if result.returncode != 0:
            return result.returncode
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="star-kb-actors")
    parser.add_argument("--log", default=".star-kb/events.ndjson", help="append-only learning/query event log")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="initialize the local append-only actor event log")
    sub.add_parser("spec", help="print canonical StarLang spec locations")
    spec_check = sub.add_parser("spec-check", help="validate canonical .star sources with StarLang")
    spec_check.add_argument("--starlang", default="starlang")

    submit = sub.add_parser("submit", help="stage one canonical StarIntel JSON document as candidate knowledge")
    submit.add_argument("file")
    submit.add_argument("--actor", required=True)
    submit.add_argument("--run-id", required=True)
    submit.add_argument("--status", choices=["candidate", "generated"], default="candidate")
    submit.add_argument("--spec-id", default=SPEC_ID)
    submit.add_argument("--spec-version", default=SPEC_VERSION)
    submit.add_argument("--spec-digest", default=SPEC_DIGEST)

    batch = sub.add_parser("submit-batch", help="stream an NDJSON dataset into candidate events")
    batch.add_argument("file")
    batch.add_argument("--actor", required=True)
    batch.add_argument("--run-id", required=True)
    batch.add_argument("--status", choices=["candidate", "generated"], default="generated")
    batch.add_argument("--spec-id", default=SPEC_ID)
    batch.add_argument("--spec-version", default=SPEC_VERSION)
    batch.add_argument("--spec-digest", default=SPEC_DIGEST)

    vote = sub.add_parser("vote", help="append or replace a voter's current vote for a candidate")
    vote.add_argument("candidate_id")
    vote.add_argument("--actor", required=True)
    vote.add_argument("--stance", choices=["approve", "reject", "abstain"], required=True)
    vote.add_argument("--weight", type=int, default=1000)
    vote.add_argument("--reason", action="append", default=[])
    vote.add_argument("--evidence-id", action="append", default=[])
    vote.add_argument("--run-id", required=True)
    vote.add_argument("--spec-id", default=SPEC_ID)
    vote.add_argument("--spec-version", default=SPEC_VERSION)
    vote.add_argument("--spec-digest", default=SPEC_DIGEST)

    query = sub.add_parser("query-log", help="record the query/tool trace visible to later review actors")
    query.add_argument("--actor", required=True)
    query.add_argument("--query", required=True)
    query.add_argument("--tool", default="")
    query.add_argument("--arguments", type=_json_object, default={})
    query.add_argument("--result-ids", type=_json_list, default=[])
    query.add_argument("--result-hash", default="")
    query.add_argument("--run-id", required=True)

    context = sub.add_parser("context", help="emit bounded replayable context for reviewer/auditor/optimizer actors")
    context.add_argument("--candidate")
    context.add_argument("--max-events", type=int, default=200)
    context.add_argument("--run-id", default="review")

    audit = sub.add_parser("audit", help="summarize query, vote, verification, and spec-drift signals")
    audit.add_argument("--max-ids", type=int, default=1000)
    audit.add_argument("--run-id", required=True)

    verify = sub.add_parser("verify", help="formally verify candidate admission in SWI-Prolog")
    verify.add_argument("candidate_id")
    verify.add_argument("--spec-id", default=SPEC_ID)
    verify.add_argument("--spec-version", default=SPEC_VERSION)
    verify.add_argument("--spec-digest", default=SPEC_DIGEST)
    verify.add_argument("--required-schema", default=DEFAULT_SCHEMA_VERSION)
    verify.add_argument("--min-approvals", type=int, default=2)
    verify.add_argument("--min-total-votes", type=int, default=2)
    verify.add_argument("--approval-ratio", default="0.6666666667")
    verify.add_argument("--min-sources", type=int, default=1)
    verify.add_argument("--min-evidence", type=int, default=1)
    verify.add_argument("--allow-self-vote", action="store_true")
    verify.add_argument("--swipl", default="swipl")
    verify.add_argument("--run-id", required=True)

    packet = sub.add_parser("packet", help="emit the exact packet that formal verification will consume")
    packet.add_argument("candidate_id")
    packet.add_argument("--spec-id", default=SPEC_ID)
    packet.add_argument("--spec-version", default=SPEC_VERSION)
    packet.add_argument("--spec-digest", default=SPEC_DIGEST)
    packet.add_argument("--required-schema", default=DEFAULT_SCHEMA_VERSION)
    packet.add_argument("--min-approvals", type=int, default=2)
    packet.add_argument("--min-total-votes", type=int, default=2)
    packet.add_argument("--approval-ratio", default="0.6666666667")
    packet.add_argument("--min-sources", type=int, default=1)
    packet.add_argument("--min-evidence", type=int, default=1)
    packet.add_argument("--allow-self-vote", action="store_true")

    args = parser.parse_args(argv)
    store = EventStore(args.log)

    if args.command == "init":
        store.init()
        _dump({"log": str(store.path), "specId": SPEC_ID, "specVersion": SPEC_VERSION, "specDigest": SPEC_DIGEST})
        return 0
    if args.command == "spec":
        _dump({
            "library": str(ROOT / "spec" / "star-kb-learning.star"),
            "actors": [str(path) for path in sorted((ROOT / "spec" / "actors").glob("*.star"))],
            "specId": SPEC_ID,
            "specVersion": SPEC_VERSION,
            "specDigest": SPEC_DIGEST,
            "rule": "StarLang source is authoritative; downstream bindings consume compiler manifests.",
        })
        return 0
    if args.command == "spec-check":
        return _run_spec_check(args.starlang)
    if args.command == "submit":
        document = json.loads(Path(args.file).read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise SystemExit("candidate file must contain one JSON object")
        event = candidate_event(
            document,
            proposed_by=args.actor,
            run_id=args.run_id,
            spec_id=args.spec_id,
            spec_version=args.spec_version,
            spec_digest=args.spec_digest,
            knowledge_status=args.status,
        )
        store.append(event)
        _dump(event)
        return 0
    if args.command == "submit-batch":
        count = 0
        for document in iter_ndjson(args.file):
            store.append(candidate_event(
                document,
                proposed_by=args.actor,
                run_id=args.run_id,
                spec_id=args.spec_id,
                spec_version=args.spec_version,
                spec_digest=args.spec_digest,
                knowledge_status=args.status,
            ))
            count += 1
        _dump({"submitted": count, "log": str(store.path)})
        return 0
    if args.command == "vote":
        event = vote_event(
            args.candidate_id,
            voter=args.actor,
            stance=args.stance,
            weight=args.weight,
            run_id=args.run_id,
            reasons=args.reason,
            evidence_ids=args.evidence_id,
            spec_id=args.spec_id,
            spec_version=args.spec_version,
            spec_digest=args.spec_digest,
        )
        store.append(event)
        _dump(event)
        return 0
    if args.command == "query-log":
        event = query_event(
            actor=args.actor,
            query=args.query,
            run_id=args.run_id,
            tool=args.tool,
            arguments=args.arguments,
            result_ids=args.result_ids,
            result_hash=args.result_hash,
        )
        store.append(event)
        _dump(event)
        return 0
    if args.command == "context":
        _dump(review_context(
            store,
            candidate_id=args.candidate,
            max_events=args.max_events,
            run_id=args.run_id,
        ))
        return 0
    if args.command == "audit":
        report = audit_report(store, run_id=args.run_id, max_ids=args.max_ids)
        store.append(audit_event(report))
        _dump(report)
        return 0
    if args.command in {"verify", "packet"}:
        policy = _policy(args)
        value = verification_packet(store, args.candidate_id, policy)
        if args.command == "packet":
            _dump(value)
            return 0
        result = run_prolog_verification(value, repo_root=ROOT, swipl=args.swipl)
        certificate = verification_event(value, result, run_id=args.run_id)
        store.append(certificate)
        _dump({**result, "verificationEventId": certificate["eventId"]})
        return 0 if result.get("decision") == "verified" else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
