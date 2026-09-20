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
    "posted_at", "generated_at", "last_validated_at", "date", "filing_date",
    "award_date",
})


@dataclass(frozen=True)
class ProjectionManifest:
    release_version: str = "0.9.1"
    schema_version: str = "0.9.0"
    profile: str = "starintel-core"
    profile_version: str = "0.9.1"
    schema_revision: str = "0.9.0+fields.20260909.1"
    expansion_hash: str = "dd3a86ab5d789f746e9f12167f2c256316f0f35082ec659362a3b95f54f59cd8"

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ProjectionManifest":
        defaults = cls()
        return cls(
            release_version=str(value.get("release_version", defaults.release_version)),
            schema_version=str(value.get("schema_version", defaults.schema_version)),
            profile=str(value.get("profile", defaults.profile)),
            profile_version=str(value.get("profile_version", defaults.profile_version)),
            schema_revision=str(value.get("schema_revision", defaults.schema_revision)),
            expansion_hash=str(value.get("expansion_content_hash", value.get("expansion_hash", defaults.expansion_hash))),
        )


@dataclass(frozen=True)
class Fact:
    predicate: str
    args: tuple[Any, ...]

    def render(self) -> str:
        return f"{self.predicate}({', '.join(prolog_term(v) for v in self.args)})."


def prolog_atom(value: str) -> str:
    escaped: list[str] = []
    for char in value:
        code = ord(char)
        if char == "\\":
            escaped.append("\\\\")
        elif char == "'":
            escaped.append("\\'")
        elif char == "\n":
            escaped.append("\\n")
        elif char == "\r":
            escaped.append("\\r")
        elif char == "\t":
            escaped.append("\\t")
        elif char == "\b":
            escaped.append("\\b")
        elif char == "\f":
            escaped.append("\\f")
        elif code < 0x20 or code == 0x7F:
            escaped.append(f"\\x{code:x}\\")
        else:
            escaped.append(char)
    return "'" + "".join(escaped) + "'"


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
    if isinstance(value, list):
        return "[" + ", ".join(prolog_term(v) for v in value) + "]"
    if isinstance(value, tuple):
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
        for key in ("_id", "id", "ref", "target", "value", "entity_id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    return None


def string_arg(value: Any, default: str = "") -> str:
    """Coerce a JSON value into a safe Prolog atom argument without data loss.

    Strings pass through unchanged; None becomes the default; other scalars use
    str(); containers are preserved deterministically as canonical JSON text.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return default
    if isinstance(value, (bool, int, float)):
        return str(value)
    return canonical_json(value)


def term_arg(value: Any) -> Any:
    """Keep scalar Prolog terms as-is; render containers as canonical JSON text."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return canonical_json(value)


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

    declared_content_hash = document.get("content_hash")
    if not isinstance(declared_content_hash, str):
        declared_content_hash = ""
    yield Fact("star_doc", (doc_id, dtype, dataset, schema_version, version, declared_content_hash))
    yield Fact("star_projection_input_hash", (doc_id, "sha256-canonical-json", content_hash(document)))
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
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            source_id = "src:" + content_hash(source)[:16]
        locator = str(source.get("uri", source.get("url", source.get("locator", ""))))
        yield Fact(
            "star_source",
            (
                doc_id,
                source_id,
                string_arg(source.get("kind", source.get("type", ""))),
                string_arg(locator),
                term_arg(source.get("credibility")),
                term_arg(source.get("reliability")),
                string_arg(source.get("content_hash", "")),
            ),
        )

    for evidence in document.get("evidence", []) if isinstance(document.get("evidence"), list) else []:
        if not isinstance(evidence, dict):
            continue
        evidence_id = evidence.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            evidence_id = "ev:" + content_hash(evidence)[:16]
        yield Fact(
            "star_evidence",
            (
                doc_id,
                evidence_id,
                string_arg(evidence.get("source_id", "")),
                string_arg(evidence.get("role", "")),
                string_arg(evidence.get("claim", evidence.get("observation", ""))),
                term_arg(evidence.get("confidence")),
                string_arg(evidence.get("status", "")),
            ),
        )
        for locator_key in ("source_url", "locator", "url", "uri"):
            locator = evidence.get(locator_key)
            if isinstance(locator, str) and locator:
                yield Fact("star_evidence_locator", (doc_id, evidence_id, locator))
                break
        for contradicted in evidence.get("contradicts", []) if isinstance(evidence.get("contradicts"), list) else []:
            if isinstance(contradicted, str):
                yield Fact("star_evidence_contradicts", (doc_id, evidence_id, contradicted))
        for corroborated in evidence.get("corroborates", []) if isinstance(evidence.get("corroborates"), list) else []:
            if isinstance(corroborated, str):
                yield Fact("star_evidence_corroborates", (doc_id, evidence_id, corroborated))

    if dtype == "relation":
        subject_raw = data.get("subject")
        object_raw = data.get("object", data.get("target"))
        subject = endpoint_value(subject_raw) or endpoint_value(data.get("source"))
        for side, raw in (("subject", subject_raw), ("object", object_raw)):
            if endpoint_value(raw) is not None or not isinstance(raw, dict):
                continue
            external_id = raw.get("external_id")
            label = raw.get("label")
            if isinstance(external_id, str) and external_id or isinstance(label, str) and label:
                yield Fact(
                    "star_relation_unresolved_endpoint",
                    (doc_id, side, string_arg(external_id), string_arg(label)),
                )
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


PROJECTION_PREDICATES = (
    "star_json_object/2",
    "star_json_array/3",
    "star_json_member/4",
    "star_json_index/4",
    "star_json_value/4",
    "star_doc/6",
    "star_projection_input_hash/3",
    "star_profile/5",
    "star_ref/3",
    "star_time/4",
    "star_provenance/9",
    "star_source/7",
    "star_evidence/7",
    "star_evidence_locator/3",
    "star_evidence_contradicts/3",
    "star_evidence_corroborates/3",
    "star_relation/9",
    "star_relation_unresolved_endpoint/4",
    "star_inverse_predicate/3",
    "star_relation_qualifier/3",
)


def projection_header(manifest: ProjectionManifest) -> list[str]:
    return [
        "% Generated by prolog-star-kb. Do not hand-edit.",
        "% Canonical source is StarIntel JSON; these are deterministic reasoning projections.",
        "% Facts are grouped per document, so predicate clauses are intentionally discontiguous.",
        ":- discontiguous "
        + ", ".join(PROJECTION_PREDICATES)
        + ".",
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


def iter_document_lines(document: dict[str, Any], manifest: ProjectionManifest | None = None) -> Iterator[str]:
    manifest = manifest or ProjectionManifest()
    yield ""
    yield f"% {document.get('_id', '<missing>')}"
    yield from (fact.render() for fact in project_document(document, manifest))


def check_unique_ids(documents: Iterable[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for document in documents:
        doc_id = str(document.get("_id", ""))
        if doc_id and doc_id in seen:
            raise ValueError(f"duplicate _id in projection input: {doc_id}")
        seen.add(doc_id)


def render_projection(documents: Iterable[dict[str, Any]], manifest: ProjectionManifest | None = None) -> str:
    manifest = manifest or ProjectionManifest()
    docs = list(documents)
    check_unique_ids(docs)
    lines = list(projection_header(manifest))
    for document in sorted(docs, key=lambda d: str(d.get("_id", ""))):
        lines.extend(iter_document_lines(document, manifest))
    return "\n".join(lines) + "\n"


def stream_projection_lines(
    lines: Iterable[str],
    manifest: ProjectionManifest | None = None,
) -> Iterator[str]:
    """Stream NDJSON text into projection lines without buffering the corpus.

    Emits documents in input order; feed sorted input for canonical ordering.
    Fails closed on invalid JSON lines and duplicate document ids, mirroring
    render_projection's guarantees for whole-corpus jobs.
    """
    manifest = manifest or ProjectionManifest()
    yield from projection_header(manifest)
    seen: set[str] = set()
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            document = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid NDJSON at line {lineno}: {exc}") from exc
        if not isinstance(document, dict):
            raise ValueError(f"NDJSON line {lineno} is not an object")
        doc_id = str(document.get("_id", ""))
        if doc_id and doc_id in seen:
            raise ValueError(f"duplicate _id in projection input: {doc_id}")
        seen.add(doc_id)
        yield from iter_document_lines(document, manifest)


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
