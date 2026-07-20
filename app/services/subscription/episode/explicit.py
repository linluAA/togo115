from __future__ import annotations

import re

from app.services.subscription.episode.keys import _expand_episode_range
from app.services.subscription.episode.numbers import _number_token_to_int
from app.services.subscription.episode.patterns import (
    CN_SEASON_EPISODE_RE,
    EPISODE_TOKEN_RE,
    FULL_EPISODE_COUNT_RE,
    PLAIN_EPISODE_RANGE_RE,
    SEASON_MENTION_RE,
    UPDATE_TO_EPISODE_RE,
)

URL_LIKE_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+|magnet:\?\S+")
SPLIT_115_SHARE_PATH_RE = re.compile(r"(?im)(?<!\S)/[A-Za-z0-9_-]{6,}(?:\?[^\s\"'<>)]+)?")

CN_EPISODE_UNIT = "\u96c6\u8bdd\u8a71"
CN_SEASON_UNIT = "\u5b63\u90e8"
CN_NUM_TOKEN = r"\d{1,3}|[\u96f6\u3007\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u58f9\u8d30\u53c1\u8086\u4f0d\u9646\u67d2\u634c\u7396\u62fe]{1,8}"
CN_SEASON_EPISODE_NATIVE_RE = re.compile(
    rf"\u7b2c\s*(?P<season>{CN_NUM_TOKEN})\s*[{CN_SEASON_UNIT}]\s*\u7b2c?\s*(?P<episode>{CN_NUM_TOKEN})\s*[{CN_EPISODE_UNIT}](?:\s*(?:-|~|\u2013|\u2014|\u81f3|\u5230)\s*\u7b2c?\s*(?P<episode_end>{CN_NUM_TOKEN})\s*[{CN_EPISODE_UNIT}]?)?",
    re.I,
)
CN_EPISODE_NATIVE_RE = re.compile(
    rf"(?:\u7b2c\s*)?(?P<episode>{CN_NUM_TOKEN})\s*[{CN_EPISODE_UNIT}](?:\s*(?:-|~|\u2013|\u2014|\u81f3|\u5230)\s*(?:\u7b2c\s*)?(?P<episode_end>{CN_NUM_TOKEN})\s*[{CN_EPISODE_UNIT}]?)?",
    re.I,
)
CN_EPISODE_RANGE_NATIVE_RE = re.compile(
    rf"\u7b2c\s*(?P<episode>{CN_NUM_TOKEN})\s*(?:-|~|\u2013|\u2014|\u81f3|\u5230)\s*(?:\u7b2c\s*)?(?P<episode_end>{CN_NUM_TOKEN})\s*[{CN_EPISODE_UNIT}]",
    re.I,
)
CN_UPDATE_TO_NATIVE_RE = re.compile(
    rf"(?:\u5df2?\u66f4\u65b0\u81f3|\u5df2?\u66f4\u81f3|\u66f4\u5230|\u66f4\u65b0\u5230|\u8fde\u8f7d\u81f3|\u9023\u8f09\u81f3|\u5b8c\u7ed3\u81f3|\u5b8c\u7d50\u81f3)\s*(?:\u7b2c\s*)?(?P<episode>{CN_NUM_TOKEN})\s*(?:[{CN_EPISODE_UNIT}]|ep|eps?|episode)?"
    rf"|\u66f4\u65b0\s*[:\uff1a]\s*(?:\u7b2c\s*)?(?P<episode_colon>{CN_NUM_TOKEN})\s*(?:[{CN_EPISODE_UNIT}]|ep|eps?|episode)?",
    re.I,
)

EPISODE_DOTTED_TOKEN_RE = re.compile(r"(?i)(?<![a-z0-9])(?:s(?P<season>\d{1,2})[\s._-]*)?(?:e|ep)(?![a-z])[\s._-]*(?P<episode>\d{1,3})(?:\s*(?:-|~|\u2013|\u2014|\u81f3|\u5230)\s*(?:e|ep)?[\s._-]*(?P<episode_end>\d{1,3}))?")
SEASON_DOTTED_EPISODE_RE = re.compile(r"(?i)(?<![a-z0-9])s(?P<season>\d{1,2})[\s._-]+(?P<episode>\d{1,3})(?:\s*(?:-|~|\u2013|\u2014|\u81f3|\u5230)\s*(?P<episode_end>\d{1,3}))?")
CN_FULL_COUNT_NATIVE_RE = re.compile(
    rf"(?:\u5168|\u5171)\s*(?P<prefix>{CN_NUM_TOKEN})\s*[{CN_EPISODE_UNIT}]|(?P<suffix>{CN_NUM_TOKEN})\s*[{CN_EPISODE_UNIT}]\s*(?:\u5168|\u5b8c\u7ed3|\u5b8c\u7d50)",
    re.I,
)
CN_SEASON_MENTION_NATIVE_RE = re.compile(rf"\u7b2c\s*(?P<season>{CN_NUM_TOKEN})\s*[{CN_SEASON_UNIT}]", re.I)



def _episode_parse_text(text: str | None) -> str:
    value = URL_LIKE_RE.sub(" ", text or "")
    return SPLIT_115_SHARE_PATH_RE.sub(" ", value)


def _season_numbers_from_text(text: str | None) -> set[int]:
    seasons: set[int] = set()
    value = _episode_parse_text(text)
    for match in SEASON_MENTION_RE.finditer(value):
        value = match.group("s") or match.group("season") or match.group("ord") or match.group("cn")
        number = _number_token_to_int(value)
        if number and 0 < number < 100:
            seasons.add(number)
    for match in CN_SEASON_MENTION_NATIVE_RE.finditer(value):
        number = _number_token_to_int(match.group("season"))
        if number and 0 < number < 100:
            seasons.add(number)
    return seasons


def _episode_counts_from_pack_text(text: str | None) -> set[int]:
    counts: set[int] = set()
    value = _episode_parse_text(text)
    for match in FULL_EPISODE_COUNT_RE.finditer(value):
        token = match.group("prefix") or match.group("suffix") or match.group("en")
        number = _number_token_to_int(token)
        if number and 0 < number <= 200:
            counts.add(number)
    for match in CN_FULL_COUNT_NATIVE_RE.finditer(value):
        token = match.group("prefix") or match.group("suffix")
        number = _number_token_to_int(token)
        if number and 0 < number <= 200:
            counts.add(number)
    return counts


def episodes_from_text(text: str) -> set[tuple[int, int]]:
    text = _episode_parse_text(text)
    episodes: set[tuple[int, int]] = set()
    episodes.update(_episodes_from_native_update_text(text))
    episodes.update(_episodes_from_update_text(text))
    if episodes:
        return episodes
    episodes.update(_episodes_from_cn_season_text(text))
    episodes.update(_episodes_from_native_cn_season_text(text))
    episodes.update(_episodes_from_dotted_episode_text(text))
    episodes.update(_episodes_from_token_text(text))
    if not episodes:
        episodes.update(_episodes_from_plain_ranges(text))
    if not episodes:
        episodes.update(_episodes_from_native_cn_episode_text(text))
    return episodes


def _episodes_from_dotted_episode_text(text: str) -> set[tuple[int, int]]:
    episodes: set[tuple[int, int]] = set()
    for match in SEASON_DOTTED_EPISODE_RE.finditer(text or ""):
        season = int(match.group("season"))
        start = int(match.group("episode"))
        end = int(match.group("episode_end")) if match.group("episode_end") else start
        episodes.update(_expand_episode_range(season, start, end))
    for match in EPISODE_DOTTED_TOKEN_RE.finditer(text or ""):
        season = int(match.group("season")) if match.group("season") else 1
        start = int(match.group("episode"))
        end = int(match.group("episode_end")) if match.group("episode_end") else start
        episodes.update(_expand_episode_range(season, start, end))
    return episodes


def _episodes_from_cn_season_text(text: str) -> set[tuple[int, int]]:
    episodes: set[tuple[int, int]] = set()
    for match in CN_SEASON_EPISODE_RE.finditer(text or ""):
        season = _number_token_to_int(match.group("season"))
        start = _number_token_to_int(match.group("episode"))
        end_value = match.group("episode_end")
        end = _number_token_to_int(end_value) if end_value else start
        if season and start:
            episodes.update(_expand_episode_range(season, start, end))
    return episodes



def _episodes_from_native_cn_season_text(text: str) -> set[tuple[int, int]]:
    episodes: set[tuple[int, int]] = set()
    for match in CN_SEASON_EPISODE_NATIVE_RE.finditer(text or ""):
        season = _number_token_to_int(match.group("season"))
        start = _number_token_to_int(match.group("episode"))
        end_value = match.group("episode_end")
        end = _number_token_to_int(end_value) if end_value else start
        if season and start:
            episodes.update(_expand_episode_range(season, start, end))
    return episodes


def _episodes_from_token_text(text: str) -> set[tuple[int, int]]:
    episodes: set[tuple[int, int]] = set()
    for match in EPISODE_TOKEN_RE.finditer(text or ""):
        if not (match.group("episode") or match.group("cn_episode")):
            continue
        season = int(match.group("season")) if match.group("season") else 1
        start = _number_token_to_int(match.group("episode") or match.group("cn_episode"))
        end_value = match.group("episode_end") or match.group("cn_episode_end")
        end = _number_token_to_int(end_value) if end_value else start
        if start:
            episodes.update(_expand_episode_range(season, start, end))
    return episodes


def _episodes_from_plain_ranges(text: str) -> set[tuple[int, int]]:
    episodes: set[tuple[int, int]] = set()
    for match in PLAIN_EPISODE_RANGE_RE.finditer(text or ""):
        start = int(match.group("start"))
        end = int(match.group("end"))
        if start <= end:
            episodes.update(_expand_episode_range(1, start, end))
    return episodes


def _episodes_from_update_text(text: str) -> set[tuple[int, int]]:
    episodes: set[tuple[int, int]] = set()
    for match in UPDATE_TO_EPISODE_RE.finditer(text or ""):
        token = match.groupdict().get("episode") or match.groupdict().get("episode_colon")
        episode = _number_token_to_int(token)
        if episode:
            episodes.update(_expand_episode_range(1, 1, episode))
    return episodes


def _episodes_from_native_cn_episode_text(text: str) -> set[tuple[int, int]]:
    if CN_FULL_COUNT_NATIVE_RE.search(text or ""):
        return set()
    episodes: set[tuple[int, int]] = set()
    for match in CN_EPISODE_RANGE_NATIVE_RE.finditer(text or ""):
        start = _number_token_to_int(match.group("episode"))
        end = _number_token_to_int(match.group("episode_end"))
        if start:
            episodes.update(_expand_episode_range(1, start, end))
    for match in CN_EPISODE_NATIVE_RE.finditer(text or ""):
        start = _number_token_to_int(match.group("episode"))
        end_value = match.group("episode_end")
        end = _number_token_to_int(end_value) if end_value else start
        if start:
            episodes.update(_expand_episode_range(1, start, end))
    return episodes


def _episodes_from_native_update_text(text: str) -> set[tuple[int, int]]:
    episodes: set[tuple[int, int]] = set()
    for match in CN_UPDATE_TO_NATIVE_RE.finditer(text or ""):
        token = match.groupdict().get("episode") or match.groupdict().get("episode_colon")
        episode = _number_token_to_int(token)
        if episode:
            episodes.update(_expand_episode_range(1, 1, episode))
    return episodes
