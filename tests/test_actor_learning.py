from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prolog_star_kb.actors import (
    SPEC_DIGEST,
    EventStore,
    VerificationPolicy,
    audit_report,
    candidate_event,
    compile_verification_facts,
    query_event,
    review_context,
    run_prolog_verification,
    verification_event,
    verification_packet,
    vote_event,
)


def fixture_document() -> dict:
    return {
        "_id": "starintel:relation:learning-test",
        "dataset": "learning-test",
        "dtype": "relation",
        "schema_version": "0.9.0",
        "version": 1,
        "provenance": {
            "actor": "extractor-a",
            "run_id": "run-1",
            "method": "llm-extraction",
            "model": "fixture",
        },
        "sources": [
            {"source_id": "src-1", "kind": "text", "content_hash": "abc"}
        ],
        "evidence": [
            {
                "evidence_id": "ev-1",
                "source_id": "src-1",
                "status": "supported",
                "claim": "fixture",
            }
        ],
        "data": {
            "subject": "starintel:person:a",
            "predicate": "related_to",
            "object": "starintel:org:b",
        },
    }


class ActorLearningTests(unittest.TestCase):
    def test_replay_index_is_disposable_and_rebuildable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = EventStore(Path(td) / "events.ndjson")
            event = candidate_event(
                fixture_document(),
                proposed_by="extractor-a",
                run_id="run-1",
            )
            store.append(event)
            self.assertTrue(store.index_path.exists())
            self.assertEqual(
                "starintel:relation:learning-test",
                store.latest_candidate("starintel:relation:learning-test")["candidateId"],
            )

            store.index_path.unlink()
            for suffix in ("-wal", "-shm"):
                Path(str(store.index_path) + suffix).unlink(missing_ok=True)

            rebuilt = store.latest_candidate("starintel:relation:learning-test")
            self.assertIsNotNone(rebuilt)
            self.assertEqual(event["eventId"], rebuilt["eventId"])

    def test_append_many_indexes_stream_without_materializing_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = EventStore(Path(td) / "events.ndjson")

            def events():
                for number in range(3):
                    document = fixture_document()
                    document["_id"] = f"starintel:relation:batch-{number}"
                    yield candidate_event(
                        document,
                        proposed_by="dataset-generator",
                        run_id="batch-1",
                        knowledge_status="generated",
                    )

            count = store.append_many(events(), batch_size=2)
            self.assertEqual(3, count)
            self.assertEqual(
                "starintel:relation:batch-2",
                store.latest_candidate("starintel:relation:batch-2")["candidateId"],
            )
            self.assertEqual(3, sum(1 for _ in store.events()))

    def test_event_log_replays_candidate_latest_vote_and_query_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = EventStore(Path(td) / "events.ndjson")
            store.append(candidate_event(fixture_document(), proposed_by="extractor-a", run_id="run-1"))
            store.append(vote_event(
                "starintel:relation:learning-test",
                voter="reviewer-a",
                stance="reject",
                weight=1000,
                run_id="run-2",
            ))
            store.append(vote_event(
                "starintel:relation:learning-test",
                voter="reviewer-a",
                stance="approve",
                weight=1000,
                run_id="run-3",
            ))
            store.append(query_event(
                actor="query-agent",
                query="who is related to b?",
                tool="kb_referrers",
                result_ids=["starintel:relation:learning-test"],
                result_hash="hash",
                run_id="run-q",
            ))
            packet = verification_packet(store, "starintel:relation:learning-test", VerificationPolicy())
            self.assertEqual(1, len(packet["votes"]))
            self.assertEqual("approve", packet["votes"][0]["stance"])
            context = review_context(store, candidate_id="starintel:relation:learning-test")
            self.assertEqual(1, len(context["queryObservations"]))

    def test_spec_digest_matches_canonical_starlang_source(self) -> None:
        expected = "sha256:" + hashlib.sha256(
            (ROOT / "spec" / "star-kb-learning.star").read_bytes()
        ).hexdigest()
        self.assertEqual(expected, SPEC_DIGEST)
        self.assertEqual(71, len(SPEC_DIGEST))

    def test_verification_facts_pin_exact_spec_and_policy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = EventStore(Path(td) / "events.ndjson")
            store.append(candidate_event(fixture_document(), proposed_by="extractor-a", run_id="run-1"))
            store.append(vote_event(
                "starintel:relation:learning-test",
                voter="reviewer-a",
                stance="approve",
                weight=1000,
                run_id="run-2",
            ))
            store.append(vote_event(
                "starintel:relation:learning-test",
                voter="reviewer-b",
                stance="approve",
                weight=1000,
                run_id="run-3",
            ))
            packet = verification_packet(store, "starintel:relation:learning-test", VerificationPolicy())
            facts = compile_verification_facts(packet)
            self.assertIn("org.starintel/kb-learning@1", facts)
            self.assertIn(SPEC_DIGEST, facts)
            self.assertIn("starintel-verify-v1", facts)
            self.assertIn("verification_vote", facts)

    @unittest.skipUnless(shutil.which("swipl"), "SWI-Prolog not installed")
    def test_formal_prolog_verifier_accepts_quorum(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = EventStore(Path(td) / "events.ndjson")
            store.append(candidate_event(fixture_document(), proposed_by="extractor-a", run_id="run-1"))
            for voter in ("reviewer-a", "reviewer-b"):
                store.append(vote_event(
                    "starintel:relation:learning-test",
                    voter=voter,
                    stance="approve",
                    weight=1000,
                    run_id="run-vote",
                ))
            packet = verification_packet(store, "starintel:relation:learning-test", VerificationPolicy())
            report = run_prolog_verification(packet, repo_root=ROOT)
            self.assertEqual("verified", report["decision"])
            self.assertEqual([], report["issues"])

    def test_audit_report_exposes_learning_signals_without_query_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = EventStore(Path(td) / "events.ndjson")
            store.append(candidate_event(
                fixture_document(),
                proposed_by="extractor-a",
                run_id="run-1",
            ))
            store.append(vote_event(
                "starintel:relation:learning-test",
                voter="reviewer-a",
                stance="approve",
                weight=1000,
                run_id="run-2",
            ))
            store.append(vote_event(
                "starintel:relation:learning-test",
                voter="reviewer-b",
                stance="reject",
                weight=1000,
                run_id="run-3",
            ))
            store.append(query_event(
                actor="query-agent",
                query="sensitive raw query text",
                tool="kb_neighbors",
                result_ids=[],
                run_id="run-q",
            ))
            report = audit_report(store, run_id="audit-1")
            self.assertEqual(1, report["candidateCount"])
            self.assertEqual(1, report["queryCount"])
            self.assertEqual(1, report["emptyResultQueryCount"])
            self.assertEqual(
                ["starintel:relation:learning-test"],
                report["voteDisagreements"],
            )
            self.assertNotIn("sensitive raw query text", json.dumps(report))

    def test_verification_certificate_pins_policy_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = EventStore(Path(td) / "events.ndjson")
            store.append(candidate_event(
                fixture_document(),
                proposed_by="extractor-a",
                run_id="run-1",
            ))
            packet = verification_packet(
                store,
                "starintel:relation:learning-test",
                VerificationPolicy(min_approvals=0, min_total_votes=0, min_sources=0, min_evidence=0),
            )
            event = verification_event(
                packet,
                {
                    "decision": "verified",
                    "issues": [],
                    "approveWeight": 0,
                    "rejectWeight": 0,
                    "abstainWeight": 0,
                    "totalWeight": 0,
                    "approvalCount": 0,
                    "voteCount": 0,
                },
                run_id="verify-1",
            )
            self.assertEqual("knowledge.verification.completed", event["eventType"])
            self.assertEqual(SPEC_DIGEST, event["specDigest"])
            self.assertEqual("starintel-verify-v1", event["verifier"])

    @unittest.skipUnless(shutil.which("swipl"), "SWI-Prolog not installed")
    def test_formal_prolog_verifier_rejects_spec_digest_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = EventStore(Path(td) / "events.ndjson")
            store.append(candidate_event(
                fixture_document(),
                proposed_by="extractor-a",
                run_id="run-1",
                spec_digest="sha256:" + ("0" * 64),
            ))
            for voter in ("reviewer-a", "reviewer-b"):
                store.append(vote_event(
                    "starintel:relation:learning-test",
                    voter=voter,
                    stance="approve",
                    weight=1000,
                    run_id="run-vote",
                ))
            packet = verification_packet(
                store,
                "starintel:relation:learning-test",
                VerificationPolicy(),
            )
            report = run_prolog_verification(packet, repo_root=ROOT)
            self.assertEqual("rejected", report["decision"])
            self.assertTrue(any("spec_digest_mismatch" in issue for issue in report["issues"]))

    @unittest.skipUnless(shutil.which("swipl"), "SWI-Prolog not installed")
    def test_formal_prolog_verifier_rejects_unknown_evidence_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            document = fixture_document()
            document["evidence"][0]["source_id"] = "missing-source"
            store = EventStore(Path(td) / "events.ndjson")
            store.append(candidate_event(document, proposed_by="extractor-a", run_id="run-1"))
            for voter in ("reviewer-a", "reviewer-b"):
                store.append(vote_event(
                    "starintel:relation:learning-test",
                    voter=voter,
                    stance="approve",
                    weight=1000,
                    run_id="run-vote",
                ))
            packet = verification_packet(
                store,
                "starintel:relation:learning-test",
                VerificationPolicy(),
            )
            report = run_prolog_verification(packet, repo_root=ROOT)
            self.assertEqual("rejected", report["decision"])
            self.assertTrue(any("evidence_unknown_source" in issue for issue in report["issues"]))

    @unittest.skipUnless(shutil.which("swipl"), "SWI-Prolog not installed")
    def test_formal_prolog_verifier_rejects_self_vote(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = EventStore(Path(td) / "events.ndjson")
            store.append(candidate_event(fixture_document(), proposed_by="extractor-a", run_id="run-1"))
            store.append(vote_event(
                "starintel:relation:learning-test",
                voter="extractor-a",
                stance="approve",
                weight=1000,
                run_id="run-vote-1",
            ))
            store.append(vote_event(
                "starintel:relation:learning-test",
                voter="reviewer-b",
                stance="approve",
                weight=1000,
                run_id="run-vote-2",
            ))
            packet = verification_packet(store, "starintel:relation:learning-test", VerificationPolicy())
            report = run_prolog_verification(packet, repo_root=ROOT)
            self.assertEqual("rejected", report["decision"])
            self.assertTrue(any("self_vote" in issue for issue in report["issues"]))


if __name__ == "__main__":
    unittest.main()
