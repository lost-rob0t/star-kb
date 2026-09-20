from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prolog_star_kb.shapes import (
    DEFAULT_MAX_EXEMPLARS,
    mine_documents,
    render_shapes,
    report_json,
)
from prolog_star_kb.projection import load_documents

FIXTURE = ROOT / "tests" / "fixtures" / "shapes" / "corpus.ndjson"
GOLDEN = ROOT / "tests" / "fixtures" / "shapes" / "fixture-shapes.pl"


def fixture_docs() -> list[dict]:
    return load_documents(FIXTURE.read_text(encoding="utf-8"))


class ShapesMiningTests(unittest.TestCase):
    def test_output_is_deterministic(self) -> None:
        docs = fixture_docs()
        self.assertEqual(render_shapes(mine_documents(docs)), render_shapes(mine_documents(docs)))

    def test_output_is_order_insensitive(self) -> None:
        docs = fixture_docs()
        self.assertEqual(
            render_shapes(mine_documents(docs)),
            render_shapes(mine_documents(list(reversed(docs)))),
        )

    def test_dtype_counts(self) -> None:
        report = mine_documents(fixture_docs())
        self.assertEqual(report.doc_count, 6)
        self.assertEqual(report.dtype_counts["person"], 2)
        self.assertEqual(report.dtype_counts["org"], 1)
        self.assertEqual(report.dtype_counts["relation"], 3)
        self.assertIn("star_dtype_count('person', 2).", render_shapes(report))

    def test_field_shape_counts_and_types(self) -> None:
        report = mine_documents(fixture_docs())
        rendered = render_shapes(report)
        # canonical_name appears in both person docs and the org doc
        self.assertIn("star_field_shape('person', '/data/canonical_name', 'string', 2, 2).", rendered)
        self.assertIn("star_field_shape('org', '/data/canonical_name', 'string', 1, 1).", rendered)
        # sources/#/uri covers all three source entries across person/org docs plus relation
        self.assertIn("star_field_cardinality('person', '/sources/#/uri', 1, 2).", rendered)

    def test_relation_shapes_include_endpoint_domains(self) -> None:
        rendered = render_shapes(mine_documents(fixture_docs()))
        self.assertIn(
            "star_relation_shape('works_for', 'person', 'org', 1).",
            rendered,
        )
        self.assertIn(
            "star_relation_shape('member_of', 'person', 'org', 1).",
            rendered,
        )
        self.assertIn(
            "star_relation_shape('enumerated_from_area_code', 'org', 'unresolved', 1).",
            rendered,
        )

    def test_qualifier_shapes(self) -> None:
        rendered = render_shapes(mine_documents(fixture_docs()))
        self.assertIn("star_qualifier_shape('works_for', 'npa', 'integer', 1).", rendered)
        self.assertIn("star_qualifier_shape('works_for', 'role', 'string', 1).", rendered)

    def test_temporal_and_ref_shapes(self) -> None:
        rendered = render_shapes(mine_documents(fixture_docs()))
        self.assertIn("star_temporal_key('person', 'posted_at', 1).", rendered)
        self.assertIn("star_temporal_key('person', 'date_added', 2).", rendered)
        self.assertIn("star_ref_shape('person', 'org', 2).", rendered)

    def test_exemplars_are_bounded(self) -> None:
        docs = fixture_docs()
        report = mine_documents(docs, max_exemplars=1)
        rendered = render_shapes(report, max_exemplars=1)
        per_shape: dict[tuple[str, str], int] = {}
        for line in rendered.splitlines():
            if not line.startswith("star_field_exemplar("):
                continue
            args = line[len("star_field_exemplar(") :].rsplit(").", 1)[0]
            key = tuple(part.strip().strip("'") for part in args.split(",", 2)[:2])
            per_shape[key] = per_shape.get(key, 0) + 1
        self.assertTrue(per_shape)
        self.assertTrue(all(count <= 1 for count in per_shape.values()))
        self.assertIn(
            "star_field_exemplar('person', '/data/canonical_name', 'starintel:person:ada').",
            rendered,
        )

    def test_corpus_hash_is_stable_and_order_insensitive(self) -> None:
        docs = fixture_docs()
        self.assertEqual(
            mine_documents(docs).corpus_hash(),
            mine_documents(list(reversed(docs))).corpus_hash(),
        )

    def test_json_sidecar_schema(self) -> None:
        payload = report_json(mine_documents(fixture_docs()))
        self.assertEqual(payload["schema"], "starintel.shapes.v1")
        self.assertEqual(payload["doc_count"], 6)
        self.assertEqual(payload["dtype_counts"]["relation"], 3)
        self.assertEqual(
            payload["fields"]["person"]["/data/canonical_name"]["types"], {"string": 2}
        )
        self.assertEqual(
            payload["relation_shapes"][0]["predicate"], "enumerated_from_area_code"
        )

    def test_no_timestamps_in_output(self) -> None:
        rendered = render_shapes(mine_documents(fixture_docs()))
        self.assertNotIn("2026-09-19", rendered.split("star_shape_manifest", 1)[1])


class ShapesGoldenAndCliTests(unittest.TestCase):
    def test_golden_fixture_output_matches(self) -> None:
        rendered = render_shapes(mine_documents(fixture_docs()))
        golden = GOLDEN.read_text(encoding="utf-8")
        self.assertEqual(rendered, golden)

    def test_cli_mine_shapes_matches_golden(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "shapes.pl"
            sidecar = Path(td) / "shapes.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "prolog-star-kb"),
                    "mine-shapes",
                    str(FIXTURE),
                    "-o",
                    str(out),
                    "--json",
                    str(sidecar),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(out.read_text(encoding="utf-8"), GOLDEN.read_text(encoding="utf-8"))
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(payload["miner_version"], "1")
            self.assertEqual(payload["doc_count"], 6)


if __name__ == "__main__":
    unittest.main()
