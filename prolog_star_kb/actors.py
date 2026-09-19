from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Iterator

from .projection import prolog_atom, prolog_term

SPEC_ID = "org.starintel/kb-learning@1"
SPEC_VERSION = "0.1.0"
DEFAULT_SCHEMA_VERSION = "0.9.0"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def event_id(kind: str, payload: dict[str, Any]) -> str:
    return "starintel:event:" + hashlib.sha256(
        (kind + "\0" + canonical_json(payload)).encode("utf-8")
    ).hexdigest()


class EventStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        self.init()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(event))
            handle.write("\n")
        return event

    def events(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"event log line {line_number} is not a JSON object")
                yield value


def validate_candidate_document(document: dict[str, Any]) -> None:
    required = ("_id", "dataset", "dtype", "schema_version", "version", "provenance")
    missing = [key for key in required if key not in document]
    if missing:
        raise ValueError("candidate document missing required fields: " + ", ".join(missing))
    if not isinstance(document["_id"], str) or not document["_id"]:
        raise ValueError("candidate _id must be a non-empty string")
    if not isinstance(document["dataset"], str) or not document["dataset"]:
        raise ValueError("candidate dataset must be a non-empty string")
    if not isinstance(document["dtype"], str) or not document["dtype"]:
        raise ValueError("candidate dtype must be a non-empty string")
    if not isinstance(document["schema_version"], str) or not document["schema_version"]:
        raise ValueError("candidate schema_version must be a non-empty string")
    if not isinstance(document["version"], int) or isinstance(document["version"], bool) or document["version"] < 0:
        raise ValueError("candidate version must be a non-negative integer")
    provenance = document["provenance"]
    if not isinstance(provenance, dict):
        raise ValueError("candidate provenance must be an object")


def candidate_event(
    document: dict[str, Any],
    *,
    proposed_by: str,
    run_id: str,
    spec_id: str = SPEC_ID,
    spec_version: str = SPEC_VERSION,
    knowledge_status: str = "candidate",
) -> dict[str, Any]:
    validate_candidate_document(document)
    payload = {
        "candidateId": document["_id"],
        "document": document,
        "proposedBy": proposed_by,
        "specId": spec_id,
        "specVersion": spec_version,
        "knowledgeStatus": knowledge_status,
        "runId": run_id,
    }
    return {
        "eventId": event_id("knowledge.candidate.proposed", payload),
        "eventType": "knowledge.candidate.proposed",
        "observedAt": utc_now(),
        **payload,
    }


def vote_event(
    candidate_id: str,
    *,
    voter: str,
    stance: str,
    weight: int,
    run_id: str,
    reasons: Iterable[str] = (),
    evidence_ids: Iterable[str] = (),
    spec_id: str = SPEC_ID,
    spec_version: str = SPEC_VERSION,
) -> dict[str, Any]:
    if stance not in {"approve", "reject", "abstain"}:
        raise ValueError("stance must be approve, reject, or abstain")
    if not isinstance(weight, int) or isinstance(weight, bool) or not 1 <= weight <= 10000:
        raise ValueError("weight must be an integer from 1 to 10000")
    payload = {
        "candidateId": candidate_id,
        "voter": voter,
        "stance": stance,
        "weight": weight,
        "specId": spec_id,
        "specVersion": spec_version,
        "reasons": list(reasons),
        "evidenceIds": list(evidence_ids),
        "runId": run_id,
    }
    return {
        "eventId": event_id("knowledge.vote.cast", {**payload, "nonce": utc_now()}),
        "eventType": "knowledge.vote.cast",
        "observedAt": utc_now(),
        **payload,
    }


def query_event(
    *,
    actor: str,
    query: str,
    run_id: str,
    tool: str = "",
    arguments: dict[str, Any] | None = None,
    result_ids: Iterable[str] = (),
    result_hash: str = "",
) -> dict[str, Any]:
    observed_at = utc_now()
    payload = {
        "queryId": "starintel:query:" + hashlib.sha256(
            (actor + "\0" + query + "\0" + observed_at).encode("utf-8")
        ).hexdigest(),
        "actor": actor,
        "query": query,
        "tool": tool,
        "arguments": arguments or {},
        "resultIds": list(result_ids),
        "resultHash": result_hash,
        "observedAt": observed_at,
        "runId": run_id,
    }
    return {
        "eventId": event_id("knowledge.query.observed", payload),
        "eventType": "knowledge.query.observed",
        **payload,
    }


def latest_candidate(store: EventStore, candidate_id: str) -> dict[str, Any]:
    found: dict[str, Any] | None = None
    for event in store.events():
        if event.get("eventType") == "knowledge.candidate.proposed" and event.get("candidateId") == candidate_id:
            found = event
    if found is None:
        raise KeyError(f"candidate not found: {candidate_id}")
    return found


def latest_votes(store: EventStore, candidate_id: str) -> list[dict[str, Any]]:
    votes: dict[str, dict[str, Any]] = {}
    for event in store.events():
        if event.get("eventType") != "knowledge.vote.cast" or event.get("candidateId") != candidate_id:
            continue
        voter = event.get("voter")
        if isinstance(voter, str) and voter:
            votes[voter] = event
    return [votes[key] for key in sorted(votes)]


@dataclass(frozen=True)
class VerificationPolicy:
    spec_id: str = SPEC_ID
    spec_version: str = SPEC_VERSION
    required_schema: str = DEFAULT_SCHEMA_VERSION
    min_approvals: int = 2
    min_total_votes: int = 2
    approval_ratio_numerator: int = 2
    approval_ratio_denominator: int = 3
    min_sources: int = 1
    min_evidence: int = 1
    allow_self_vote: bool = False

    @classmethod
    def from_ratio(cls, *, approval_ratio: str | float, **kwargs: Any) -> "VerificationPolicy":
        fraction = Fraction(str(approval_ratio)).limit_denominator(10000)
        return cls(
            approval_ratio_numerator=fraction.numerator,
            approval_ratio_denominator=fraction.denominator,
            **kwargs,
        )


def verification_packet(
    store: EventStore,
    candidate_id: str,
    policy: VerificationPolicy,
) -> dict[str, Any]:
    return {
        "candidate": latest_candidate(store, candidate_id),
        "votes": latest_votes(store, candidate_id),
        "policy": {
            "specId": policy.spec_id,
            "specVersion": policy.spec_version,
            "requiredSchema": policy.required_schema,
            "minApprovals": policy.min_approvals,
            "minTotalVotes": policy.min_total_votes,
            "approvalRatio": [
                policy.approval_ratio_numerator,
                policy.approval_ratio_denominator,
            ],
            "minSources": policy.min_sources,
            "minEvidence": policy.min_evidence,
            "allowSelfVote": policy.allow_self_vote,
        },
    }


def _atom(value: Any) -> str:
    return prolog_atom("" if value is None else str(value))


def compile_verification_facts(packet: dict[str, Any]) -> str:
    candidate = packet["candidate"]
    document = candidate["document"]
    provenance = document.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    policy = packet["policy"]
    ratio = policy["approvalRatio"]
    lines = [
        ":- multifile star_verify:verification_document/11.",
        ":- multifile star_verify:verification_policy/11.",
        ":- multifile star_verify:verification_source/2.",
        ":- multifile star_verify:verification_evidence/4.",
        ":- multifile star_verify:verification_vote/6.",
        (
            "star_verify:verification_document("
            + ", ".join(
                [
                    _atom(candidate["candidateId"]),
                    _atom(document.get("dtype", "")),
                    _atom(document.get("dataset", "")),
                    _atom(document.get("schema_version", "")),
                    prolog_term(document.get("version", -1)),
                    _atom(candidate.get("proposedBy", provenance.get("actor", ""))),
                    _atom(provenance.get("run_id", candidate.get("runId", ""))),
                    _atom(provenance.get("method", "")),
                    _atom(candidate.get("specId", "")),
                    _atom(candidate.get("specVersion", "")),
                    _atom(candidate.get("knowledgeStatus", "")),
                ]
            )
            + ")."
        ),
        (
            "star_verify:verification_policy("
            + ", ".join(
                [
                    _atom(candidate["candidateId"]),
                    _atom(policy["specId"]),
                    _atom(policy["specVersion"]),
                    _atom(policy["requiredSchema"]),
                    prolog_term(int(policy["minApprovals"])),
                    prolog_term(int(policy["minTotalVotes"])),
                    f"ratio({int(ratio[0])}, {int(ratio[1])})",
                    prolog_term(int(policy["minSources"])),
                    prolog_term(int(policy["minEvidence"])),
                    "true" if policy["allowSelfVote"] else "false",
                    _atom("starintel-verify-v1"),
                ]
            )
            + ")."
        ),
    ]
    for source in document.get("sources", []) if isinstance(document.get("sources"), list) else []:
        if isinstance(source, dict) and source.get("source_id"):
            lines.append(
                "star_verify:verification_source("
                f"{_atom(candidate['candidateId'])}, {_atom(source['source_id'])})."
            )
    for evidence in document.get("evidence", []) if isinstance(document.get("evidence"), list) else []:
        if isinstance(evidence, dict) and evidence.get("evidence_id"):
            lines.append(
                "star_verify:verification_evidence("
                + ", ".join(
                    [
                        _atom(candidate["candidateId"]),
                        _atom(evidence["evidence_id"]),
                        _atom(evidence.get("source_id", "")),
                        _atom(evidence.get("status", "")),
                    ]
                )
                + ")."
            )
    for vote in packet.get("votes", []):
        lines.append(
            "star_verify:verification_vote("
            + ", ".join(
                [
                    _atom(candidate["candidateId"]),
                    _atom(vote.get("voter", "")),
                    str(vote.get("stance", "")),
                    prolog_term(vote.get("weight", 0)),
                    _atom(vote.get("specId", "")),
                    _atom(vote.get("specVersion", "")),
                ]
            )
            + ")."
        )
    return "\n".join(lines) + "\n"


def run_prolog_verification(
    packet: dict[str, Any],
    *,
    repo_root: str | Path,
    swipl: str = "swipl",
) -> dict[str, Any]:
    executable = shutil.which(swipl)
    if executable is None:
        raise RuntimeError("SWI-Prolog is required for formal verification")
    repo_root = Path(repo_root)
    verifier = repo_root / "kb" / "core" / "star_verify.pl"
    if not verifier.exists():
        raise RuntimeError(f"formal verifier not found: {verifier}")
    candidate_id = packet["candidate"]["candidateId"]
    with tempfile.TemporaryDirectory(prefix="star-kb-verify-") as temp_dir:
        facts = Path(temp_dir) / "packet.pl"
        facts.write_text(compile_verification_facts(packet), encoding="utf-8")
        goal = f"star_verify:print_verification_report({prolog_atom(candidate_id)}),halt."
        process = subprocess.run(
            [executable, "-q", "-s", str(verifier), "-s", str(facts), "-g", goal],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "SWI-Prolog verification failed")
    result = json.loads(process.stdout)
    if not isinstance(result, dict):
        raise RuntimeError("formal verifier returned a non-object result")
    return result


def review_context(
    store: EventStore,
    *,
    candidate_id: str | None = None,
    max_events: int = 200,
    run_id: str = "review",
) -> dict[str, Any]:
    if max_events < 1 or max_events > 10000:
        raise ValueError("max_events must be between 1 and 10000")
    selected: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []
    for event in store.events():
        if candidate_id is not None:
            event_candidate = event.get("candidateId")
            result_ids = event.get("resultIds")
            relevant = event_candidate == candidate_id or (
                isinstance(result_ids, list) and candidate_id in result_ids
            )
            if not relevant and event.get("eventType") != "knowledge.query.observed":
                continue
        selected.append(event)
        if event.get("eventType") == "knowledge.query.observed":
            queries.append(event)
    selected = selected[-max_events:]
    queries = queries[-max_events:]
    generated_at = utc_now()
    return {
        "reviewId": "starintel:review:" + content_hash(
            {"candidateId": candidate_id, "events": [e.get("eventId") for e in selected], "at": generated_at}
        ),
        "candidateId": candidate_id,
        "events": selected,
        "queryObservations": queries,
        "generatedAt": generated_at,
        "runId": run_id,
    }


def iter_ndjson(path: str | Path) -> Iterator[dict[str, Any]]:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number} is not a JSON object")
            yield value
