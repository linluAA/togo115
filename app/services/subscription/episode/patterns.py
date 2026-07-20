from __future__ import annotations

import re

CN_NUMBER_TOKEN = r"\d{1,3}|[零〇一二三四五六七八九十两壹贰叁肆伍陆柒捌玖拾]{1,8}"
EPISODE_TOKEN_RE = re.compile(
    rf"(?:s(?P<season>\d{{1,2}})\s*)?e(?:p)?(?P<episode>\d{{1,3}})(?:\s*(?:-|~|–|—|至|到)\s*(?:e(?:p)?)?(?P<episode_end>\d{{1,3}}))?"
    rf"|第\s*(?P<cn_episode>{CN_NUMBER_TOKEN})\s*[集话話](?:\s*(?:-|~|–|—|至|到)\s*第?\s*(?P<cn_episode_end>{CN_NUMBER_TOKEN})\s*[集话話]?)?",
    re.I,
)
CN_SEASON_EPISODE_RE = re.compile(
    rf"第\s*(?P<season>{CN_NUMBER_TOKEN})\s*季.*?第\s*(?P<episode>{CN_NUMBER_TOKEN})\s*[集话話](?:\s*(?:-|~|–|—|至|到)\s*第?\s*(?P<episode_end>{CN_NUMBER_TOKEN})\s*[集话話]?)?",
    re.I,
)
PLAIN_EPISODE_RANGE_RE = re.compile(
    r"(?<![a-z0-9])(?P<start>\d{1,3})\s*(?:-|~|–|—|至|到)\s*(?P<end>\d{1,3})\s*(?:集|话|話|eps?|episodes?)?(?![a-z0-9])",
    re.I,
)
UPDATE_TO_EPISODE_RE = re.compile(
    rf"(?:已?更新至|已?更至|更到|更新到|连载至|完结至)\s*(?:第\s*)?(?P<episode>{CN_NUMBER_TOKEN})(?:\s*(?:集|话|話|ep|eps?|episode))?"
    rf"|更新\s*[:：]\s*(?:第\s*)?(?P<episode_colon>{CN_NUMBER_TOKEN})(?:\s*(?:集|话|話|ep|eps?|episode))?",
    re.I,
)
SEASON_MENTION_RE = re.compile(
    rf"(?<![a-z0-9])s(?P<s>\d{{1,2}})(?!\d)"
    rf"|season[\s._-]*(?P<season>\d{{1,2}})\b"
    rf"|(?P<ord>\d{{1,2}})(?:st|nd|rd|th)?[\s._-]*season\b"
    rf"|第\s*(?P<cn>{CN_NUMBER_TOKEN})\s*[季部]",
    re.I,
)
SEASON_PACK_WORD_RE = re.compile(r"(?:全集|全季|整季|合集|完结|已完结|完整版|complete(?:d)?|full\s*season|season\s*(?:pack|complete))", re.I)
FULL_SERIES_PACK_RE = re.compile(rf"(?:全集|全剧|全套|合集|完整版|complete\s*(?:series|collection)?|full\s*(?:series|collection)|全\s*(?:{CN_NUMBER_TOKEN})\s*[季部])", re.I)
FULL_SERIES_WIDE_PACK_RE = re.compile(rf"(?:全剧|全套|complete\s*(?:series|collection)|full\s*(?:series|collection)|全\s*(?:{CN_NUMBER_TOKEN})\s*[季部])", re.I)
STRONG_PACK_WORD_RE = re.compile(rf"(?:全集|全季|整季|合集|全剧|全套|全\s*(?:{CN_NUMBER_TOKEN})\s*[集话話季部]|season\s*(?:pack|complete)|full\s*season|complete\s*(?:series|collection)|full\s*(?:series|collection))", re.I)
FULL_EPISODE_COUNT_RE = re.compile(
    rf"(?:(?:全|共)\s*(?P<prefix>{CN_NUMBER_TOKEN})\s*[集话話]"
    rf"|(?P<suffix>{CN_NUMBER_TOKEN})\s*[集话話]\s*(?:全|全集|完结|已完结)"
    rf"|(?P<en>\d{{1,3}})\s*(?:eps?|episodes?)\s*(?:complete|completed|full))",
    re.I,
)
