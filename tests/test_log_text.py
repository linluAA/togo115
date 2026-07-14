import ast
from pathlib import Path


LOG_TEXT_FILES = [
    Path("app/services/subscription/search/service.py"),
    Path("app/services/subscription/search/flow.py"),
    Path("app/services/subscription/search/selection.py"),
    Path("app/services/subscription/delivery/link_validation.py"),
    Path("app/services/subscription/search/selection_logs.py"),
    Path("app/services/subscription/search/selection_fallback.py"),
    Path("app/services/subscription/search/discovery.py"),
    Path("app/services/subscription/attach/service.py"),
    Path("app/services/subscription/attach/match.py"),
    Path("app/services/subscription/delivery/service.py"),
    Path("app/services/subscription/delivery/executor.py"),
    Path("app/services/adapters/pan115.py"),
    Path("app/services/adapters/telegram/session/config.py"),
    Path("app/services/adapters/telegram/session/login.py"),
    Path("app/services/adapters/telegram/history/search.py"),
    Path("app/services/adapters/telegram/history/fast.py"),
    Path("app/services/adapters/telegram/history/recent.py"),
    Path("app/services/adapters/telegram/scan/message_links.py"),
    Path("app/services/adapters/telegram/scan/message_context.py"),
    Path("app/services/adapters/telegram/scan/button_links.py"),
    Path("app/services/link_telegram_hints.py"),
    Path("app/services/adapters/telegram/monitor.py"),
    Path("app/services/adapters/telegram/pipeline.py"),
    Path("app/services/adapters/telegram/bot/polling.py"),
    Path("app/db_logs.py"),
]

MOJIBAKE_FRAGMENTS = (
    "璁㈤",
    "鎼滅",
    "鍘嗗",
    "纾佸",
    "閾炬",
    "澶辫",
    "涓嶅",
    "淇濆",
    "鎶曢",
    "鍙戠",
    "寮傚",
    "鏍煎",
    "瀹炴",
    "鐩戞",
    "\u6902\u74a7",
    "\u52ec\u7c2e",
    "\u68f0\u52eb",
    "\u5c2e\u95b0",
    "\u9357\u6945",
    "\u5997\uff46",
    "\u9422\u4f43",
    "\u9353?",
    "\u93c8\u63a5\u70ba\u7a7a",
    "???",
    "€?",
)


def _string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def test_subscription_log_text_has_no_common_mojibake_fragments() -> None:
    hits: list[str] = []
    for path in LOG_TEXT_FILES:
        for value in _string_constants(path):
            if any(fragment in value for fragment in MOJIBAKE_FRAGMENTS):
                hits.append(f"{path}: {value}")

    assert hits == []


def test_app_source_has_no_question_mark_mojibake_runs() -> None:
    hits: list[str] = []
    for path in Path("app").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "???" in line:
                hits.append(f"{path}:{lineno}: {line.strip()}")

    assert hits == []
