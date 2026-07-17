from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.services.adapters.pan115 import PAN115_URL_RE, normalize_115_share_link

PAN115_LOOSE_URL_RE = re.compile(
    r"(?:(?:https?)\s*:\s*/\s*/)?(?:www\s*\.\s*)?(?P<host>115(?:cdn)?\s*\.\s*com)\s*/\s*s\s*/\s*(?P<code>[A-Za-z0-9_-]+)(?P<query>\s*\?[^\s\"'<>)]+)?",
    re.I,
)
DOWNLOAD_TEXT_TRANSLATION = str.maketrans(
    {
        "：": ":",
        "／": "/",
        "？": "?",
        "＆": "&",
        "＝": "=",
        "。": ".",
    }
)
INVISIBLE_URL_CHARS_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
MAGNET_URL_RE = re.compile(r"magnet:\?[^\"'<>]+", re.I)
TORRENT_URL_RE = re.compile(r"https?://[^\s\"'<>)]+?\.torrent(?:\?[^\s\"'<>)]+)?", re.I)
BTIH_HASH_RE = re.compile(r"(?:种子哈希|信息哈希|info\s*hash|btih|hash)\s*[：:]\s*([A-Fa-f0-9]{32,40})", re.I)
PAN115_RECEIVE_CODE_RE = re.compile(
    r"(?:提取码|访问码|接收码|密码|口令|receive[_\s-]*code|password|pwd|pass|code)\s*[：:=]?\s*([A-Za-z0-9]{2,8})",
    re.I,
)

def _clean_download_link(link: str) -> str:
    value = str(link or "").strip()
    if value.casefold().startswith("magnet:?"):
        value = re.split(r"\s+(?=(?:https?://|magnet:\?|(?:www\.)?115(?:cdn)?\s*\.\s*com\s*/\s*s\s*/))", value, 1, re.I)[0]
        value = re.split(r"(?:磁力下载|复制全部地址|复制链接|复制|迅雷下载|下载地址)", value, 1)[0]
    cleaned = re.sub(r"\s+", "", value).rstrip("，。；,.;")
    while cleaned.endswith(")") and cleaned.count(")") > cleaned.count("("):
        cleaned = cleaned[:-1]
    if re.match(r"(?i)^(?:www\.)?115(?:cdn)?\.com/s/", cleaned):
        cleaned = f"https://{cleaned}"
    if re.match(r"(?i)^https?://(?:www\.)?115(?:cdn)?\.com/s/", cleaned):
        normalized = normalize_115_share_link(cleaned)
        return normalized or cleaned
    return cleaned


def is_115_share_link(link: str | None) -> bool:
    parsed = urlparse(str(link or "").strip())
    host = parsed.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    return host in {"115.com", "115cdn.com"} and bool(_115_share_code(link))


def is_valid_download_link(link: str | None) -> bool:
    value = str(link or "").strip()
    if not value:
        return False
    if value.casefold().startswith("magnet:?"):
        return True
    if re.match(r"(?i)^https?://[^\s\"'<>)]+\.torrent(?:\?[^\s\"'<>)]+)?$", value):
        return True
    parsed = urlparse(value)
    host = parsed.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    if host in {"115.com", "115cdn.com"}:
        return bool(_115_share_code(value))
    return False


def _115_share_code(link: str | None) -> str:
    parsed = urlparse(str(link or "").strip())
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[-2].casefold() != "s":
        return ""
    code = parts[-1].strip()
    return code if code and code.casefold() != "s" else ""


def _append_115_receive_code(link: str, text: str, match_end: int) -> str:
    parsed = urlparse(link)
    if not re.search(r"(?i)(?:^|\.)115(?:cdn)?\.com$", parsed.netloc):
        return link
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query_keys = {key.lower() for key, _ in query_items}
    if {"password", "pwd", "receive_code"} & query_keys:
        return link
    window = text[match_end:match_end + 120]
    match = PAN115_RECEIVE_CODE_RE.search(window)
    if not match:
        return link
    query_items.append(("password", match.group(1)))
    return urlunparse(parsed._replace(query=urlencode(query_items)))


def _download_link_key(link: str | None) -> tuple[str, str]:
    magnet_match = re.search(r"(?i)(?:xt=urn:btih:|btih:)([a-f0-9]{32,40})", str(link or ""))
    if magnet_match:
        return ("magnet", magnet_match.group(1).casefold())
    return ("url", str(link or "").strip())


def _loose_115_link(match: re.Match[str]) -> str:
    host = re.sub(r"\s+", "", match.group("host") or "").lower()
    code = re.sub(r"\s+", "", match.group("code") or "")
    query = re.sub(r"\s+", "", match.group("query") or "")
    if query and not re.match(r"(?i)^\?(?:password|pwd|receive_code)=", query):
        query = ""
    return f"https://{host}/s/{code}{query}"


def _normalize_download_text(text: str | None) -> str:
    value = unescape(str(text or ""))
    value = INVISIBLE_URL_CHARS_RE.sub("", value)
    return value.translate(DOWNLOAD_TEXT_TRANSLATION)


def extract_115_links(text: str | None) -> list[str]:
    if not text:
        return []
    text = _normalize_download_text(text)
    seen: set[str] = set()
    links: list[str] = []
    for match in PAN115_URL_RE.finditer(text):
        link = _append_115_receive_code(_clean_download_link(match.group(0)), text, match.end())
        if link not in seen:
            seen.add(link)
            links.append(link)
    for match in PAN115_LOOSE_URL_RE.finditer(text):
        link = _append_115_receive_code(_clean_download_link(_loose_115_link(match)), text, match.end())
        if link not in seen:
            seen.add(link)
            links.append(link)
    return links


def extract_download_links(text: str | None) -> list[str]:
    if not text:
        return []
    text = unescape(text)
    seen: set[tuple[str, str]] = set()
    links: list[str] = []
    for link in extract_115_links(text):
        if not is_valid_download_link(link):
            continue
        key = _download_link_key(link)
        if key not in seen:
            seen.add(key)
            links.append(link)
    for pattern in (MAGNET_URL_RE, TORRENT_URL_RE):
        for match in pattern.findall(text):
            link = _clean_download_link(match)
            if not is_valid_download_link(link):
                continue
            key = _download_link_key(link)
            if key not in seen:
                seen.add(key)
                links.append(link)
    for match in BTIH_HASH_RE.finditer(text):
        link = f"magnet:?xt=urn:btih:{match.group(1).upper()}"
        key = _download_link_key(link)
        if key not in seen:
            seen.add(key)
            links.append(link)
    return links


