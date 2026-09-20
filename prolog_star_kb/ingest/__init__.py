"""Deterministic ingestion of external/generated knowledge into StarIntel candidates."""

from __future__ import annotations

from .autodig import AUTODIG_COLLECTOR, ingest_autodig, ndjson_bytes

__all__ = ["AUTODIG_COLLECTOR", "ingest_autodig", "ndjson_bytes"]
