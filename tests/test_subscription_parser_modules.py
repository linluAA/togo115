from app.services.subscription.episode.parser import (
    episode_keys_from_text_for_subscription,
    missing_episode_keys,
    episodes_from_text,
)
from app.services.subscription.match.text_utils import title_without_year, years_from_text


def test_episode_parser_extracts_explicit_season_range() -> None:
    assert episodes_from_text("Drama S02E01-E03 1080p") == {(2, 1), (2, 2), (2, 3)}


def test_episode_parser_maps_full_pack_to_missing_episode_range() -> None:
    subscription = {
        "media_type": "tv",
        "tmdb_total_count": 10,
        "emby_episode_keys": ["1x1", "1x2", "1x3", "1x4", "1x5"],
    }

    assert missing_episode_keys(subscription) == {(1, 6), (1, 7), (1, 8), (1, 9), (1, 10)}
    assert episode_keys_from_text_for_subscription(subscription, "Drama 10 episodes complete 1080p") == {
        (1, 1),
        (1, 2),
        (1, 3),
        (1, 4),
        (1, 5),
        (1, 6),
        (1, 7),
        (1, 8),
        (1, 9),
        (1, 10),
    }


def test_episode_parser_handles_native_chinese_episode_numbers() -> None:
    assert episodes_from_text("\u7b2c\u516b\u96c6") == {(1, 8)}
    assert episodes_from_text("\u7b2c\u5341\u4e8c\u8bdd") == {(1, 12)}
    assert episodes_from_text("\u66f4\u65b0\u81f3\u7b2c\u516b\u96c6") == {
        (1, 1),
        (1, 2),
        (1, 3),
        (1, 4),
        (1, 5),
        (1, 6),
        (1, 7),
        (1, 8),
    }
    assert episodes_from_text("\u7b2c1\u8bdd-\u7b2c3\u8bdd") == {(1, 1), (1, 2), (1, 3)}


def test_episode_parser_handles_native_chinese_season_context() -> None:
    subscription = {
        "media_type": "tv",
        "tmdb_seasons": [
            {"season_number": 1, "episode_count": 10},
            {"season_number": 2, "episode_count": 12},
        ],
        "emby_episode_keys": [f"1x{episode}" for episode in range(1, 11)],
    }

    assert episode_keys_from_text_for_subscription(subscription, "\u7b2c\u4e8c\u5b63 \u7b2c\u4e03\u96c6") == {(2, 7)}
    assert episode_keys_from_text_for_subscription(subscription, "\u7b2c2\u5b63\u516812\u96c6 1080p") == {
        (2, episode) for episode in range(1, 13)
    }
    assert episode_keys_from_text_for_subscription(subscription, "\u7b2c2\u5b63 \u66f4\u65b0\u81f3\u7b2c8\u96c6") == {
        (2, episode) for episode in range(1, 9)
    }


def test_episode_parser_handles_real_world_title_variants() -> None:
    subscription = {
        "media_type": "tv",
        "tmdb_seasons": [
            {"season_number": 1, "episode_count": 8},
            {"season_number": 2, "episode_count": 12},
        ],
        "emby_episode_keys": [],
    }

    assert episodes_from_text("\u5c06\u591c.2026.S01.08.1080p.WEB-DL") == {(1, 8)}
    assert episodes_from_text("\u5c06\u591c 2026 EP.08 1080p") == {(1, 8)}
    assert episodes_from_text("\u5c06\u591c 2026 \u7b2c01\u81f308\u96c6 1080p") == {
        (1, episode) for episode in range(1, 9)
    }
    assert episode_keys_from_text_for_subscription(subscription, "\u5c06\u591c \u7b2c\u4e8c\u5b63 01-12 1080p") == {
        (2, episode) for episode in range(1, 13)
    }


def test_text_utils_extracts_and_removes_year() -> None:
    assert years_from_text("Drama (2026) 1080p") == {2026}
    assert title_without_year("Drama (2026)") == "Drama"
