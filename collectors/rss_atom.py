"""Deterministic RSS 2.0 / Atom collector: raw envelope + normalized StarIntel candidates."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from .base import BaseCollector, SourceSpec, candidate_document, content_hash, fetch_url


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element) -> str:
    return "".join(element.itertext()).strip()


def _first_text(parent: ET.Element, *names: str) -> str:
    wanted = set(names)
    for child in parent:
        if _localname(child.tag) in wanted:
            value = _text(child)
            if value:
                return value
    return ""


def _atom_link(parent: ET.Element) -> str:
    fallback = ""
    for child in parent:
        if _localname(child.tag) != "link":
            continue
        rel = child.get("rel", "alternate")
        href = child.get("href", "")
        if not href:
            continue
        if rel == "alternate":
            return href
        if not fallback:
            fallback = href
    return fallback


def _root(feed: ET.Element) -> str:
    return _localname(feed.tag)


def parse_items(content: str) -> tuple[str, list[dict[str, str]]]:
    """Parse RSS 2.0 or Atom content into (feed_kind, ordered item records)."""
    feed = ET.fromstring(content)
    kind = _root(feed)
    records: list[dict[str, str]] = []
    if kind == "rss":
        for item in feed.iter():
            if _localname(item.tag) != "item":
                continue
            records.append(
                {
                    "title": _first_text(item, "title"),
                    "url": _first_text(item, "link"),
                    "guid": _first_text(item, "guid", "id"),
                    "published_at": _first_text(item, "pubDate", "published", "updated"),
                    "summary": _first_text(item, "description", "summary"),
                }
            )
        return "rss", records
    if kind == "feed":
        for entry in feed:
            if _localname(entry.tag) != "entry":
                continue
            records.append(
                {
                    "title": _first_text(entry, "title"),
                    "url": _atom_link(entry),
                    "guid": _first_text(entry, "id"),
                    "published_at": _first_text(entry, "published", "updated"),
                    "summary": _first_text(entry, "summary", "content"),
                }
            )
        return "atom", records
    raise ValueError(f"unsupported feed root element {kind!r}; expected rss or feed (Atom)")


class RssAtomCollector(BaseCollector):
    collector_id = "rss-atom"
    default_media_type = "application/xml"

    def fetch(self, source: SourceSpec) -> tuple[bytes, str]:
        return fetch_url(source)

    def resolve_media_type(self, content: bytes, fetched_media_type: str) -> str:
        if fetched_media_type not in ("", "application/octet-stream", "application/xml", "text/xml"):
            return fetched_media_type
        kind, _ = parse_items(content.decode("utf-8"))
        return "application/rss+xml" if kind == "rss" else "application/atom+xml"

    def normalize(self, envelope: dict[str, Any], source: SourceSpec) -> list[dict[str, Any]]:
        _, records = parse_items(envelope["content"])
        documents: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records[: source.max_items]:
            key = record["guid"] or canonical_record(record)
            data = dict(record)
            document = candidate_document(source=source, envelope=envelope, data=data)
            stable_id = f"starintel:candidate:{source.source_id}:{id_hash(key)[:16]}"
            document["_id"] = stable_id
            if stable_id in seen:
                continue
            seen.add(stable_id)
            documents.append(document)
        return documents


def canonical_record(record: dict[str, str]) -> str:
    return "|".join(f"{k}={record.get(k, '')}" for k in sorted(record))


def id_hash(value: str) -> str:
    return content_hash(value)
