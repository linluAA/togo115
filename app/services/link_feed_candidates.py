from __future__ import annotations

import xml.etree.ElementTree as ET


def _looks_like_direct_download(url: str) -> bool:
    lowered = url.strip().casefold()
    return lowered.startswith("magnet:?") or lowered.endswith(".torrent") or any(
        marker in lowered for marker in ("/download", "download?", "getfile", "attachment", "fileid=")
    )


def _feed_item_link_candidates(element: ET.Element, allow_direct_http: bool = False) -> tuple[list[str], list[str]]:
    text_candidates: list[str] = []
    direct_candidates: list[str] = []
    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name == "link":
            _append_link_value(child.attrib.get("href"), allow_direct_http, text_candidates, direct_candidates)
            _append_link_value(child.text, allow_direct_http, text_candidates, direct_candidates)
        if local_name in ("enclosure", "torznab"):
            _append_direct_value(child.attrib.get("url"), direct_candidates)
        if local_name == "attr":
            _append_attr_value(child.attrib.get("name", ""), child.attrib.get("value"), text_candidates, direct_candidates)
    return text_candidates, direct_candidates


def _append_link_value(value: str | None, allow_direct_http: bool, text_candidates: list[str], direct_candidates: list[str]) -> None:
    if not value:
        return
    cleaned = value.strip()
    if allow_direct_http and _looks_like_direct_download(cleaned):
        direct_candidates.append(cleaned)
    else:
        text_candidates.append(cleaned)


def _append_direct_value(value: str | None, direct_candidates: list[str]) -> None:
    if value:
        direct_candidates.append(value.strip())


def _append_attr_value(name: str, value: str | None, text_candidates: list[str], direct_candidates: list[str]) -> None:
    if not value:
        return
    cleaned = value.strip()
    if name.casefold() in ("magneturl", "downloadurl", "download", "torrent", "link"):
        direct_candidates.append(cleaned)
    else:
        text_candidates.append(cleaned)
