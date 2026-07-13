from __future__ import annotations

import xml.etree.ElementTree as ET

from app.services.link_feed_candidates import _feed_item_link_candidates
from app.services.link_downloads import _clean_download_link, extract_download_links, is_valid_download_link

def _first_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in names:
            return (child.text or "").strip()
    return ""


def _all_text(element: ET.Element, names: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in names:
            value = (child.text or "").strip()
            if value:
                values.append(value)
    return values


def _item_links(element: ET.Element, allow_direct_http: bool = False) -> list[str]:
    text_candidates, direct_candidates = _feed_item_link_candidates(element, allow_direct_http)
    links: list[str] = []
    for candidate in text_candidates:
        links.extend(extract_download_links(candidate))
    for candidate in direct_candidates:
        extracted = extract_download_links(candidate)
        links.extend(extracted or ([candidate] if allow_direct_http and candidate.startswith(("http://", "https://", "magnet:?")) else []))
    return _dedupe_clean_links(links)


def _dedupe_clean_links(links: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for link in links:
        cleaned = _clean_download_link(link)
        if cleaned and is_valid_download_link(cleaned) and cleaned not in seen:
            seen.add(cleaned)
            deduped.append(cleaned)
    return deduped


def _item_context(element: ET.Element) -> str:
    parts = [
        _first_text(element, ("title",)),
        _first_text(element, ("description", "summary", "content", "encoded")),
        *_all_text(element, ("category",)),
    ]
    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name == "attr":
            name = child.attrib.get("name", "")
            value = child.attrib.get("value", "")
            if name or value:
                parts.append(f"{name}: {value}")
    return "\n".join(part for part in parts if part)
