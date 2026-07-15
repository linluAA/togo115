from __future__ import annotations

from app.services.adapters.telegram.scan.message_links import TelegramMessageLinkMixin


class Harness(TelegramMessageLinkMixin):
    pass


def test_filter_link_contexts_requires_title_query_match() -> None:
    harness = Harness()
    contexts = {
        "https://115.com/s/swsbls23ndb?password=KMKM": "名称: 念念相忘.Just.for.Meeting.You.2023.2160p\n链接：https://115.com/s/swsbls23ndb?password=KMKM",
        "https://115.com/s/ydgtlink?password=1111": "剧集：野狗骨头 2026\n链接：https://115.com/s/ydgtlink?password=1111",
    }
    filtered = harness._filter_link_contexts_by_query(contexts, ["野狗骨头"])
    assert list(filtered) == ["https://115.com/s/ydgtlink?password=1111"]
