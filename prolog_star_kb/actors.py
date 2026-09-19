from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Iterator

from .projection import prolog_atom, prolog_term

SPEC_ID = "org.starintel/kb-learning@1"
SPEC_VERSION = "0.1.0"
SPEC_PATH = Path(__file__).resolve().parents[1] / "spec" / "star-kb-learning.star"
SPEC_DIGEST = "sha256:" + hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()
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
    INDEX_VERSION = "1"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.index_path = self.path.with_suffix(self.path.suffix + ".sqlite3")

    def _connect(self) -> sqlite3.Connection:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.index_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id TEXT PRIMARY KEY,
                event_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS votes (
                candidate_id TEXT NOT NULL,
                voter TEXT NOT NULL,
                event_json TEXT NOT NULL,
                PRIMARY KEY (candidate_id, voter)
            );
            CREATE TABLE IF NOT EXISTS verifications (
                candidate_id TEXT PRIMARY KEY,
                event_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS queries (
                query_id TEXT PRIMARY KEY,
                event_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audits (
                audit_id TEXT PRIMARY KEY,
                event_json TEXT NOT NULL
            );
            """
        )
        return connection

    @staticmethod
    def _metadata(connection: sqlite3.Connection, key: str) -> str | None:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = ?",
            (key,),
        ).fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    def _set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            """
            INSERT INTO metadata(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    @staticmethod
    def _apply_event(connection: sqlite3.Connection, event: dict[str, Any]) -> None:
        event_type = event.get("eventType")
        event_json = canonical_json(event)
        if event_type == "knowledge.candidate.proposed":
            candidate_id = event.get("candidateId")
            if isinstance(candidate_id, str) and candidate_id:
                connection.execute(
                    """
                    INSERT INTO candidates(candidate_id, event_json) VALUES(?, ?)
                    ON CONFLICT(candidate_id) DO UPDATE SET event_json = excluded.event_json
                    """,
                    (candidate_id, event_json),
                )
            return
        if event_type == "knowledge.vote.cast":
            candidate_id = event.get("candidateId")
            voter = event.get("voter")
            if isinstance(candidate_id, str) and candidate_id and isinstance(voter, str) and voter:
                connection.execute(
                    """
                    INSERT INTO votes(candidate_id, voter, event_json) VALUES(?, ?, ?)
                    ON CONFLICT(candidate_id, voter) DO UPDATE SET event_json = excluded.event_json
                    """,
                    (candidate_id, voter, event_json),
                )
            return
        if event_type == "knowledge.verification.completed":
            candidate_id = event.get("candidateId")
            if isinstance(candidate_id, str) and candidate_id:
                connection.execute(
                    """
                    INSERT INTO verifications(candidate_id, event_json) VALUES(?, ?)
                    ON CONFLICT(candidate_id) DO UPDATE SET event_json = excluded.event_json
                    """,
                    (candidate_id, event_json),
                )
            return
        if event_type == "knowledge.query.observed":
            query_id = event.get("queryId")
            if isinstance(query_id, str) and query_id:
                connection.execute(
                    "INSERT OR REPLACE INTO queries(query_id, event_json) VALUES(?, ?)",
                    (query_id, event_json),
                )
            return
        if event_type == "knowledge.audit.completed":
            report = event.get("report")
            audit_id = report.get("auditId") if isinstance(report, dict) else None
            if isinstance(audit_id, str) and audit_id:
                connection.execute(
                    "INSERT OR REPLACE INTO audits(audit_id, event_json) VALUES(?, ?)",
                    (audit_id, event_json),
                )

    def _clear_index(self, connection: sqlite3.Connection) -> None:
        for table in ("candidates", "votes", "verifications", "queries", "audits"):
            connection.execute(f"DELETE FROM {table}")
        self._set_metadata(connection, "index_version", self.INDEX_VERSION)
        self._set_metadata(connection, "indexed_bytes", "0")

    def _sync_index(self, connection: sqlite3.Connection) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        file_size = self.path.stat().st_size
        version = self._metadata(connection, "index_version")
        indexed_raw = self._metadata(connection, "indexed_bytes")
        try:
            indexed_bytes = int(indexed_raw or "0")
        except ValueError:
            indexed_bytes = -1

        if version != self.INDEX_VERSION or indexed_bytes < 0 or indexed_bytes > file_size:
            self._clear_index(connection)
            connection.commit()
            indexed_bytes = 0

        if indexed_bytes == file_size:
            return

        with self.path.open("rb") as handle:
            handle.seek(indexed_bytes)
            while True:
                raw = handle.readline()
                if not raw:
                    break
                if not raw.endswith(b"\n"):
                    raise ValueError("event log ends with an incomplete record")
                value = json.loads(raw.decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("event log contains a non-object record")
                self._apply_event(connection, value)
            self._set_metadata(connection, "index_version", self.INDEX_VERSION)
            self._set_metadata(connection, "indexed_bytes", str(handle.tell()))
        connection.commit()

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        connection = self._connect()
        try:
            self._sync_index(connection)
        finally:
            connection.close()

    def append_many(self, events: Iterable[dict[str, Any]], *, batch_size: int = 1000) -> int:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        connection = self._connect()
        count = 0
        try:
            self._sync_index(connection)
            with self.path.open("ab") as handle:
                for event in events:
                    if not isinstance(event, dict):
                        raise TypeError("event must be a JSON object")
                    encoded = (canonical_json(event) + "\n").encode("utf-8")
                    handle.write(encoded)
                    self._apply_event(connection, event)
                    count += 1
                    if count % batch_size == 0:
                        handle.flush()
                        os.fsync(handle.fileno())
                        self._set_metadata(connection, "indexed_bytes", str(handle.tell()))
                        self._set_metadata(connection, "index_version", self.INDEX_VERSION)
                        connection.commit()
                handle.flush()
                os.fsync(handle.fileno())
                self._set_metadata(connection, "indexed_bytes", str(handle.tell()))
                self._set_metadata(connection, "index_version", self.INDEX_VERSION)
                connection.commit()
        finally:
            connection.close()
        return count

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        self.append_many((event,), batch_size=1)
        return event

    def rebuild_index(self) -> None:
        connection = self._connect()
        try:
            self._clear_index(connection)
            connection.commit()
            self._sync_index(connection)
        finally:
            connection.close()

    def latest_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            self._sync_index(connection)
            row = connection.execute(
                "SELECT event_json FROM candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else json.loads(row[0])

    def latest_votes(self, candidate_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            self._sync_index(connection)
            rows = connection.execute(
                """
                SELECT event_json
                FROM votes
                WHERE candidate_id = ?
                ORDER BY voter
                """,
                (candidate_id,),
            ).fetchall()
        finally:
            connection.close()
        return [json.loads(row[0]) for row in rows]

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
    spec_digest: str = SPEC_DIGEST,
    knowledge_status: str = "candidate",
) -> dict[str, Any]:
    validate_candidate_document(document)
    payload = {
        "candidateId": document["_id"],
        "document": document,
        "proposedBy": proposed_by,
        "specId": spec_id,
        "specVersion": spec_version,
        "specDigest": spec_digest,
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
    spec_digest: str = SPEC_DIGEST,
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
        "specDigest": spec_digest,
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
    found = store.latest_candidate(candidate_id)
    if found is None:
        raise KeyError(f"candidate not found: {candidate_id}")
    return found


def latest_votes(store: EventStore, candidate_id: str) -> list[dict[str, Any]]:
    return store.latest_votes(candidate_id)


@dataclass(frozen=True)
class VerificationPolicy:
    spec_id: str = SPEC_ID
    spec_version: str = SPEC_VERSION
    spec_digest: str = SPEC_DIGEST
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
            "specDigest": policy.spec_digest,
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
        ":- multifile star_verify:verification_document/12.",
        ":- multifile star_verify:verification_policy/12.",
        ":- multifile star_verify:verification_source/2.",
        ":- multifile star_verify:verification_evidence/4.",
        ":- multifile star_verify:verification_vote/7.",
        (
            "star_verify:verification_document("
            + ", ".join(
                [
                    _atom(candidate["candidateId"]),
                    _atom(document.get("dtype", "")),
                    _atom(document.get("dataset", "")),
                    _atom(document.get("schema_version", "")),
                    prolog_term(document.get("version", -1)),
                    _atom(provenance.get("actor", "")),
                    _atom(provenance.get("run_id", "")),
                    _atom(provenance.get("method", "")),
                    _atom(candidate.get("specId", "")),
                    _atom(candidate.get("specVersion", "")),
                    _atom(candidate.get("specDigest", "")),
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
                    _atom(policy["specDigest"]),
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
                    _atom(vote.get("stance", "")),
                    prolog_term(vote.get("weight", 0)),
                    _atom(vote.get("specId", "")),
                    _atom(vote.get("specVersion", "")),
                    _atom(vote.get("specDigest", "")),
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


def verification_event(
    packet: dict[str, Any],
    report: dict[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    policy = packet["policy"]
    payload = {
        "candidateId": packet["candidate"]["candidateId"],
        "decision": report.get("decision", "error"),
        "issues": list(report.get("issues", [])),
        "approveWeight": int(report.get("approveWeight", 0)),
        "rejectWeight": int(report.get("rejectWeight", 0)),
        "abstainWeight": int(report.get("abstainWeight", 0)),
        "totalWeight": int(report.get("totalWeight", 0)),
        "approvalCount": int(report.get("approvalCount", 0)),
        "voteCount": int(report.get("voteCount", 0)),
        "specId": policy["specId"],
        "specVersion": policy["specVersion"],
        "specDigest": policy["specDigest"],
        "requiredSchema": policy["requiredSchema"],
        "policy": policy,
        "verifier": "starintel-verify-v1",
        "runId": run_id,
    }
    return {
        "eventId": event_id("knowledge.verification.completed", payload),
        "eventType": "knowledge.verification.completed",
        "observedAt": utc_now(),
        **payload,
    }


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


def audit_report(
    store: EventStore,
    *,
    run_id: str,
    max_ids: int = 1000,
) -> dict[str, Any]:
    if max_ids < 0 or max_ids > 10000:
        raise ValueError("max_ids must be between 0 and 10000")

    event_types: Counter[str] = Counter()
    verification_issues: Counter[str] = Counter()
    tool_usage: Counter[str] = Counter()
    latest_candidates: dict[str, dict[str, Any]] = {}
    latest_verifications: dict[str, dict[str, Any]] = {}
    latest_votes_by_candidate: dict[str, dict[str, dict[str, Any]]] = {}
    query_count = 0
    empty_result_query_count = 0
    event_count = 0
    stream_hash = hashlib.sha256()

    for event in store.events():
        event_count += 1
        event_type = str(event.get("eventType", "unknown"))
        event_types[event_type] += 1
        event_id_value = event.get("eventId")
        if isinstance(event_id_value, str) and event_id_value:
            stream_hash.update(event_id_value.encode("utf-8"))
        else:
            stream_hash.update(canonical_json(event).encode("utf-8"))
        stream_hash.update(b"\n")

        if event_type == "knowledge.candidate.proposed":
            candidate_id = event.get("candidateId")
            if isinstance(candidate_id, str) and candidate_id:
                latest_candidates[candidate_id] = event
            continue

        if event_type == "knowledge.vote.cast":
            candidate_id = event.get("candidateId")
            voter = event.get("voter")
            if isinstance(candidate_id, str) and candidate_id and isinstance(voter, str) and voter:
                latest_votes_by_candidate.setdefault(candidate_id, {})[voter] = event
            continue

        if event_type == "knowledge.verification.completed":
            candidate_id = event.get("candidateId")
            if isinstance(candidate_id, str) and candidate_id:
                latest_verifications[candidate_id] = event
            for issue in event.get("issues", []) if isinstance(event.get("issues"), list) else []:
                verification_issues[str(issue)] += 1
            continue

        if event_type == "knowledge.query.observed":
            query_count += 1
            tool = event.get("tool")
            if isinstance(tool, str) and tool:
                tool_usage[tool] += 1
            result_ids = event.get("resultIds")
            if isinstance(result_ids, list) and not result_ids:
                empty_result_query_count += 1

    candidate_ids = sorted(latest_candidates)
    unverified = [
        candidate_id
        for candidate_id in candidate_ids
        if candidate_id not in latest_verifications
    ]
    rejected = [
        candidate_id
        for candidate_id, event in sorted(latest_verifications.items())
        if event.get("decision") == "rejected"
    ]
    spec_drift = [
        candidate_id
        for candidate_id, event in sorted(latest_candidates.items())
        if event.get("specDigest") != SPEC_DIGEST
    ]
    disagreements: list[str] = []
    for candidate_id, votes in sorted(latest_votes_by_candidate.items()):
        stances = {vote.get("stance") for vote in votes.values()}
        if "approve" in stances and "reject" in stances:
            disagreements.append(candidate_id)

    verification_decisions = Counter(
        str(event.get("decision", "unknown"))
        for event in latest_verifications.values()
    )
    generated_at = utc_now()
    audit_basis = {
        "streamHash": stream_hash.hexdigest(),
        "specDigest": SPEC_DIGEST,
        "candidateCount": len(latest_candidates),
        "verificationCount": len(latest_verifications),
        "queryCount": query_count,
    }
    return {
        "auditId": "starintel:audit:" + content_hash(audit_basis),
        "eventCount": event_count,
        "eventTypes": dict(sorted(event_types.items())),
        "candidateCount": len(latest_candidates),
        "verificationDecisions": dict(sorted(verification_decisions.items())),
        "verificationIssues": dict(sorted(verification_issues.items())),
        "voteDisagreements": disagreements[:max_ids],
        "unverifiedCandidates": unverified[:max_ids],
        "rejectedCandidates": rejected[:max_ids],
        "specDriftCandidates": spec_drift[:max_ids],
        "truncated": {
            "voteDisagreements": max(0, len(disagreements) - max_ids),
            "unverifiedCandidates": max(0, len(unverified) - max_ids),
            "rejectedCandidates": max(0, len(rejected) - max_ids),
            "specDriftCandidates": max(0, len(spec_drift) - max_ids),
        },
        "queryCount": query_count,
        "emptyResultQueryCount": empty_result_query_count,
        "toolUsage": dict(sorted(tool_usage.items())),
        "specId": SPEC_ID,
        "specVersion": SPEC_VERSION,
        "specDigest": SPEC_DIGEST,
        "generatedAt": generated_at,
        "runId": run_id,
    }


def audit_event(report: dict[str, Any]) -> dict[str, Any]:
    payload = {"report": report, "runId": report["runId"]}
    return {
        "eventId": event_id("knowledge.audit.completed", payload),
        "eventType": "knowledge.audit.completed",
        "observedAt": utc_now(),
        **payload,
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
