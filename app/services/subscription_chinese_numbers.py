from __future__ import annotations


CHINESE_DIGITS = {
    "\u96f6": 0,
    "\u3007": 0,
    "\u4e00": 1,
    "\u4e8c": 2,
    "\u4e24": 2,
    "\u4e09": 3,
    "\u56db": 4,
    "\u4e94": 5,
    "\u516d": 6,
    "\u4e03": 7,
    "\u516b": 8,
    "\u4e5d": 9,
    "\u58f9": 1,
    "\u8d30": 2,
    "\u8cb3": 2,
    "\u53c1": 3,
    "\u8086": 4,
    "\u4f0d": 5,
    "\u9646": 6,
    "\u9678": 6,
    "\u67d2": 7,
    "\u634c": 8,
    "\u7396": 9,
}


def _chinese_number_to_int(text: str) -> int | None:
    normalized = text.strip().replace("\u62fe", "\u5341")
    if normalized == "\u5341":
        return 10
    if "\u5341" in normalized:
        left, _, right = normalized.partition("\u5341")
        tens = CHINESE_DIGITS.get(left, 1 if not left else 0)
        ones = CHINESE_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones if tens else None
    if len(normalized) == 1:
        return CHINESE_DIGITS.get(normalized)
    return _plain_chinese_digits_to_int(normalized)


def _plain_chinese_digits_to_int(text: str) -> int | None:
    number = 0
    for char in text:
        if char not in CHINESE_DIGITS:
            return None
        number = number * 10 + CHINESE_DIGITS[char]
    return number or None
