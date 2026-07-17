from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from app.db import add_log
from app.services.link import _first_text, _item_context, _item_links, extract_download_links
from app.services.types import SearchResult


class RssTorznabFeedMixin:
    def _parse_feed(self, source: dict[str, Any], xml_text: str) -> list[SearchResult]:
        name = str(source.get("name") or "订阅源").strip()
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            add_log("warning", "rss", "订阅源解析失败", {"source": name, "error": str(exc)})
            return []
        items = [item for item in root.iter() if item.tag.rsplit("}", 1)[-1].lower() in ("item", "entry")]
        results: list[SearchResult] = []
        for item in items:
            title = _first_text(item, ("title",)) or name
            context = _item_context(item)
            text = context or title
            if not self._source_matches_filters(source, text):
                continue
            source_type = self._source_type(source)
            links = _item_links(item, allow_direct_http=source_type == "torznab") or extract_download_links(text)
            for link in links:
                results.append(
                    SearchResult(
                        title=title[:120],
                        url=link,
                        source=f"{source_type}:{name}",
                        message_id=_first_text(item, ("guid", "id")),
                        context=text,
                    )
                )
        return results

