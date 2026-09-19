from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prolog_star_kb.actors import (
    EventStore,
    VerificationPolicy,
    candidate_event,
    compile_verification_facts,
    query_event,
    review_context,
    run_prolog_verification,
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
