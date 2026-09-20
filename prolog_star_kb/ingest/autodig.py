"""AutoDig -> StarIntel candidate importer.

Structured JSON/NDJSON claim bundles become candidate StarIntel relation documents that
keep AutoDig provenance (run/report id, generator identity, source locators, report
hash, confidence as reported). Imported claims are candidate/generated knowledge and
are never trusted canonical truth.

Markdown input is supported in archival mode only: one lossless document record with
source links and a content hash. No semantic relations are inferred from prose.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..projection import load_documents

AUTODIG_COLLECTOR = "autodig-import"
AUTODIG_TOOL = "prolog-star-kb ingest-autodig"
SCHEMA_VERSION = "0.9.0"
PROFILE = "starintel-core"
PROFILE_VERSION = "0.9.1"
SCHEMA_REVISION = "0.9.0+fields.20260909.1"

CLAIM_LOCATOR_KEYS = ("source_locators", "locators", "sources")
RUN_KEYS = ("run_id", "report_id")


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _nonempty_str(value: Any, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}: required field {field!r} must be a non-empty string")
    return value.strip()


def _run_identifier(claim: dict[str, Any], bundle: dict[str, Any], position: int) -> str:
    for source in (claim, bundle):
        for key in RUN_KEYS:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise ValueError(f"claim #{position}: missing report/run identifier (run_id or report_id)")


def _locators(claim: dict[str, Any], bundle: dict[str, Any], position: int) -> list[str]:
    values: list[str] = []
    for source in (claim, bundle):
        for key in CLAIM_LOCATOR_KEYS:
            raw = source.get(key)
            if isinstance(raw, str):
                values.append(raw)
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, str) and item.strip():
                        values.append(item.strip())
                    elif isinstance(item, dict):
                        url = item.get("url", item.get("locator", ""))
                        if isinstance(url, str) and url.strip():
                            values.append(url.strip())
    if not values:
        raise ValueError(f"claim #{position}: missing source locator(s) (source_locators)")
    return list(dict.fromkeys(values))


def _objects(value: Any, position: int) -> list[str]:
    raw = value if isinstance(value, list) else [value]
    objects = [_nonempty_str(item, "object", f"claim #{position}") for item in raw]
    return list(dict.fromkeys(objects))


def _source_id(locator: str) -> str:
    return f"autodig-locator:{_sha256_hex(locator)[:12]}"


def _claim_document(
    claim: dict[str, Any],
    bundle: dict[str, Any],
    position: int,
    dataset: str,
) -> dict[str, Any]:
    if not isinstance(claim, dict):
        raise ValueError(f"claim #{position} must be an object")
    run_id = _run_identifier(claim, bundle, position)
    subject = _nonempty_str(claim.get("subject"), "subject", f"claim #{position}")
    predicate = _nonempty_str(claim.get("predicate"), "predicate", f"claim #{position}")
    objects = _objects(claim.get("object"), position)
    locators = _locators(claim, bundle, position)

    model = claim.get("model") or claim.get("generator") or bundle.get("generated_by") or bundle.get("model")
    model = model if isinstance(model, str) and model.strip() else ""
    confidence = claim.get("confidence", bundle.get("confidence"))
    if confidence is not None and (
        isinstance(confidence, bool) or not isinstance(confidence, (int, float))
    ):
        raise ValueError(f"claim #{position}: 'confidence' must be a number when present")
    observed_at = claim.get("observed_at") or claim.get("timestamp") or claim.get("claimed_at")
    observed_at = observed_at if isinstance(observed_at, str) and observed_at else ""
    evidence_text = claim.get("evidence") or claim.get("evidence_text")
    evidence_text = evidence_text if isinstance(evidence_text, str) and evidence_text else ""
    qualifiers = claim.get("qualifiers") if isinstance(claim.get("qualifiers"), dict) else {}
    report_hash = claim.get("report_sha256") or bundle.get("report_sha256")
    report_hash = report_hash if isinstance(report_hash, str) and report_hash else ""

    claim_hash = _sha256_hex(
        json.dumps(
            {
                "run_id": run_id,
                "subject": subject,
                "predicate": predicate,
                "object": objects,
                "locators": locators,
                "evidence": evidence_text,
                "qualifiers": qualifiers,
                "confidence": confidence,
                "observed_at": observed_at,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    primary_source_id = _source_id(locators[0])
    document: dict[str, Any] = {
        "_id": f"starintel:candidate:autodig:{_sha256_hex(run_id)[:12]}:{claim_hash[:16]}",
        "dataset": dataset,
        "dtype": "relation",
        "schema_version": SCHEMA_VERSION,
        "profile": PROFILE,
        "profile_version": PROFILE_VERSION,
        "schema_revision": SCHEMA_REVISION,
        "version": 1,
        "candidate": True,
        "sources": [
            {
                "source_id": _source_id(locator),
                "kind": "autodig-report",
                "url": locator,
                **({"content_hash": report_hash} if report_hash else {}),
            }
            for locator in locators
        ],
        "evidence": [
            {
                "evidence_id": f"claim:{claim_hash[:16]}",
                "source_id": primary_source_id,
                "role": "reported-claim",
                **({"observation": evidence_text} if evidence_text else {}),
                **({"confidence": confidence} if confidence is not None else {}),
                "status": "candidate",
            }
        ],
        "provenance": {
            "collector": AUTODIG_COLLECTOR,
            "tool": AUTODIG_TOOL,
            **({"model": model} if model else {}),
            "run_id": run_id,
            "method": "structured-claim-import",
            "imported_from": locators[0],
            "transform": f"autodig-claim:{claim_hash}",
        },
        "data": {
            "subject": subject,
            "predicate": predicate,
            "object": objects if len(objects) > 1 else objects[0],
            "directed": True,
            "candidate": True,
            **({"confidence": confidence} if confidence is not None else {}),
            **({"observed_at": observed_at} if observed_at else {}),
            **({"qualifiers": qualifiers} if qualifiers else {}),
        },
    }
    if observed_at:
        document["date_added"] = observed_at
    corroborates = claim.get("corroborates", [])
    contradicts = claim.get("contradicts", [])
    if isinstance(corroborates, list) and corroborates:
        document["evidence"][0]["corroborates"] = [str(item) for item in corroborates]
    if isinstance(contradicts, list) and contradicts:
        document["evidence"][0]["contradicts"] = [str(item) for item in contradicts]
    return document


def _markdown_document(
    content: str,
    dataset: str,
    locators: list[str],
    run_id: str = "",
    model: str = "",
) -> dict[str, Any]:
    content_hash = _sha256_hex(content)
    title = ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            break
    sources = [
        {
            "source_id": _source_id(locator),
            "kind": "autodig-report",
            "url": locator,
            "content_hash": content_hash,
        }
        for locator in locators
    ]
    primary = _source_id(locators[0]) if locators else ""
    document: dict[str, Any] = {
        "_id": f"starintel:candidate:autodig:archive:{content_hash[:24]}",
        "dataset": dataset,
        "dtype": "document",
        "schema_version": SCHEMA_VERSION,
        "profile": PROFILE,
        "profile_version": PROFILE_VERSION,
        "schema_revision": SCHEMA_REVISION,
        "version": 1,
        "candidate": True,
        "sources": sources,
        "evidence": [
            {
                "evidence_id": f"report:{content_hash[:16]}",
                **({"source_id": primary} if primary else {}),
                "role": "archival-copy",
                "observation": (
                    "lossless archival storage of an AutoDig report; no semantic extraction performed"
                ),
                "status": "candidate",
            }
        ],
        "provenance": {
            "collector": AUTODIG_COLLECTOR,
            "tool": AUTODIG_TOOL,
            **({"model": model} if model else {}),
            **({"run_id": run_id} if run_id else {}),
            "method": "markdown-archival",
            "transform": f"autodig-report:{content_hash}",
        },
        "data": {
            **({"title": title} if title else {}),
            "media_type": "text/markdown",
            "content": content,
            "content_sha256": content_hash,
            **({"urls": locators} if locators else {}),
        },
    }
    return document


def _claims_from(input_objects: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(input_objects) == 1 and isinstance(input_objects[0].get("claims"), list):
        bundle = input_objects[0]
        return [claim for claim in bundle["claims"] if isinstance(claim, dict)], bundle
    return input_objects, {}


def ingest_autodig(
    text: str,
    *,
    name: str = "input",
    dataset: str = "autodig-import",
    report_format: str | None = None,
    extra_sources: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Convert AutoDig input into candidate StarIntel documents (deterministic)."""
    locators = [locator.strip() for locator in (extra_sources or []) if locator.strip()]
    lowered = name.lower()
    is_markdown = report_format == "markdown" or (
        report_format is None and (lowered.endswith(".md") or lowered.endswith(".markdown"))
    )
    if is_markdown:
        return [_markdown_document(text, dataset=dataset, locators=locators)]

    try:
        input_objects = load_documents(text)
    except (json.JSONDecodeError, ValueError) as exc:
        if report_format is None and text.lstrip().startswith("#"):
            raise ValueError(
                "input looks like Markdown; pass --format markdown for archival-only ingestion"
            ) from exc
        raise
    claims, bundle = _claims_from(input_objects)
    documents = [
        _claim_document(claim, bundle, position=position, dataset=dataset)
        for position, claim in enumerate(claims)
    ]
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for document in documents:
        if document["_id"] in seen:
            continue
        seen.add(document["_id"])
        unique.append(document)
    return unique


def ndjson_bytes(documents: list[dict[str, Any]]) -> bytes:
    if not documents:
        return b""
    body = "".join(
        json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for doc in documents
    )
    return body.encode("utf-8")
