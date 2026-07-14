from app.services.adapters.telegram.scan.message_context import TelegramMessageContextMixin


class DummyButton:
    def __init__(self, text: str):
        self.text = text
        self.url = None
        self.button = None


class DummyMessage:
    def __init__(self, message_id: int, text: str, buttons=None, grouped_id=None):
        self.id = message_id
        self.message = text
        self.text = text
        self.raw_text = text
        self.buttons = buttons
        self.grouped_id = grouped_id


class ContextHarness(TelegramMessageContextMixin):
    pass


def test_button_sibling_with_different_resource_title_is_not_merged() -> None:
    harness = ContextHarness()
    base = DummyMessage(100, "后室 2026")
    sibling = DummyMessage(101, "我的王室死对头（2026）", [[DummyButton("115")]])

    assert not harness._should_merge_sibling(base, sibling, True, ["后室 2026"])


def test_adjacent_button_only_sibling_can_be_merged() -> None:
    harness = ContextHarness()
    base = DummyMessage(100, "后室 2026")
    sibling = DummyMessage(101, "", [[DummyButton("115")]])

    assert harness._should_merge_sibling(base, sibling, True, ["后室 2026"])
