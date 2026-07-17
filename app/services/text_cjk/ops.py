from __future__ import annotations

"""CJK normalize/alias helpers."""

from app.services.text_cjk.tables import _SPACE_RE, _TITLE_PREFIX_ALIASES, _TRAD_TO_SIMP

def simplify_cjk(text: str | None) -> str:
    value = str(text or "")
    if not value:
        return ""
    return "".join(_TRAD_TO_SIMP.get(char, char) for char in value)


def normalize_cjk_for_match(text: str | None) -> str:
    """Canonicalize text before compact matching / local query filters."""
    return simplify_cjk(text)


def title_prefix_aliases(title: str | None) -> list[str]:
    """Return original title plus common franchise-prefix stripped forms.

    Example: 新攻壳机动队 -> [新攻壳机动队, 攻壳机动队]
    """
    raw = _SPACE_RE.sub(" ", str(title or "").strip())
    if not raw:
        return []
    aliases = [raw]
    for prefix in _TITLE_PREFIX_ALIASES:
        if raw.startswith(prefix) and len(raw) - len(prefix) >= 2:
            stripped = raw[len(prefix):].lstrip(" ·・:-—–")
            if stripped and stripped not in aliases:
                aliases.append(stripped)
    return aliases


def query_match_aliases(query: str | None) -> list[str]:
    """Expand a search/filter query for CJK title variance."""
    raw = _SPACE_RE.sub(" ", str(query or "").strip())
    if not raw:
        return []
    aliases: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        normalized = _SPACE_RE.sub(" ", str(value or "").strip())
        if not normalized:
            return
        key = normalized.casefold()
        if key in seen:
            return
        seen.add(key)
        aliases.append(normalized)

    for item in title_prefix_aliases(raw):
        add(item)
        simplified = simplify_cjk(item)
        add(simplified)
    return aliases
