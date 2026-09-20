from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prolog_star_kb.ingest.autodig import ingest_autodig, ndjson_bytes  # noqa: E402
from prolog_star_kb.projection import render_projection  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "autodig"
CLI = ROOT / "tools" / "prolog-star-kb"
REPORT_SHA = "6b8f4b0d3f2a7c51e9d04a8b13c5f6e7a2d94b0c8e1f3a5d7c9b2e4f6a8d0c3b"

SWIPL = shutil.which("swipl")


def swipl_succeeds(goal: str) -> bool:
    result = subprocess.run(
        ["swipl", "-q", "-g", goal, "-t", "halt(1)"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


class AutodigStructuredClaimTests(unittest.TestCase):
    def test_structured_claims_become_candidate_relations(self) -> None:
        text = FIXTURES.joinpath("claims.ndjson").read_text(encoding="utf-8")
        documents = ingest_autodig(text, name="claims.ndjson")
        self.assertEqual(2, len(documents))
        for document in documents:
            self.assertEqual("relation", document["dtype"])
            self.assertTrue(document["candidate"])
            self.assertTrue(document["data"]["candidate"])
            self.assertEqual("autodig-import", document["provenance"]["collector"])
            self.assertEqual("autodig-run-2026-09-19-alpha", document["provenance"]["run_id"])
            self.assertEqual("autodig-worker-k1", document["provenance"]["model"])
            self.assertTrue(document["sources"])
            self.assertTrue(document["sources"][0]["url"].startswith("https://autodig.example/"))
            self.assertEqual(REPORT_SHA, document["sources"][0]["content_hash"])
        predicates = {document["data"]["predicate"] for document in documents}
        self.assertEqual({"operates", "works_for"}, predicates)

    def test_bundle_claims_inherit_bundle_provenance(self) -> None:
        text = FIXTURES.joinpath("bundle.json").read_text(encoding="utf-8")
        documents = ingest_autodig(text, name="bundle.json")
        self.assertEqual(2, len(documents))
        for document in documents:
            self.assertEqual("autodig-run-2026-09-19-beta", document["provenance"]["run_id"])
            self.assertEqual("autodig-worker-k2", document["provenance"]["model"])
        locators = {source["url"] for document in documents for source in document["sources"]}
        self.assertEqual(
            {
                "https://autodig.example/runs/beta/report.org",
                "https://autodig.example/runs/beta/notes.org",
            },
            locators,
        )

    def test_ingest_is_deterministic(self) -> None:
        text = FIXTURES.joinpath("claims.ndjson").read_text(encoding="utf-8")
        first = ndjson_bytes(ingest_autodig(text, name="claims.ndjson"))
        second = ndjson_bytes(ingest_autodig(text, name="claims.ndjson"))
        self.assertEqual(first, second)

    def test_missing_required_fields_fail_closed(self) -> None:
        base = {
            "run_id": "r1",
            "subject": "starintel:person:x",
            "predicate": "works_for",
            "object": "starintel:org:y",
            "source_locators": ["https://example.test/a"],
        }
        for missing in ("run_id", "subject", "predicate", "object", "source_locators"):
            claim = {key: value for key, value in base.items() if key != missing}
            with self.assertRaises(ValueError, msg=f"missing {missing} must be rejected"):
                ingest_autodig(json.dumps(claim), name="claim.json")

    def test_multi_object_claim_and_confidence_passthrough(self) -> None:
        claim = {
            "run_id": "r2",
            "subject": "starintel:person:x",
            "predicate": "member_of",
            "object": ["starintel:org:y", "starintel:org:z"],
            "source_locators": ["https://example.test/a"],
            "confidence": 0.4,
        }
        document = ingest_autodig(json.dumps(claim), name="claim.json")[0]
        self.assertEqual(["starintel:org:y", "starintel:org:z"], document["data"]["object"])
        self.assertEqual(0.4, document["data"]["confidence"])


class AutodigMarkdownArchivalTests(unittest.TestCase):
    def test_markdown_is_archival_only_and_never_invents_relations(self) -> None:
        text = FIXTURES.joinpath("report.md").read_text(encoding="utf-8")
        documents = ingest_autodig(
            text,
            name="report.md",
            extra_sources=["https://autodig.example/runs/alpha/report.org"],
        )
        self.assertEqual(1, len(documents))
        document = documents[0]
        self.assertEqual("document", document["dtype"])
        self.assertEqual(text, document["data"]["content"])
        self.assertNotEqual("", document["data"]["content_sha256"])
        self.assertEqual(document["data"]["content_sha256"], document["sources"][0]["content_hash"])
        self.assertEqual("markdown-archival", document["provenance"]["method"])
        payload = json.dumps(documents)
        self.assertNotIn('"predicate"', payload)

    def test_free_text_claims_do_not_become_relations(self) -> None:
        text = FIXTURES.joinpath("report.md").read_text(encoding="utf-8")
        documents = ingest_autodig(text, name="report.md")
        self.assertEqual([], [doc for doc in documents if doc["dtype"] == "relation"])

    def test_json_that_looks_structured_but_is_prose_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ingest_autodig("# Report\nAda works for Analytical Engines.", name="input.txt")


class AutodigProjectionTests(unittest.TestCase):
    """End-to-end: candidates -> projector -> Prolog facts, provenance resolves to report hash."""

    def _projected(self) -> str:
        text = FIXTURES.joinpath("claims.ndjson").read_text(encoding="utf-8")
        documents = ingest_autodig(text, name="claims.ndjson")
        return render_projection(documents)

    def test_relation_and_provenance_facts_survive_projection(self) -> None:
        rendered = self._projected()
        self.assertIn("star_doc('starintel:candidate:autodig:", rendered)
        self.assertIn(
            "star_relation('starintel:candidate:autodig:",
            rendered,
        )
        self.assertIn("'starintel:org:harbor-city', 'operates', 'starintel:facility:harbor-branch-library'", rendered)
        self.assertIn("'starintel:person:ada-fixture', 'works_for', 'starintel:org:analytical-engines'", rendered)
        self.assertIn("star_provenance('starintel:candidate:autodig:", rendered)
        self.assertIn("'autodig-import'", rendered)
        self.assertIn("'autodig-worker-k1'", rendered)
        self.assertIn("'prolog-star-kb ingest-autodig'", rendered)

    def test_provenance_resolves_back_to_report_hash(self) -> None:
        rendered = self._projected()
        self.assertIn(f"'autodig-report', 'https://autodig.example/runs/alpha/report.org', null, null, '{REPORT_SHA}'", rendered)
        self.assertIn("star_evidence('starintel:candidate:autodig:", rendered)
        self.assertIn("council page lists the branch library", rendered)

    @unittest.skipUnless(SWIPL is not None, "swipl not available")
    def test_swipl_loads_projection_queries_relation_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            candidates = Path(td) / "candidates.ndjson"
            projection = Path(td) / "candidates.pl"
            text = FIXTURES.joinpath("claims.ndjson").read_text(encoding="utf-8")
            candidates.write_bytes(ndjson_bytes(ingest_autodig(text, name="claims.ndjson")))
            subprocess.run(
                [sys.executable, str(CLI), "project", str(candidates), "-o", str(projection)],
                check=True,
            )
            goal = (
                "use_module('kb/core/star_json.pl'), "
                f"star_json:load_projection('{projection}'), "
                "(star_json:star_relation(_, 'starintel:org:harbor-city', 'operates', 'starintel:facility:harbor-branch-library', _, _, _, _, _) -> true; halt(1)), "
                "(star_json:star_source(_, _, 'autodig-report', 'https://autodig.example/runs/alpha/report.org', _, _, "
                f"'{REPORT_SHA}') -> halt(0); halt(1))"
            )
            self.assertTrue(swipl_succeeds(goal), f"SWI-Prolog query failed: {goal}")


class AutodigCliTests(unittest.TestCase):
    def test_cli_ingest_autodig_writes_candidate_ndjson(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "candidates.ndjson"
            subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "ingest-autodig",
                    str(FIXTURES / "bundle.json"),
                    "-o",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(lines))
            documents = [json.loads(line) for line in lines]
            for document in documents:
                self.assertEqual("relation", document["dtype"])
                self.assertTrue(document["candidate"])

    def test_cli_markdown_flag_produces_single_archival_document(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "archive.ndjson"
            subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "ingest-autodig",
                    str(FIXTURES / "report.md"),
                    "--format",
                    "markdown",
                    "--source",
                    "https://autodig.example/runs/alpha/report.org",
                    "-o",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            documents = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(1, len(documents))
            self.assertEqual("document", documents[0]["dtype"])


if __name__ == "__main__":
    unittest.main()
