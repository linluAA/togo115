from __future__ import annotations

from pathlib import Path

from app.services.subscription_chinese_numbers import CHINESE_DIGITS, _chinese_number_to_int


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".md", ".html", ".css", ".js", ".json", ".yml", ".yaml", ".txt"}
EXCLUDED_PARTS = {".venv", ".tools", ".helloagents", "data", "__pycache__", ".pytest_cache"}

MOJIBAKE_MARKERS = (
    "\u9435\u4f43\u4fca",
    "\u95b8\u6a3a",
    "\u95b9\u517c",
    "\u7f01\u65b2",
    "\u95c1\u5267",
    "\u5a62\u60f0",
    "\u5a11\u64b3",
    "\u5a23\u56e8",
    "\u7025\u8663",
    "\u943e\u572d",
    "\u951f\u65a4",
    "\u813f",
    "\u7039\u70b4",
    "\u6902\u74a7",
    "\u52ec\u7c2e",
    "\u68f0\u52eb",
    "\u5c2e\u95b0",
    "\u9357\u6945",
    "\u5997\uff46",
    "\u9422\u4f43",
    "\u9353?",
    "\u93c8\u63a5\u70ba\u7a7a",
    "\ufffd",
)

CRITICAL_PARSER_FILES = (
    Path("app/services/subscription_chinese_numbers.py"),
    Path("app/services/subscription_episode_explicit.py"),
    Path("app/services/subscription_episode_patterns.py"),
)


def iter_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path == Path(__file__).resolve():
            continue
        if path.name == "test_log_text.py":
            continue
        if any(part in EXCLUDED_PARTS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def test_text_files_do_not_contain_known_mojibake_markers() -> None:
    hits: list[str] = []
    for path in iter_text_files():
        text = path.read_text(encoding="utf-8")
        for marker in MOJIBAKE_MARKERS:
            if marker in text:
                hits.append(f"{path.relative_to(ROOT)} contains {marker!r}")
    assert not hits


def test_critical_episode_parser_files_do_not_contain_replacement_characters() -> None:
    hits: list[str] = []
    for relative_path in CRITICAL_PARSER_FILES:
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        if "\ufffd" in text:
            hits.append(str(relative_path))
    assert hits == []


def test_chinese_number_table_uses_native_literals() -> None:
    assert CHINESE_DIGITS["\u4e00"] == 1
    assert CHINESE_DIGITS["\u4e24"] == 2
    assert CHINESE_DIGITS["\u516b"] == 8
    assert _chinese_number_to_int("\u5341\u4e8c") == 12
    assert _chinese_number_to_int("\u4e8c\u5341\u516d") == 26
