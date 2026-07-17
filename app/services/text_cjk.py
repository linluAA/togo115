from __future__ import annotations

"""CJK text utilities public facade."""

from app.services.text_cjk_ops import (
    normalize_cjk_for_match,
    query_match_aliases,
    simplify_cjk,
    title_prefix_aliases,
)
from app.services.text_cjk_tables import *  # noqa: F401,F403

__all__ = [
    "simplify_cjk",
    "normalize_cjk_for_match",
    "title_prefix_aliases",
    "query_match_aliases",
]
