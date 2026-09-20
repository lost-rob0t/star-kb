"""Deterministic fact-shape / ontology mining over StarIntel JSON corpora.

The miner observes which field shapes, relation shapes, qualifiers, temporal
keys, and cross-dtype references actually occur in a corpus and emits them as
versioned Prolog facts (plus an optional JSON sidecar). Output is candidate
ontology evidence derived from canonical StarIntel JSON; it is rebuildable,
order-insensitive, and contains no timestamps so identical corpora produce
byte-identical output regardless of document order.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from .projection import (
    TEMPORAL_KEYS,
    Fact,
    endpoint_value,
    scalar_type,
)

SHAPES_MINER_VERSION = "1"
ARRAY_SEGMENT = "#"
DEFAULT_MAX_EXEMPLARS = 3


@dataclass
class FieldShape:
    """Bounded per-(dtype, path-shape) statistics.

    Memory is O(1) in corpus size: exemplars keep only the lexicographically
    smallest ids ever observed, and per-document cardinality folds
    incrementally instead of retaining per-document counters.
    """

    types: Counter[str] = field(default_factory=Counter)
    doc_count: int = 0
    min_per_doc: int = 0
    max_per_doc: int = 0
    exemplars: list[str] = field(default_factory=list)
    _current_occurrences: int = -1

    def begin_document(self) -> None:
        self._current_occurrences = 0

    def observe(self, doc_id: str, value_type: str, exemplar_bound: int) -> None:
        self.types[value_type] += 1
        self._current_occurrences += 1
        self._offer_exemplar(doc_id, exemplar_bound)

    def _offer_exemplar(self, doc_id: str, bound: int) -> None:
        if bound <= 0 or not doc_id:
            return
        if doc_id in self.exemplars:
            return
        if len(self.exemplars) < bound:
            self.exemplars.append(doc_id)
            self.exemplars.sort()
            return
        if doc_id < self.exemplars[-1]:
            self.exemplars[-1] = doc_id
            self.exemplars.sort()

    def end_document(self) -> None:
        if self._current_occurrences < 0:
            return
        if self.doc_count == 0:
            self.min_per_doc = self.max_per_doc = self._current_occurrences
        else:
            self.min_per_doc = min(self.min_per_doc, self._current_occurrences)
            self.max_per_doc = max(self.max_per_doc, self._current_occurrences)
        self.doc_count += 1
        self._current_occurrences = -1


@dataclass
class ShapeReport:
    doc_count: int = 0
    dtype_counts: Counter[str] = field(default_factory=Counter)
    fields: dict[tuple[str, str], FieldShape] = field(default_factory=dict)
    relation_shapes: Counter[tuple[str, str, str]] = field(default_factory=Counter)
    qualifier_shapes: Counter[tuple[str, str, str]] = field(default_factory=Counter)
    temporal_keys: Counter[tuple[str, str]] = field(default_factory=Counter)
    ref_shapes: Counter[tuple[str, str]] = field(default_factory=Counter)
    doc_hashes: list[str] = field(default_factory=list)

    def corpus_hash(self) -> str:
        joined = "\n".join(sorted(self.doc_hashes))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def child_shape(parent: str, part: str) -> str:
    encoded = part.replace("~", "~0").replace("/", "~1")
    return f"/{encoded}" if parent == "" else f"{parent}/{encoded}"


def array_shape(parent: str) -> str:
    return f"{parent}/{ARRAY_SEGMENT}"


def ref_target_dtype(value: str) -> str:
    dtype = value[len("starintel:"):].split(":", 1)[0]
    return dtype or "unknown"


def endpoint_shape(raw: Any) -> str:
    endpoint = endpoint_value(raw)
    if endpoint is None:
        return "unresolved" if isinstance(raw, dict) else "literal"
    if endpoint.startswith("starintel:"):
        return ref_target_dtype(endpoint)
    return "external"


class ShapesMiner:
    """Aggregates corpus shape observations deterministically."""

    def __init__(self, max_exemplars: int = DEFAULT_MAX_EXEMPLARS) -> None:
        self.max_exemplars = max_exemplars
        self.report = ShapeReport()
        self._touched: list[FieldShape] = []

    def observe(self, document: dict[str, Any]) -> None:
        if not isinstance(document, dict):
            raise TypeError("StarIntel document must be a JSON object")
        doc_id = str(document.get("_id", ""))
        dtype = str(document.get("dtype", "unknown"))
        report = self.report
        report.doc_count += 1
        report.dtype_counts[dtype] += 1
        report.doc_hashes.append(
            hashlib.sha256(
                json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        )
        self._touched = []
        self._walk(doc_id, dtype, document, "")
        for stats in self._touched:
            stats.end_document()
        if dtype == "relation":
            self._observe_relation(document)

    def _field(self, dtype: str, shape: str) -> FieldShape:
        key = (dtype, shape)
        stats = self.report.fields.get(key)
        if stats is None:
            stats = FieldShape()
            self.report.fields[key] = stats
        return stats

    def _walk(self, doc_id: str, dtype: str, value: Any, shape: str) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                self._walk(doc_id, dtype, value[key], child_shape(shape, key))
            return
        if isinstance(value, list):
            child = array_shape(shape)
            for item in value:
                self._walk(doc_id, dtype, item, child)
            return
        stats = self._field(dtype, shape)
        if stats._current_occurrences < 0:
            stats.begin_document()
            self._touched.append(stats)
        stats.observe(doc_id, scalar_type(value), self.max_exemplars)
        key = shape.rsplit("/", 1)[-1] if shape else ""
        if key in TEMPORAL_KEYS and isinstance(value, str):
            self.report.temporal_keys[(dtype, key)] += 1
        if shape != "/_id" and isinstance(value, str) and value.startswith("starintel:"):
            self.report.ref_shapes[(dtype, ref_target_dtype(value))] += 1

    def _observe_relation(self, document: dict[str, Any]) -> None:
        data = document.get("data") if isinstance(document.get("data"), dict) else {}
        predicate = data.get("predicate") or data.get("predicate_id") or data.get("relation_type")
        if not isinstance(predicate, str) or not predicate:
            return
        subject_raw = data.get("subject")
        subject = endpoint_value(subject_raw) or endpoint_value(data.get("source"))
        object_raw = data.get("object", data.get("target"))
        objects = object_raw if isinstance(object_raw, list) else [object_raw]
        subject_shape = endpoint_shape(
            subject_raw if endpoint_value(subject_raw) is not None else data.get("source")
        )
        for raw_object in objects:
            if subject is None and endpoint_value(raw_object) is None:
                continue
            self.report.relation_shapes[(predicate, subject_shape, endpoint_shape(raw_object))] += 1
        qualifiers = data.get("qualifiers")
        if isinstance(qualifiers, dict):
            for key in sorted(qualifiers):
                value = qualifiers[key]
                if value is None or isinstance(value, (str, bool, int, float)):
                    self.report.qualifier_shapes[(predicate, key, scalar_type(value))] += 1


def mine_documents(
    documents: Iterable[dict[str, Any]],
    max_exemplars: int = DEFAULT_MAX_EXEMPLARS,
) -> ShapeReport:
    miner = ShapesMiner(max_exemplars=max_exemplars)
    for document in documents:
        miner.observe(document)
    return miner.report


def report_facts(
    report: ShapeReport,
    max_exemplars: int = DEFAULT_MAX_EXEMPLARS,
) -> Iterator[Fact]:
    yield Fact(
        "star_shape_manifest",
        (SHAPES_MINER_VERSION, report.corpus_hash(), report.doc_count, len(report.dtype_counts)),
    )
    for dtype in sorted(report.dtype_counts):
        yield Fact("star_dtype_count", (dtype, report.dtype_counts[dtype]))
    for (dtype, shape) in sorted(report.fields):
        stats = report.fields[(dtype, shape)]
        for value_type in sorted(stats.types):
            yield Fact(
                "star_field_shape",
                (dtype, shape, value_type, stats.types[value_type], stats.doc_count),
            )
        yield Fact("star_field_cardinality", (dtype, shape, stats.min_per_doc, stats.max_per_doc))
        for exemplar in stats.exemplars[:max_exemplars]:
            yield Fact("star_field_exemplar", (dtype, shape, exemplar))
    for (predicate, subject_shape, object_shape) in sorted(report.relation_shapes):
        count = report.relation_shapes[(predicate, subject_shape, object_shape)]
        yield Fact("star_relation_shape", (predicate, subject_shape, object_shape, count))
    for (predicate, key, value_type) in sorted(report.qualifier_shapes):
        count = report.qualifier_shapes[(predicate, key, value_type)]
        yield Fact("star_qualifier_shape", (predicate, key, value_type, count))
    for (dtype, key) in sorted(report.temporal_keys):
        yield Fact("star_temporal_key", (dtype, key, report.temporal_keys[(dtype, key)]))
    for (dtype, target) in sorted(report.ref_shapes):
        yield Fact("star_ref_shape", (dtype, target, report.ref_shapes[(dtype, target)]))


def render_shapes(report: ShapeReport, max_exemplars: int = DEFAULT_MAX_EXEMPLARS) -> str:
    lines = [
        "% Generated by prolog-star-kb mine-shapes. Do not hand-edit.",
        "% Candidate fact-shape/ontology evidence mined from canonical StarIntel JSON;",
        "% deterministic rebuildable output, not trusted truth. No timestamps are recorded.",
        f"% Miner version {SHAPES_MINER_VERSION} over {report.doc_count} documents.",
    ]
    lines.extend(fact.render() for fact in report_facts(report, max_exemplars))
    return "\n".join(lines) + "\n"


def report_json(report: ShapeReport, max_exemplars: int = DEFAULT_MAX_EXEMPLARS) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for (dtype, shape) in sorted(report.fields):
        stats = report.fields[(dtype, shape)]
        entry = {
            "types": {value_type: stats.types[value_type] for value_type in sorted(stats.types)},
            "doc_count": stats.doc_count,
            "cardinality": {"min": stats.min_per_doc, "max": stats.max_per_doc},
            "exemplars": stats.exemplars[:max_exemplars],
        }
        fields.setdefault(dtype, {})[shape] = entry
    return {
        "schema": "starintel.shapes.v1",
        "miner_version": SHAPES_MINER_VERSION,
        "corpus_hash": report.corpus_hash(),
        "doc_count": report.doc_count,
        "dtype_counts": dict(sorted(report.dtype_counts.items())),
        "fields": fields,
        "relation_shapes": [
            {"predicate": predicate, "subject": subject, "object": obj, "count": count}
            for (predicate, subject, obj), count in sorted(report.relation_shapes.items())
        ],
        "qualifier_shapes": [
            {"predicate": predicate, "key": key, "value_type": value_type, "count": count}
            for (predicate, key, value_type), count in sorted(report.qualifier_shapes.items())
        ],
        "temporal_keys": [
            {"dtype": dtype, "key": key, "count": count}
            for (dtype, key), count in sorted(report.temporal_keys.items())
        ],
        "ref_shapes": [
            {"dtype": dtype, "target_dtype": target, "count": count}
            for (dtype, target), count in sorted(report.ref_shapes.items())
        ],
    }
