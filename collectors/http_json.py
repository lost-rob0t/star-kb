"""Deterministic HTTP JSON collector: raw envelope + normalized StarIntel candidates."""

from __future__ import annotations

import json
from typing import Any

from .base import BaseCollector, SourceSpec, candidate_document, fetch_url


class HttpJsonCollector(BaseCollector):
    collector_id = "http-json"
    default_media_type = "application/json"

    def fetch(self, source: SourceSpec) -> tuple[bytes, str]:
        return fetch_url(source)

    def normalize(self, envelope: dict[str, Any], source: SourceSpec) -> list[dict[str, Any]]:
        payload = json.loads(envelope["content"])
        items = payload if isinstance(payload, list) else [payload]
        documents: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items[: source.max_items]:
            if not isinstance(item, dict):
                continue
            document = candidate_document(source=source, envelope=envelope, data=item)
            if document["_id"] in seen:
                continue
            seen.add(document["_id"])
            documents.append(document)
        return documents
