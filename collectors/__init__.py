"""Star KB collector package: registry-driven, two-layer deterministic collection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import (
    ALLOWED_URL_SCHEMES,
    BaseCollector,
    RAW_ENVELOPE_KEYS,
    SourceSpec,
    build_raw_envelope,
    candidate_document,
    canonical_json,
    content_hash,
    fetch_url,
    load_registry,
    ndjson_bytes,
    parse_registry,
    parse_source_entry,
    sha256_bytes,
)
from .http_json import HttpJsonCollector
from .rss_atom import RssAtomCollector

COLLECTORS: dict[str, type[BaseCollector]] = {
    "http_json": HttpJsonCollector,
    "rss_atom": RssAtomCollector,
}


def run_source(
    registry_path: str | Path,
    source_id: str,
    artifact_dir: str | Path,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Collect one registry source into raw + normalized NDJSON under artifact_dir.

    artifact_dir is runtime state (a temp directory in CI): collected data is uploaded
    as workflow artifacts and never committed to the repository.
    """
    specs = {spec.source_id: spec for spec in load_registry(registry_path)}
    spec = specs.get(source_id)
    if spec is None:
        raise ValueError(f"unknown source id {source_id!r} in {registry_path}")
    collector = COLLECTORS[spec.type]()
    envelope, documents = collector.collect(spec, retrieved_at=retrieved_at)
    base = Path(artifact_dir) / spec.source_id
    raw_path = base / "raw" / f"{spec.source_id}.ndjson"
    normalized_path = base / "normalized" / f"{spec.source_id}.ndjson"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(canonical_json(envelope).encode("utf-8") + b"\n")
    normalized_path.write_bytes(ndjson_bytes(documents))
    return {
        "source_id": spec.source_id,
        "collector_id": collector.collector_id,
        "raw_path": str(raw_path),
        "normalized_path": str(normalized_path),
        "document_count": len(documents),
        "raw_sha256": envelope["sha256"],
    }


def enabled_source_ids(registry_path: str | Path, selected: str = "") -> list[str]:
    ids = [spec.source_id for spec in load_registry(registry_path) if spec.enabled]
    if selected:
        ids = [source_id for source_id in ids if source_id == selected]
    return ids


__all__ = [
    "ALLOWED_URL_SCHEMES",
    "BaseCollector",
    "COLLECTORS",
    "HttpJsonCollector",
    "RAW_ENVELOPE_KEYS",
    "RssAtomCollector",
    "SourceSpec",
    "build_raw_envelope",
    "candidate_document",
    "canonical_json",
    "content_hash",
    "enabled_source_ids",
    "fetch_url",
    "load_registry",
    "ndjson_bytes",
    "parse_registry",
    "parse_source_entry",
    "run_source",
    "sha256_bytes",
]
