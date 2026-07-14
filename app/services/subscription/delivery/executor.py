from __future__ import annotations

from app.services.adapters.pan115 import PAN115_URL_RE, SHARE_UNAVAILABLE, SHARE_UNKNOWN, normalize_115_share_link
from app.services.link_downloads import is_valid_download_link


async def _deliver_resource_url(
    resource,
    delivery_mode: str,
    pan115_adapter_cls: type,
    telegram_bot_adapter_cls: type,
) -> tuple[bool, str]:
    url = _normalized_delivery_url(resource["url"] or "")
    if not url:
        return False, "资源链接为空"
    if not is_valid_download_link(url):
        return False, "资源链接格式无效"

    pan115 = None
    if PAN115_URL_RE.match(url):
        pan115 = pan115_adapter_cls()
        availability = await pan115.share_availability(url)
        if availability == SHARE_UNAVAILABLE:
            return False, "115 分享链接已失效"
        if availability == SHARE_UNKNOWN:
            pass

    if delivery_mode == "telegram_bot":
        return await telegram_bot_adapter_cls().forward_to_bot(url), ""
    if PAN115_URL_RE.match(url):
        return await pan115.transfer(url, resource["target_path"]), ""
    return await pan115_adapter_cls().offline_download(url, resource["target_path"]), ""


def _normalized_delivery_url(url: str) -> str:
    value = str(url or "").strip()
    clean_115 = normalize_115_share_link(value)
    return clean_115 or value
