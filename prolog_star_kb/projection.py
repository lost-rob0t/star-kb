from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable, Iterator


TEMPORAL_KEYS = frozenset({
    "date_added", "date_updated", "observed_at", "collected_at", "published_at",
    "created_at", "modified_at", "event_start", "event_end", "valid_from", "valid_to",
    "first_seen", "last_seen", "start_at", "end_at", "retrieved_at", "accessed_at",
    "verified_at", "last_reviewed_at", "review_due_at", "next_run_at", "completed_at",
    "started_at", "last_run_at", "resolved_at", "suppressed_until", "adopted_at",
    "repealed_at", "awarded_at", "acquired_at", "disposed_at", "transaction_date",
})


@dataclass(frozen=True)
class ProjectionManifest:
    release_version: str = "0.9.1"
    schema_version: str = "0.9.0"
    profile: str = "starintel-core"
    profile_version: str = "0.9.1"
    schema_revision: str = "0.9.0+fields.20260909.1"
    expansion_hash: str = "dd3a86ab5d789f746e9f12167f2c256316f0f35082ec659362a3b95f54f59cd8"


@dataclass(frozen=True)
class Fact:
    predicate: str
    args: tuple[Any, ...]

    def render(self) -> str:
        return f"{self.predicate}({', '.join(prolog_term(v) for v in self.args)})."


def prolog_atom(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f"'{escaped}'"


def prolog_term(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite numbers are not valid StarIntel JSON")
        return repr(value)
    if isinstance(value, str):
        return prolog_atom(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(prolog_term(v) for v in value) + "]"
    raise TypeError(f"unsupported Prolog value: {type(value).__name__}")


def pointer_escape(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def child_pointer(parent: str, part: str | int) -> str:
    encoded = pointer_escape(str(part))
    return f"/{encoded}" if parent == "" else f"{parent}/{encoded}"


def scalar_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    raise TypeError(f"not a JSON scalar: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def endpoint_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("_id", "id", "ref", "target", "value"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    return None


def iter_scalars(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key in sorted(value):
            yield from iter_scalars(value[key], child_pointer(path, key))
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_scalars(item, child_pointer(path, index))
        return
    yield path, value


def _walk(doc_id: str, value: Any, path: str = "") -> Iterator[Fact]:
    if isinstance(value, dict):
        yield Fact("star_json_object", (doc_id, path))
        for key in sorted(value):
            child = child_pointer(path, key)
            yield Fact("star_json_member", (doc_id, path, key, child))
            yield from _walk(doc_id, value[key], child)
        return
    if isinstance(value, list):
        yield Fact("star_json_array", (doc_id, path, len(value)))
        for index, item in enumerate(value):
            child = child_pointer(path, index)
            yield Fact("star_json_index", (doc_id, path, index, child))
            yield from _walk(doc_id, item, child)
        return
    yield Fact("star_json_value", (doc_id, path, scalar_type(value), value))


def _semantic_facts(document: dict[str, Any], manifest: ProjectionManifest) -> Iterator[Fact]:
    doc_id = document["_id"]
    data = document.get("data") if isinstance(document.get("data"), dict) else {}
    dtype = str(document.get("dtype", "unknown"))
    dataset = str(document.get("dataset", ""))
    schema_version = str(document.get("schema_version", manifest.schema_version))
    version = document.get("version", 0)

    yield Fact("star_doc", (doc_id, dtype, dataset, schema_version, version, content_hash(document)))
    yield Fact(
        "star_profile",
        (
            doc_id,
            str(document.get("profile", manifest.profile)),
            str(document.get("profile_version", manifest.profile_version)),
            str(document.get("schema_revision", manifest.schema_revision)),
            manifest.release_version,
        ),
    )

    for path, value in iter_scalars(document):
        key = path.rsplit("/", 1)[-1] if path else ""
        if key in TEMPORAL_KEYS and isinstance(value, str):
            yield Fact("star_time", (doc_id, key, value, path))
        if isinstance(value, str) and value.startswith("starintel:") and value != doc_id:
            yield Fact("star_ref", (doc_id, path, value))

    provenance = document.get("provenance")
    if isinstance(provenance, dict):
        yield Fact(
            "star_provenance",
            (
                doc_id,
                str(provenance.get("collector", "")),
                str(provenance.get("actor", provenance.get("agent", ""))),
                str(provenance.get("tool", "")),
                str(provenance.get("model", "")),
                str(provenance.get("run_id", "")),
                str(provenance.get("method", "")),
                str(provenance.get("imported_from", "")),
                str(provenance.get("transform", "")),
            ),
        )

    for source in document.get("sources", []) if isinstance(document.get("sources"), list) else []:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id", ""))
        if not source_id:
            continue
        locator = str(source.get("uri", source.get("url", source.get("locator", ""))))
        yield Fact(
            "star_source",
            (
                doc_id,
                source_id,
                str(source.get("kind", source.get("type", ""))),
                locator,
                source.get("credibility"),
                source.get("reliability"),
                source.get("content_hash", ""),
            ),
        )

    for evidence in document.get("evidence", []) if isinstance(document.get("evidence"), list) else []:
        if not isinstance(evidence, dict):
            continue
        evidence_id = str(evidence.get("evidence_id", ""))
        if not evidence_id:
            continue
        yield Fact(
            "star_evidence",
            (
                doc_id,
                evidence_id,
                str(evidence.get("source_id", "")),
                str(evidence.get("role", "")),
                str(evidence.get("claim", evidence.get("observation", ""))),
                evidence.get("confidence"),
                str(evidence.get("status", "")),
            ),
        )
        for contradicted in evidence.get("contradicts", []) if isinstance(evidence.get("contradicts"), list) else []:
            if isinstance(contradicted, str):
                yield Fact("star_evidence_contradicts", (doc_id, evidence_id, contradicted))
        for corroborated in evidence.get("corroborates", []) if isinstance(evidence.get("corroborates"), list) else []:
            if isinstance(corroborated, str):
                yield Fact("star_evidence_corroborates", (doc_id, evidence_id, corroborated))

    if dtype == "relation":
        subject = endpoint_value(data.get("subject")) or endpoint_value(data.get("source"))
        predicate = data.get("predicate") or data.get("predicate_id") or data.get("relation_type")
        raw_objects = data.get("object", data.get("target"))
        objects = raw_objects if isinstance(raw_objects, list) else [raw_objects]
        directed = bool(data.get("directed", True))
        negated = bool(data.get("negated", False))
        confidence = data.get("confidence", data.get("weight"))
        for raw_object in objects:
            obj = endpoint_value(raw_object)
            if subject and isinstance(predicate, str) and predicate and obj:
                yield Fact(
                    "star_relation",
                    (
                        doc_id,
                        subject,
                        predicate,
                        obj,
                        directed,
                        negated,
                        confidence,
                        data.get("start_at"),
                        data.get("end_at"),
                    ),
                )
                inverse = data.get("inverse_predicate")
                if isinstance(inverse, str) and inverse:
                    yield Fact("star_inverse_predicate", (doc_id, predicate, inverse))
        qualifiers = data.get("qualifiers")
        if isinstance(qualifiers, dict):
            for key in sorted(qualifiers):
                value = qualifiers[key]
                if value is None or isinstance(value, (str, bool, int, float)):
                    yield Fact("star_relation_qualifier", (doc_id, key, value))


def project_document(document: dict[str, Any], manifest: ProjectionManifest | None = None) -> list[Fact]:
    manifest = manifest or ProjectionManifest()
    if not isinstance(document, dict):
        raise TypeError("StarIntel document must be a JSON object")
    if not isinstance(document.get("_id"), str) or not document["_id"]:
        raise ValueError("StarIntel document requires a non-empty string _id")
    if not isinstance(document.get("dtype"), str) or not document["dtype"]:
        raise ValueError("StarIntel document requires a non-empty string dtype")
    if not isinstance(document.get("dataset"), str):
        raise ValueError("StarIntel document requires a string dataset")

    facts = list(_walk(document["_id"], document))
    facts.extend(_semantic_facts(document, manifest))
    return facts


def render_projection(documents: Iterable[dict[str, Any]], manifest: ProjectionManifest | None = None) -> str:
    manifest = manifest or ProjectionManifest()
    docs = list(documents)
    lines = [
        "% Generated by prolog-star-kb. Do not hand-edit.",
        "% Canonical source is StarIntel JSON; these are deterministic reasoning projections.",
        Fact(
            "star_projection_manifest",
            (
                manifest.release_version,
                manifest.schema_version,
                manifest.profile,
                manifest.profile_version,
                manifest.schema_revision,
                manifest.expansion_hash,
            ),
        ).render(),
    ]
    for document in sorted(docs, key=lambda d: str(d.get("_id", ""))):
        lines.append("")
        lines.append(f"% {document.get('_id', '<missing>')}")
        lines.extend(fact.render() for fact in project_document(document, manifest))
    return "\n".join(lines) + "\n"


def load_documents(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    if not stripped:
        return []
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        documents = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON/NDJSON at line {lineno}: {exc}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"NDJSON line {lineno} is not an object")
            documents.append(item)
        return documents
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return list(value)
    raise ValueError("input must be a StarIntel JSON object, an array of objects, or NDJSON")
