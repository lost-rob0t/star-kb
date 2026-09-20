"""Shared collector infrastructure: source registry, raw evidence envelopes, candidate documents.

Every collector produces two deterministic layers:

1. an immutable raw evidence envelope (collector identity + request + content hash);
2. normalized StarIntel candidate documents whose provenance carries the raw hash.

Normalization is a pure function of the raw envelope, so the same raw fixture always
produces byte-identical normalized output. Collected data is never canonical truth:
every emitted document is marked as a candidate.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAW_ENVELOPE_KEYS = (
    "collector_id",
    "source_id",
    "retrieved_at",
    "request_url",
    "media_type",
    "sha256",
    "content",
)

COLLECTOR_TYPES = ("http_json", "rss_atom")
ALLOWED_URL_SCHEMES = ("https", "file")

MAX_TIMEOUT_SECONDS = 120
MAX_RETRIES = 5
MAX_ITEMS = 1000
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_RETRIES = 2
DEFAULT_MAX_ITEMS = 200

SCHEMA_VERSION = "0.9.0"
PROFILE = "starintel-core"
PROFILE_VERSION = "0.9.1"
SCHEMA_REVISION = "0.9.0+fields.20260909.1"
COLLECTOR_TOOL_ID = "star-kb-collectors/0.1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ndjson_bytes(documents: list[dict[str, Any]]) -> bytes:
    if not documents:
        return b""
    body = "".join(canonical_json(doc) + "\n" for doc in documents)
    return body.encode("utf-8")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    type: str
    url: str
    enabled: bool
    dtype: str
    dataset: str
    timeout_seconds: int
    max_retries: int
    max_items: int


def _bounded_int(raw: Any, field: str, default: int, minimum: int, maximum: int) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"source field {field!r} must be an integer, got {raw!r}")
    if raw < minimum or raw > maximum:
        raise ValueError(f"source field {field!r} must be between {minimum} and {maximum}, got {raw}")
    return raw


def parse_source_entry(raw: Any, position: int) -> SourceSpec:
    if not isinstance(raw, dict):
        raise ValueError(f"registry source #{position} must be an object")
    source_id = raw.get("id")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError(f"registry source #{position} requires a non-empty string id")
    source_type = raw.get("type")
    if source_type not in COLLECTOR_TYPES:
        raise ValueError(f"source {source_id!r} has unknown collector type {source_type!r}")
    url = raw.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"source {source_id!r} requires a non-empty string url")
    scheme = urllib.parse.urlsplit(url).scheme
    if scheme not in ALLOWED_URL_SCHEMES:
        raise ValueError(f"source {source_id!r} url scheme {scheme!r} is not allowed (https/file only)")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"source {source_id!r} field 'enabled' must be a boolean")
    dtype = raw.get("dtype", "document")
    if not isinstance(dtype, str) or not dtype:
        raise ValueError(f"source {source_id!r} field 'dtype' must be a non-empty string")
    dataset = raw.get("dataset", f"collect:{source_id}")
    if not isinstance(dataset, str) or not dataset:
        raise ValueError(f"source {source_id!r} field 'dataset' must be a non-empty string")
    return SourceSpec(
        source_id=source_id,
        type=source_type,
        url=url,
        enabled=enabled,
        dtype=dtype,
        dataset=dataset,
        timeout_seconds=_bounded_int(raw.get("timeout_seconds"), "timeout_seconds", DEFAULT_TIMEOUT_SECONDS, 1, MAX_TIMEOUT_SECONDS),
        max_retries=_bounded_int(raw.get("max_retries"), "max_retries", DEFAULT_RETRIES, 0, MAX_RETRIES),
        max_items=_bounded_int(raw.get("max_items"), "max_items", DEFAULT_MAX_ITEMS, 1, MAX_ITEMS),
    )


def parse_registry(data: Any) -> list[SourceSpec]:
    if not isinstance(data, dict):
        raise ValueError("registry must be a JSON object")
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("registry requires a 'sources' array")
    specs: list[SourceSpec] = []
    seen: set[str] = set()
    for position, raw in enumerate(raw_sources):
        spec = parse_source_entry(raw, position)
        if spec.source_id in seen:
            raise ValueError(f"duplicate source id {spec.source_id!r} in registry")
        seen.add(spec.source_id)
        specs.append(spec)
    return specs


def load_registry(path: str | Path) -> list[SourceSpec]:
    return parse_registry(json.loads(Path(path).read_text(encoding="utf-8")))


def build_raw_envelope(
    *,
    collector_id: str,
    source_id: str,
    retrieved_at: str,
    request_url: str,
    media_type: str,
    content: bytes,
) -> dict[str, Any]:
    """Build the immutable raw evidence envelope. sha256 covers the exact response bytes."""
    return {
        "collector_id": collector_id,
        "source_id": source_id,
        "retrieved_at": retrieved_at,
        "request_url": request_url,
        "media_type": media_type,
        "sha256": sha256_bytes(content),
        "content": content.decode("utf-8", errors="replace"),
    }


REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve_file_path(parsed: urllib.parse.SplitResult) -> Path:
    """Resolve file:// URLs.

    file:///abs/path and file://localhost/abs/path are absolute. Any other netloc
    (e.g. file://tests/fixtures/x) or a relative path is treated as repo-relative,
    so fixture collection works from any working directory.
    """
    if parsed.netloc in ("", "localhost"):
        path = Path(urllib.request.url2pathname(parsed.path))
        if path.is_absolute():
            return path
        return (REPO_ROOT / path).resolve()
    return (REPO_ROOT / f"{parsed.netloc}{parsed.path}").resolve()


def fetch_url(source: SourceSpec) -> tuple[bytes, str]:
    """Fetch source content with the registry's bounded timeout/retry budget.

    file:// URLs are supported so fixture runs stay offline and replayable.
    """
    parsed = urllib.parse.urlsplit(source.url)
    if parsed.scheme == "file":
        return _resolve_file_path(parsed).read_bytes(), ""
    last_error: Exception | None = None
    for attempt in range(source.max_retries + 1):
        try:
            request = urllib.request.Request(source.url, headers={"User-Agent": "star-kb-collector/0.1"})
            with urllib.request.urlopen(request, timeout=source.timeout_seconds) as response:
                return response.read(), response.headers.get_content_type()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_error = exc
            if attempt < source.max_retries:
                time.sleep(min(2**attempt, 5))
    raise RuntimeError(
        f"fetch failed for {source.url} after {source.max_retries + 1} attempts: {last_error}"
    )


def candidate_document(
    *,
    source: SourceSpec,
    envelope: dict[str, Any],
    data: dict[str, Any],
    dtype: str | None = None,
) -> dict[str, Any]:
    """Build one normalized StarIntel candidate document from a raw envelope.

    The envelope's sha256 and collector identity are preserved in provenance and in a
    source record, so projection provenance resolves back to the raw evidence hash.
    """
    raw_hash = envelope["sha256"]
    return {
        "_id": f"starintel:candidate:{source.source_id}:{content_hash(data)[:16]}",
        "dataset": source.dataset,
        "dtype": dtype or source.dtype,
        "schema_version": SCHEMA_VERSION,
        "profile": PROFILE,
        "profile_version": PROFILE_VERSION,
        "schema_revision": SCHEMA_REVISION,
        "version": 1,
        "candidate": True,
        "date_added": envelope["retrieved_at"],
        "sources": [
            {
                "source_id": f"raw:{source.source_id}",
                "kind": f"collector:{envelope['collector_id']}",
                "url": envelope["request_url"],
                "retrieved_at": envelope["retrieved_at"],
                "content_hash": raw_hash,
            }
        ],
        "evidence": [
            {
                "evidence_id": f"raw-envelope:{raw_hash[:16]}",
                "source_id": f"raw:{source.source_id}",
                "role": "raw-retrieval",
                "observation": (
                    f"collected by {envelope['collector_id']} from {envelope['request_url']}"
                ),
                "status": "candidate",
            }
        ],
        "provenance": {
            "collector": envelope["collector_id"],
            "tool": COLLECTOR_TOOL_ID,
            "method": "deterministic-normalize",
            "imported_from": envelope["request_url"],
            "transform": f"raw-envelope:{raw_hash}",
        },
        "data": data,
    }


class BaseCollector(ABC):
    """Two-layer deterministic collector contract."""

    collector_id: str = "base"
    default_media_type: str = "application/octet-stream"

    def collect(self, source: SourceSpec, retrieved_at: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        content, fetched_media_type = self.fetch(source)
        media_type = self.resolve_media_type(content, fetched_media_type)
        envelope = build_raw_envelope(
            collector_id=self.collector_id,
            source_id=source.source_id,
            retrieved_at=retrieved_at or utc_now_iso(),
            request_url=source.url,
            media_type=media_type,
            content=content,
        )
        documents = self.normalize(envelope, source)
        return envelope, documents

    @abstractmethod
    def fetch(self, source: SourceSpec) -> tuple[bytes, str]:
        """Return (raw content bytes, fetched media type or '')."""

    def resolve_media_type(self, content: bytes, fetched_media_type: str) -> str:
        return fetched_media_type or self.default_media_type

    @abstractmethod
    def normalize(self, envelope: dict[str, Any], source: SourceSpec) -> list[dict[str, Any]]:
        """Pure function of the raw envelope; returns candidate StarIntel documents."""
