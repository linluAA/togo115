from __future__ import annotations

from app.services.adapters.telegram.scan.message_candidates import telegram_candidate_link_contexts


class DummyMessage:
    def __init__(self, message_id: int, text: str, grouped_id=None) -> None:
        self.id = message_id
        self.raw_text = text
        self.message = text
        self.text = text
        self.buttons = []
        self.grouped_id = grouped_id
        self.media = None


def test_candidate_contexts_do_not_mix_adjacent_resource_cards() -> None:
    messages = [
        DummyMessage(100, "\u5267\u96c6\uff1a\u7231\u4e3d\u4e1d\uff082020\uff09"),
        DummyMessage(101, "\u94fe\u63a5\uff1ahttps://115.com/s/alice?password=1111"),
        DummyMessage(102, "\u7535\u5f71\uff1a\u5982\u5c65\u8584\u51b0\uff082026\uff09"),
        DummyMessage(103, "\u94fe\u63a5\uff1ahttps://115.com/s/ice?password=2222"),
    ]

    contexts = telegram_candidate_link_contexts(messages)

    alice_context = contexts["https://115.com/s/alice?password=1111"]
    ice_context = contexts["https://115.com/s/ice?password=2222"]
    assert "\u7231\u4e3d\u4e1d" in alice_context
    assert "\u5982\u5c65\u8584\u51b0" not in alice_context
    assert "\u5982\u5c65\u8584\u51b0" in ice_context
    assert "\u7231\u4e3d\u4e1d" not in ice_context


def test_candidate_contexts_keep_grouped_album_messages_together() -> None:
    messages = [
        DummyMessage(200, "\u5267\u96c6\uff1a\u5357\u90e8\u6863\u6848\uff082026\uff09", grouped_id=1),
        DummyMessage(201, "\u7b2c 12 \u96c6 1080p", grouped_id=1),
        DummyMessage(202, "\u94fe\u63a5\uff1ahttps://115.com/s/south?password=3333", grouped_id=1),
    ]

    contexts = telegram_candidate_link_contexts(messages)

    context = contexts["https://115.com/s/south?password=3333"]
    assert "\u5357\u90e8\u6863\u6848" in context
    assert "1080p" in context
