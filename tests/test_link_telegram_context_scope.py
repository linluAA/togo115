from __future__ import annotations

from app.services.link import context_for_115_link, _local_text_matches_query
from app.services.adapters.telegram.scan.message_links import _telegram_resource_title


def test_context_for_115_link_prefers_nearest_title_above_share() -> None:
    text = "\n".join(
        [
            "剧集：野狗骨头 2026 第 20 集 1080p",
            "名称: 念念相忘.Just.for.Meeting.You.2023.2160p",
            "链接：https://115.com/s/swsbls23ndb?password=KMKM",
        ]
    )
    scoped = context_for_115_link(text, "https://115.com/s/swsbls23ndb?password=KMKM", 1)
    assert "念念相忘" in scoped
    assert "野狗骨头" not in scoped
    assert _telegram_resource_title(scoped).startswith("念念相忘")
    assert not _local_text_matches_query(scoped, "野狗骨头")


def test_context_for_115_link_keeps_matching_title_when_adjacent() -> None:
    text = "\n".join(
        [
            "剧集：野狗骨头 2026 第 20 集 1080p",
            "链接：https://115.com/s/ydgtlink?password=1111",
        ]
    )
    scoped = context_for_115_link(text, "https://115.com/s/ydgtlink?password=1111", 1)
    assert "野狗骨头" in scoped
    assert _local_text_matches_query(scoped, "野狗骨头")


def test_context_for_115_link_excludes_following_title() -> None:
    text = "\n".join(
        [
            "剧集：野狗骨头 2026",
            "链接：https://115.com/s/ydgtlink?password=1111",
            "名称: 念念相忘.Just.for.Meeting.You.2023.2160p",
            "链接：https://115.com/s/swsbls23ndb?password=KMKM",
        ]
    )
    scoped = context_for_115_link(text, "https://115.com/s/ydgtlink?password=1111", 2)
    assert "野狗骨头" in scoped
    assert "念念相忘" not in scoped

def test_telegram_resource_title_includes_episode_range_from_context() -> None:
    text = "\n".join(
        [
            "剧集：野狗骨头(2026)",
            "评分：4.2",
            "TMDB ID：291392",
            "季集：S01E01-E21",
            "大小：83.97GB",
            "质量：4K / WEB-DL / HEVC",
            "https://115.com/s/ydgt21?password=8888",
        ]
    )
    title = _telegram_resource_title(text)
    assert "野狗骨头" in title
    assert "S01E01-E21" in title

