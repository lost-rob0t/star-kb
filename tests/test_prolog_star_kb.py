from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prolog_star_kb.projection import ProjectionManifest, load_documents, project_document, prolog_atom, render_projection
from prolog_star_kb.tools import compile_tool_call, tool_catalog


class ProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = {
            "_id": "starintel:relation:r1",
            "dataset": "test",
            "dtype": "relation",
            "schema_version": "0.9.0",
            "profile": "starintel-core",
            "profile_version": "0.9.1",
            "schema_revision": "0.9.0+fields.20260909.1",
            "version": 1,
            "content_hash": "canonical-hash",
            "date_added": "2026-09-18T00:00:00Z",
            "sources": [{
                "source_id": "src-1",
                "kind": "web",
                "url": "https://example.test/evidence",
                "credibility": 0.8,
                "reliability": 0.9,
                "content_hash": "abc",
            }],
            "evidence": [{
                "evidence_id": "ev-1",
                "source_id": "src-1",
                "role": "supporting",
                "claim": "Ada works for Analytical Engines.",
                "confidence": 0.95,
                "status": "verified",
            }],
            "provenance": {"actor": "fixture", "tool": "unit-test", "run_id": "run-1", "method": "test"},
            "data": {
                "subject": "starintel:person:ada",
                "predicate": "works_for",
                "object": "starintel:org:analytical-engines",
                "directed": True,
                "confidence": 0.95,
                "qualifiers": {"role": "mathematician"},
            },
        }

    def test_projection_contains_lossless_and_semantic_facts(self) -> None:
        rendered = render_projection([self.doc])
        self.assertIn("star_projection_manifest('0.9.1', '0.9.0'", rendered)
        self.assertIn("star_doc('starintel:relation:r1', 'relation', 'test', '0.9.0', 1, 'canonical-hash').", rendered)
        self.assertIn("star_projection_input_hash('starintel:relation:r1', 'sha256-canonical-json'", rendered)
        self.assertIn("star_json_value('starintel:relation:r1', '/data/predicate', 'string', 'works_for').", rendered)
        self.assertIn("star_relation('starintel:relation:r1', 'starintel:person:ada', 'works_for', 'starintel:org:analytical-engines'", rendered)
        self.assertIn("star_source('starintel:relation:r1', 'src-1'", rendered)
        self.assertIn("star_evidence('starintel:relation:r1', 'ev-1'", rendered)
        self.assertIn("star_ref('starintel:relation:r1', '/data/subject', 'starintel:person:ada').", rendered)

    def test_projection_is_deterministic(self) -> None:
        a = render_projection([self.doc])
        b = render_projection([json.loads(json.dumps(self.doc))])
        self.assertEqual(a, b)

    def test_json_array_and_ndjson_load(self) -> None:
        array = json.dumps([self.doc, {**self.doc, "_id": "starintel:relation:r2"}])
        self.assertEqual(2, len(load_documents(array)))
        ndjson = "\n".join(json.dumps(d) for d in [self.doc, {**self.doc, "_id": "starintel:relation:r2"}])
        self.assertEqual(2, len(load_documents(ndjson)))

    def test_manifest_can_follow_future_additive_release(self) -> None:
        manifest = ProjectionManifest.from_mapping({
            "release_version": "0.9.2",
            "schema_version": "0.9.0",
            "profile": "starintel-core",
            "profile_version": "0.9.2",
            "schema_revision": "0.9.0+fields.test",
            "expansion_content_hash": "future-hash",
        })
        rendered = render_projection([self.doc], manifest)
        self.assertIn("star_projection_manifest('0.9.2', '0.9.0', 'starintel-core', '0.9.2'", rendered)

    def test_prolog_atom_escapes_control_characters(self) -> None:
        rendered = prolog_atom("a\x00b\n\t\b\f'\\")
        self.assertNotIn("\x00", rendered)
        self.assertIn("\\x0\\", rendered)
        self.assertIn("\\n", rendered)

    def test_rejects_missing_identity(self) -> None:
        with self.assertRaises(ValueError):
            project_document({"dataset": "x", "dtype": "person"})


class ToolTests(unittest.TestCase):
    def test_catalog_is_machine_readable(self) -> None:
        names = {tool["name"] for tool in tool_catalog()}
        self.assertTrue({"kb_neighbors", "kb_path", "kb_explain", "kb_contradictions", "kb_route_reasoning", "kb_values", "kb_referrers", "kb_packet", "kb_relation_maturity", "kb_linkage_neighbors", "kb_fact_history"} <= names)

    def test_compile_bounded_goal(self) -> None:
        goal = compile_tool_call("kb_path", {"source": "starintel:person:a", "target": "starintel:org:b", "max_depth": 5})
        self.assertEqual("star_reasoning:tool_path('starintel:person:a', 'starintel:org:b', 5, Result)", goal)

    def test_compile_packet_goal_is_bounded(self) -> None:
        goal = compile_tool_call("kb_packet", {"id": "starintel:person:a", "max_items": 30})
        self.assertEqual("star_reasoning:tool_packet('starintel:person:a', 30, Result)", goal)
        with self.assertRaises(ValueError):
            compile_tool_call("kb_packet", {"id": "starintel:person:a", "max_items": 1000})

    def test_tool_does_not_accept_unknown_arguments(self) -> None:
        with self.assertRaises(ValueError):
            compile_tool_call("kb_document", {"id": "x", "goal": "shell(ls)"})

    def test_depth_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            compile_tool_call("kb_path", {"source": "a", "target": "b", "max_depth": 1000})


    def test_long_term_tools_are_bounded(self) -> None:
        goal = compile_tool_call(
            "kb_linkage_neighbors",
            {"id": "starintel:person:a", "min_level": 3, "max_items": 20},
        )
        self.assertEqual(
            "star_reasoning:tool_linkage_neighbors('starintel:person:a', 3, 20, Result)",
            goal,
        )
        maturity = compile_tool_call(
            "kb_relation_maturity",
            {"subject": "a", "predicate": "works_for", "object": "b"},
        )
        self.assertEqual(
            "star_reasoning:tool_relation_maturity('a', 'works_for', 'b', Result)",
            maturity,
        )
        history = compile_tool_call("kb_fact_history", {"id": "a", "max_items": 10})
        self.assertEqual("star_reasoning:tool_fact_history('a', 10, Result)", history)
        with self.assertRaises(ValueError):
            compile_tool_call("kb_linkage_neighbors", {"id": "a", "min_level": 6})
        with self.assertRaises(ValueError):
            compile_tool_call("kb_fact_history", {"id": "a", "max_items": 1000})


class CliTests(unittest.TestCase):
    def test_cli_project(self) -> None:
        document = {
            "_id": "starintel:person:test",
            "dataset": "test",
            "dtype": "person",
            "schema_version": "0.9.0",
            "version": 1,
            "sources": [],
            "evidence": [],
            "data": {"canonical_name": "Test Person"},
        }
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "doc.json"
            src.write_text(json.dumps(document), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "prolog-star-kb"), "project", str(src)],
                check=True,
                capture_output=True,
                text=True,
            )
        self.assertIn("star_doc('starintel:person:test'", result.stdout)


if __name__ == "__main__":
    unittest.main()
