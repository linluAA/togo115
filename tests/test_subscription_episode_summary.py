
from app.services.subscription.episode.summary import episode_range_labels, subscription_episode_snapshot


def test_episode_range_labels_compact_ranges() -> None:
    labels = episode_range_labels({(1, 1), (1, 2), (1, 4), (2, 1), (2, 2)})

    assert labels == ["S01E01-E02", "S01E04", "S02E01-E02"]


def test_subscription_episode_snapshot_reports_missing_ranges() -> None:
    snapshot = subscription_episode_snapshot(
        {
            "media_type": "tv",
            "tmdb_total_count": 12,
            "emby_episode_keys": [f"1x{episode}" for episode in range(1, 9)],
        }
    )

    assert snapshot["expected_count"] == 12
    assert snapshot["owned_count"] == 8
    assert snapshot["missing_count"] == 4
    assert snapshot["missing_ranges"] == ["S01E09-E12"]
