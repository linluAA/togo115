from __future__ import annotations

from app.services.link_search_utils import _expanded_search_queries, _local_text_matches_query
from app.services.subscription.match.matching import compact_match_text, extra_search_keywords
from app.services.text_cjk import query_match_aliases, simplify_cjk, title_prefix_aliases


def test_simplify_ghost_in_the_shell_traditional_title() -> None:
    assert simplify_cjk("攻殻機動隊") == "攻壳机动队"
    assert compact_match_text("攻殻機動隊") == compact_match_text("攻壳机动队")


def test_title_prefix_aliases_strip_new_prefix() -> None:
    assert title_prefix_aliases("新攻壳机动队") == ["新攻壳机动队", "攻壳机动队"]
    assert "攻壳机动队" in query_match_aliases("新攻壳机动队")


def test_local_query_matches_traditional_card_with_simplified_new_title() -> None:
    context = "剧集：攻殻機動隊(2026)\n季集：S01E01-E02\nTMDB ID：255358"
    assert _local_text_matches_query(context, "新攻壳机动队")
    assert _local_text_matches_query("攻殻機動隊(2026) S01E01-E02", "新攻壳机动队")


def test_search_queries_include_prefix_stripped_alias() -> None:
    queries = _expanded_search_queries("新攻壳机动队", [], max_queries=8)
    assert "新攻壳机动队" in queries
    assert "攻壳机动队" in queries


def test_extra_search_keywords_include_prefix_stripped_alias() -> None:
    extras = extra_search_keywords({"title": "新攻壳机动队", "keywords": ["新攻壳机动队"]})
    assert "攻壳机动队" in extras
