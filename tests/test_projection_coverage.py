from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prolog_star_kb.projection import (
    ProjectionManifest,
    load_documents,
    render_projection,
    stream_projection_lines,
)


def relation_doc(doc_id: str, data: dict, **extra) -> dict:
    document = {
        "_id": doc_id,
        "dataset": "coverage",
        "dtype": "relation",
        "schema_version": "0.9.0",
        "version": 1,
        "sources": [],
        "evidence": [],
        "data": data,
    }
    document.update(extra)
    return document


class EndpointCoverageTests(unittest.TestCase):
    def test_entity_id_object_endpoint_projects(self) -> None:
        doc = relation_doc(
            "starintel:relation:r-entity",
            {
                "subject": "starintel:person:ada",
                "predicate": "member_of",
                "object": {"dtype": "org", "entity_id": "starintel:org:ae", "unresolved": True},
            },
        )
        rendered = render_projection([doc])
        self.assertIn(
            "star_relation('starintel:relation:r-entity', 'starintel:person:ada', 'member_of', 'starintel:org:ae'",
            rendered,
        )

    def test_unresolved_endpoint_is_captured_without_fabricating_identity(self) -> None:
        doc = relation_doc(
            "starintel:relation:r-unresolved",
            {
                "subject": "starintel:org:ae",
                "predicate": "enumerated_from_area_code",
                "object": {"external_id": "NPA:706", "label": "NPA 706 region", "unresolved": True},
            },
        )
        rendered = render_projection([doc])
        self.assertNotIn("star_relation('starintel:relation:r-unresolved'", rendered)
        self.assertIn(
            "star_relation_unresolved_endpoint('starintel:relation:r-unresolved', 'object', 'NPA:706', 'NPA 706 region').",
            rendered,
        )
        # the observed raw endpoint stays losslessly reachable via path facts
        self.assertIn("star_json_value('starintel:relation:r-unresolved', '/data/object/external_id', 'string', 'NPA:706').", rendered)

    def test_dict_endpoint_with_id_key_still_projects(self) -> None:
        doc = relation_doc(
            "starintel:relation:r-dict",
            {
                "subject": {"dtype": "person", "id": "starintel:person:ada", "role": "subject"},
                "predicate": "works_for",
                "object": "starintel:org:ae",
            },
        )
        rendered = render_projection([doc])
        self.assertIn(
            "star_relation('starintel:relation:r-dict', 'starintel:person:ada', 'works_for', 'starintel:org:ae'",
            rendered,
        )

    def test_multi_object_list_projects_all_edges(self) -> None:
        doc = relation_doc(
            "starintel:relation:r-multi",
            {
                "subject": "starintel:org:emh",
                "predicate": "used",
                "object": ["starintel:org:a-inc", "starintel:org:b-inc"],
            },
        )
        rendered = render_projection([doc])
        self.assertIn("'starintel:org:emh', 'used', 'starintel:org:a-inc'", rendered)
        self.assertIn("'starintel:org:emh', 'used', 'starintel:org:b-inc'", rendered)


class EvidenceAndSourceCoverageTests(unittest.TestCase):
    def test_evidence_without_evidence_id_is_indexed_with_stable_synthetic_key(self) -> None:
        doc = relation_doc(
            "starintel:relation:r-ev",
            {"subject": "a", "predicate": "p", "object": "b"},
            evidence=[{
                "role": "supporting",
                "observation": "Observed directly.",
                "confidence": 0.9,
                "source_url": "https://example.test/x",
                "status": "verified",
            }],
        )
        a = render_projection([doc])
        b = render_projection([json.loads(json.dumps(doc))])
        self.assertIn("ev:", a)
        self.assertEqual(a, b)  # synthetic key is deterministic
        self.assertIn("'starintel:relation:r-ev', 'ev:", a)
        self.assertIn("star_evidence_locator('starintel:relation:r-ev', 'ev:", a)
        self.assertIn("'https://example.test/x').", a)

    def test_evidence_with_explicit_id_keeps_it(self) -> None:
        doc = relation_doc(
            "starintel:relation:r-ev2",
            {"subject": "a", "predicate": "p", "object": "b"},
            evidence=[{"evidence_id": "ev-9", "source_id": "s-1", "role": "supporting",
                       "claim": "c", "confidence": 0.5, "status": "verified"}],
        )
        rendered = render_projection([doc])
        self.assertIn("star_evidence('starintel:relation:r-ev2', 'ev-9', 's-1'", rendered)

    def test_source_without_source_id_is_indexed_with_stable_synthetic_key(self) -> None:
        doc = relation_doc(
            "starintel:relation:r-src",
            {"subject": "a", "predicate": "p", "object": "b"},
            sources=[{"kind": "web", "uri": "https://example.test/anon", "credibility": 0.5}],
        )
        rendered = render_projection([doc])
        self.assertIn("src:", rendered)
        self.assertIn("'https://example.test/anon'", rendered)

    def test_container_valued_source_fields_do_not_crash(self) -> None:
        doc = relation_doc(
            "starintel:relation:r-cv",
            {"subject": "a", "predicate": "p", "object": "b"},
            sources=[{"source_id": "s-2", "kind": "web", "uri": "https://example.test/x",
                      "credibility": {"memo": 0.5}, "content_hash": ["h1"]}],
        )
        rendered = render_projection([doc])
        self.assertIn("star_source('starintel:relation:r-cv', 's-2'", rendered)
        self.assertIn("'{\"memo\":0.5}'", rendered)
        self.assertIn("'[\"h1\"]'", rendered)


class TemporalAndIntegrityTests(unittest.TestCase):
    def test_additional_temporal_keys_are_indexed(self) -> None:
        doc = relation_doc(
            "starintel:relation:r-time",
            {"subject": "a", "predicate": "p", "object": "b"},
            posted_at="2026-09-01T00:00:00Z",
            generated_at="2026-09-02T00:00:00Z",
        )
        rendered = render_projection([doc])
        self.assertIn("star_time('starintel:relation:r-time', 'posted_at', '2026-09-01T00:00:00Z', '/posted_at').", rendered)
        self.assertIn("star_time('starintel:relation:r-time', 'generated_at', '2026-09-02T00:00:00Z', '/generated_at').", rendered)

    def test_duplicate_ids_fail_closed(self) -> None:
        doc = relation_doc("starintel:relation:r-dup", {"subject": "a", "predicate": "p", "object": "b"})
        with self.assertRaises(ValueError):
            render_projection([doc, dict(doc)])
        ndjson = "\n".join(json.dumps(d) for d in [doc, dict(doc)])
        with self.assertRaises(ValueError):
            list(stream_projection_lines(ndjson.splitlines()))


class StreamingTests(unittest.TestCase):
    def test_streaming_matches_rendered_projection_for_sorted_input(self) -> None:
        docs = [
            relation_doc("starintel:relation:r-a", {"subject": "a", "predicate": "p", "object": "b",
                                                    "qualifiers": {"k": "v"}}),
            relation_doc("starintel:relation:r-b", {"subject": "x", "predicate": "q", "object": "y"}),
        ]
        ndjson = "\n".join(json.dumps(d) for d in sorted(docs, key=lambda d: d["_id"]))
        streamed = "\n".join(stream_projection_lines(ndjson.splitlines())) + "\n"
        self.assertEqual(streamed, render_projection(docs, ProjectionManifest()))

    def test_streaming_rejects_invalid_lines(self) -> None:
        with self.assertRaises(ValueError):
            list(stream_projection_lines(["{not json"]))

    def test_cli_project_streams_ndjson_file(self) -> None:
        docs = [
            relation_doc("starintel:relation:r-cli1", {"subject": "a", "predicate": "p", "object": "b"}),
            relation_doc("starintel:relation:r-cli2", {"subject": "x", "predicate": "q", "object": "y"}),
        ]
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "corpus.ndjson"
            src.write_text("\n".join(json.dumps(d) for d in docs) + "\n", encoding="utf-8")
            out = Path(td) / "corpus.pl"
            subprocess.run(
                [sys.executable, str(ROOT / "tools" / "prolog-star-kb"), "project", str(src), "-o", str(out), "--stream"],
                check=True,
                capture_output=True,
                text=True,
            )
            streamed = out.read_text(encoding="utf-8")
        self.assertEqual(streamed, render_projection(docs))


if __name__ == "__main__":
    unittest.main()
