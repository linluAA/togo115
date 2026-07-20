from __future__ import annotations

import re
import sys
from typing import Any
from urllib.parse import urlparse

from app.services import integration_state as _state
from app.services.link import download_link_key, expanded_search_queries, truthy


def _integration_attr(name: str):
    module = sys.modules.get("app.services.integrations")
    return getattr(module, name, None) if module is not None else None


def get_setting(*args, **kwargs):
    func = _integration_attr("get_setting") or _state.get_setting
    return func(*args, **kwargs)


class RssTorznabConfigMixin:
    def _source_type(self, source: dict[str, Any]) -> str:
        source_type = str(source.get("type") or "rss").strip().lower()
        if source_type in self.SITE_PLUGIN_TYPES:
            return "site_plugin"
        return source_type or "rss"

    def _site_plugin_id(self, source: dict[str, Any]) -> str:
        url = str(source.get("url") or "")
        # Known hosts win over a mis-set plugin (e.g. generic_magnet on qmp4.com).
        # Otherwise the suggest JSON API is opened but parsed as HTML search results.
        if self._is_qmp4_url(url):
            return "qmp4"
        if self._is_bt1207_url(url):
            return "bt1207"
        raw = str(source.get("plugin") or source.get("site_plugin") or "").strip().lower()
        plugin_id = self.SITE_PLUGIN_ALIASES.get(raw)
        if plugin_id:
            return plugin_id
        if raw == "haisou" or truthy(source.get("_haisou")):
            return "haisou"
        source_type = str(source.get("type") or "").strip().lower()
        if source_type in self.LEGACY_SITE_PLUGIN_TYPES:
            return "generic_magnet"
        return "generic_magnet"

    def _source_identity(self, source: dict[str, Any]) -> str:
        return str(source.get("id") or f"{source.get('name') or ''}|{source.get('url') or ''}")

    def _source_priority(self, source: dict[str, Any]) -> int:
        try:
            return int(source.get("priority") or 0)
        except (TypeError, ValueError):
            return 0

    def _source_dedupe_key(self, source: dict[str, Any]) -> str:
        source_type = self._source_type(source)
        if source_type == "site_plugin":
            plugin_id = self._site_plugin_id(source)
            if plugin_id in ("bt1207", "qmp4", "haisou"):
                return f"site_plugin:{plugin_id}"
        url = str(source.get("url") or "").strip().rstrip("/")
        return f"{source_type}:{url or self._source_identity(source)}"

    def _builtin_sources(self, config: dict[str, Any], configured_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        last_checked = config.get("builtin_last_checked") if isinstance(config.get("builtin_last_checked"), dict) else {}
        overrides = config.get("builtin_sources") if isinstance(config.get("builtin_sources"), dict) else {}
        configured_keys = {self._source_dedupe_key(source) for source in configured_sources}
        builtins: list[dict[str, Any]] = []
        for source in self.BUILTIN_SOURCES:
            if self._source_dedupe_key(source) in configured_keys:
                continue
            identity = self._source_identity(source)
            override = overrides.get(identity) if isinstance(overrides.get(identity), dict) else {}
            merged = {
                **source,
                **{
                    key: override[key]
                    for key in (
                        "url",
                        "enabled",
                        "use_proxy",
                        "priority",
                        "refresh_interval",
                        "keywords",
                        "quality",
                        "test_query",
                        "api_key",
                        "page_size",
                        "search_in",
                        "platforms",
                    )
                    if key in override
                },
                "id": identity,
                "name": source["name"],
                "type": "site_plugin",
                "plugin": source["plugin"],
                "_builtin": True,
                "last_checked_at": last_checked.get(identity),
            }
            if source.get("plugin") == "haisou" or truthy(source.get("_haisou")):
                merged = self._merge_haisou_builtin(merged, override)
                if not merged:
                    continue
            if truthy(merged.get("enabled"), True):
                builtins.append(merged)
        return builtins

    def _dedupe_links(self, links: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[tuple[str, str]] = set()
        for link in links:
            key = download_link_key(link)
            if not link or key in seen:
                continue
            seen.add(key)
            deduped.append(link)
        return deduped

    def _source_supports_query(self, source: dict[str, Any]) -> bool:
        url = str(source.get("url") or "")
        source_type = self._source_type(source)
        return "{query}" in url or "{title}" in url or source_type in ("torznab", "site_plugin")

    def _qmp4_query_variants(self, query: str | None) -> list[str]:
        value = str(query or "").strip()
        if not value:
            return []
        no_year = re.sub(r"[\(（\[\s]*(?:19|20)\d{2}[\)）\]\s]*", " ", value)
        no_year = re.sub(r"\s+", " ", no_year).strip()
        no_quality = re.sub(
            r"(?i)\b(?:2160p|1080p|720p|4k|web-?dl|webrip|hdtv|bluray|bdrip|x26[45]|h\.?26[45]|hevc|avc|aac|ddp?5\.?1|hdr|dv)\b",
            " ",
            no_year,
        )
        no_quality = re.sub(r"\s+", " ", no_quality).strip()
        variants: list[str] = []
        for item in (value, no_year, no_quality):
            if item and item not in variants:
                variants.append(item)
        return variants

    def _source_queries(self, source: dict[str, Any], queries: list[str]) -> list[str | None]:
        if not self._source_supports_query(source):
            return [None]
        # Paid API: one compact query per search to avoid duplicate billing.
        if self._site_plugin_id(source) == "haisou":
            for query in queries:
                value = str(query or "").strip()
                if value:
                    return [value]
            return []
        if self._site_plugin_id(source) != "qmp4":
            return list(dict.fromkeys(query for query in queries if query))
        expanded: list[str] = []
        for query in queries:
            for variant in self._qmp4_query_variants(query):
                if variant not in expanded:
                    expanded.append(variant)
        return expanded

    def _sources(self) -> list[dict[str, Any]]:
        config = get_setting("rss_sources", {"sources": []})
        sources = config.get("sources") or []
        enabled_sources: list[dict[str, Any]] = []
        for index, source in enumerate(sources):
            if not isinstance(source, dict) or not truthy(source.get("enabled"), True):
                continue
            enabled_sources.append({**source, "_order": index})
        for index, source in enumerate(self._builtin_sources(config, enabled_sources), start=len(enabled_sources)):
            enabled_sources.append({**source, "_order": index})
        return sorted(enabled_sources, key=lambda item: (-self._source_priority(item), int(item.get("_order") or 0)))

    def _merge_haisou_builtin(self, merged: dict[str, Any], override: dict[str, Any]) -> dict[str, Any] | None:
        try:
            from app.services.sources.haisou.config import (
                REQUEST_TIMEOUT_SECONDS,
                SOURCE_URL,
                haisou_settings,
            )
        except Exception:
            return None
        settings = haisou_settings()
        api_key = str(override.get("api_key") or merged.get("api_key") or settings.get("api_key") or "").strip()
        # Override wins; otherwise reuse unified settings (includes legacy haisou migration).
        if "enabled" in override:
            enabled = truthy(override.get("enabled"), False)
        else:
            enabled = bool(settings.get("enabled"))
        if not enabled or not api_key:
            return None
        page_size = override.get("page_size", merged.get("page_size", settings.get("page_size")))
        search_in = override.get("search_in", merged.get("search_in", settings.get("search_in")))
        platforms = override.get("platforms", merged.get("platforms", settings.get("platforms")))
        return {
            **merged,
            "enabled": True,
            "url": SOURCE_URL,
            "plugin": "haisou",
            "_haisou": True,
            "_request_timeout": REQUEST_TIMEOUT_SECONDS,
            "api_key": api_key,
            "page_size": page_size,
            "search_in": search_in,
            "platforms": platforms,
            "use_proxy": truthy(
                override.get("use_proxy") if "use_proxy" in override else merged.get("use_proxy"),
                False,
            ),
            "priority": int(
                override.get("priority")
                if "priority" in override
                else merged.get("priority") or settings.get("priority") or 10
            ),
            "refresh_interval": int(
                override.get("refresh_interval")
                if "refresh_interval" in override
                else merged.get("refresh_interval") or settings.get("refresh_interval") or 30
            ),
            "test_query": str(
                override.get("test_query")
                if "test_query" in override
                else merged.get("test_query") or settings.get("test_query") or ""
            ),
            "keywords": str(
                override.get("keywords")
                if "keywords" in override
                else merged.get("keywords") or settings.get("keywords") or ""
            ),
            "quality": str(
                override.get("quality")
                if "quality" in override
                else merged.get("quality") or settings.get("quality") or ""
            ),
        }

    def _source_proxy(self, source: dict[str, Any]) -> str | None:
        if truthy(source.get("use_proxy")):
            proxy = get_setting("proxy")
            return proxy.get("url")
        return None


