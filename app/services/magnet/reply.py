from __future__ import annotations

from typing import Any

from app.services.sources.rss_torznab import SearchResult
from app.services.magnet.cache import _store_pending_magnet_results
from app.services.magnet.ranking import _detail_title, _detail_year, _display_source, _resource_size

def magnet_results_reply(detail: dict[str, Any], results: list[SearchResult]) -> str:
    title = _detail_title(detail) or "\u672a\u547d\u540d"
    year = _detail_year(detail) or "\u672a\u77e5\u5e74\u4efd"
    if not results:
        return f"{title} ({year})\n\u6ca1\u6709\u4ece\u78c1\u529b\u8ba2\u9605\u6e90\u627e\u5230\u5339\u914d\u7ed3\u679c\u3002"
    lines = [f"{title} ({year})", f"\u627e\u5230 {len(results)} \u6761\u6700\u5339\u914d\u78c1\u529b\uff1a"]
    for index, result in enumerate(results, start=1):
        name = str(result.title or "\u78c1\u529b\u8d44\u6e90").strip()[:80]
        source = _display_source(result.source)
        size = _resource_size(result) or "\u672a\u77e5"
        lines.append(f"\n{index}. {name}\n\u5927\u5c0f\uff1a{size}\n\u6765\u6e90\uff1a{source}\n{result.url}")
    return "\n".join(lines)


def magnet_results_reply_markup(detail: dict[str, Any], results: list[SearchResult]) -> dict[str, Any]:
    token = _store_pending_magnet_results(detail, results)
    buttons = [[]]
    for index, result in enumerate(results, start=1):
        buttons[0].append({"text": str(index), "callback_data": f"magpick:{token}:{index - 1}"})
    return {"inline_keyboard": buttons}



