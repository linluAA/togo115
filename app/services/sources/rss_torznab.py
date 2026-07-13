from __future__ import annotations

import sys

from app.services import integration_state as _state
from app.services.source_stats import list_source_stats
from app.services.sources.rss_torznab_cache import RssTorznabCacheMixin
from app.services.sources.rss_torznab_config import RssTorznabConfigMixin
from app.services.sources.rss_torznab_feed import RssTorznabFeedMixin
from app.services.sources.rss_torznab_refresh import RssTorznabRefreshMixin
from app.services.sources.rss_torznab_search import RssTorznabSearchMixin
from app.services.sources.rss_torznab_site import RssTorznabSiteMixin
from app.services.sources.rss_torznab_test import RssTorznabTestMixin
from app.services.types import SearchResult


def _integration_attr(name: str):
    module = sys.modules.get("app.services.integrations")
    return getattr(module, name, None) if module is not None else None


def get_setting(*args, **kwargs):
    func = _integration_attr("get_setting") or _state.get_setting
    return func(*args, **kwargs)


def save_setting(*args, **kwargs):
    func = _integration_attr("save_setting") or _state.save_setting
    return func(*args, **kwargs)


def module_proxy(*args, **kwargs):
    func = _integration_attr("module_proxy") or _state.module_proxy
    return func(*args, **kwargs)


class RssTorznabAdapter(
    RssTorznabTestMixin,
    RssTorznabRefreshMixin,
    RssTorznabCacheMixin,
    RssTorznabConfigMixin,
    RssTorznabSiteMixin,
    RssTorznabFeedMixin,
    RssTorznabSearchMixin,
):
    SEARCH_CACHE_TTL_SECONDS = 1800
    _search_cache: dict[tuple[str, str], tuple[float, list[SearchResult]]] = {}

    LEGACY_SITE_PLUGIN_TYPES = {"magnet_web", "web_magnet", "magnet"}
    SITE_PLUGIN_TYPES = {"site_plugin", "site", "plugin", *LEGACY_SITE_PLUGIN_TYPES}
    SITE_PLUGIN_ALIASES = {
        "bt1207": "bt1207",
        "bt1207_magnet": "bt1207",
        "generic": "generic_magnet",
        "generic_html": "generic_magnet",
        "generic_magnet": "generic_magnet",
        "magnet": "generic_magnet",
        "magnet_web": "generic_magnet",
        "qmp4": "qmp4",
        "qiwei": "qmp4",
        "qmp4_magnet": "qmp4",
        "hdhive": "hdhive",
        "yingchao": "hdhive",
        "hdhive_115": "hdhive",
    }
    MAGNET_WEB_BROWSER_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    BUILTIN_SOURCES = (
        {
            "id": "builtin_bt1207",
            "name": "BT1207",
            "type": "site_plugin",
            "plugin": "bt1207",
            "url": "https://bt1207to.cc/",
            "enabled": True,
            "use_proxy": False,
            "priority": -50,
            "refresh_interval": 30,
            "_builtin": True,
        },
        {
            "id": "builtin_qmp4",
            "name": "QMP4 / 七味",
            "type": "site_plugin",
            "plugin": "qmp4",
            "url": "https://www.qmp4.com/",
            "enabled": True,
            "use_proxy": False,
            "priority": -50,
            "refresh_interval": 30,
            "_builtin": True,
        },
        {
            "id": "builtin_hdhive",
            "name": "HDHive / 影巢",
            "type": "site_plugin",
            "plugin": "hdhive",
            "url": "https://hdhive.com/",
            "enabled": False,
            "use_proxy": False,
            "priority": -40,
            "refresh_interval": 30,
            "points_threshold": 0,
            "_builtin": True,
        },
    )


__all__ = ["RssTorznabAdapter", "SearchResult", "list_source_stats"]
