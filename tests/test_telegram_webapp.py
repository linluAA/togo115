from app.services.adapters.telegram_webapp import _telegram_oauth_error_message, _telegram_webapp_init_data


def test_telegram_webapp_init_data_from_fragment() -> None:
    url = "https://example.com/#tgWebAppData=query_id%3Dabc%26user%3D%257B%257D%26hash%3Dfff&tgWebAppVersion=7.0"

    assert _telegram_webapp_init_data(url) == "query_id=abc&user=%7B%7D&hash=fff"


def test_telegram_webapp_init_data_from_query() -> None:
    url = "https://example.com/?initData=query_id%3Dabc%26hash%3Dfff"

    assert _telegram_webapp_init_data(url) == "query_id=abc&hash=fff"


def test_telegram_oauth_error_message_has_fallback_detail() -> None:
    assert "Telegram OAuth login failed" in _telegram_oauth_error_message(RuntimeError("boom"))


class _SessionPasswordNeededError(Exception):
    pass


def test_telegram_oauth_error_message_handles_password_required() -> None:
    _SessionPasswordNeededError.__name__ = "SessionPasswordNeededError"

    assert "two-step verification" in _telegram_oauth_error_message(_SessionPasswordNeededError())
