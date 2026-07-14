from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse

from app.services.link_parser import _years_from_text


class RssTorznabUrlBuilderMixin:
    def _source_url(self, source: dict[str, Any], query: str | None = None) -> str | None:
        url = str(source.get("url") or "").strip()
        if not url:
            return None
        if "{query}" in url or "{title}" in url:
            return self._templated_source_url(url, query)
        if query and self._source_type(source) == "torznab":
            return self._torznab_source_url(url, query)
        if query and self._source_type(source) == "site_plugin":
            return self._site_plugin_source_url(source, url, query)
        return url

    def _query_release_year(self, query: str | None) -> int | None:
        years = _years_from_text(query)
        return min(years) if years else None

    def _templated_source_url(self, url: str, query: str | None) -> str | None:
        if not query:
            return None
        encoded = quote(query)
        return url.replace("{query}", encoded).replace("{title}", encoded)

    def _torznab_source_url(self, url: str, query: str) -> str:
        parsed = urlparse(url)
        params = parse_qsl(parsed.query, keep_blank_values=True)
        keys = {key.lower() for key, _ in params}
        if "t" not in keys:
            params.append(("t", "search"))
        if "q" not in keys:
            params.append(("q", query))
        return urlunparse(parsed._replace(query=urlencode(params)))

    def _site_plugin_source_url(self, source: dict[str, Any], url: str, query: str) -> str:
        parsed = urlparse(url)
        plugin_id = self._site_plugin_id(source)
        if plugin_id == "qmp4" or self._is_qmp4_url(url):
            return urlunparse(parsed._replace(path="/index.php/ajax/suggest", query=urlencode({"mid": 1, "wd": query})))
        if (plugin_id == "bt1207" or self._is_bt1207_url(url)) and parsed.path.rstrip("/") in ("", "/search"):
            return urlunparse(parsed._replace(path="/search", query=urlencode({"keyword": query})))
        if parsed.query:
            params = parse_qsl(parsed.query, keep_blank_values=True)
            if not any(key.lower() in ("q", "wd", "keyword", "search", "query") for key, _ in params):
                params.append(("q", query))
            return urlunparse(parsed._replace(query=urlencode(params)))
        if parsed.path in ("", "/"):
            return urljoin(url if url.endswith("/") else f"{url}/", f"s/{quote(query)}.html")
        return url

