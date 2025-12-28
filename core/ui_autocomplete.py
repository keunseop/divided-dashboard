from __future__ import annotations

import streamlit as st

from core.ticker_lookup import TickerSuggestion, find_ticker_candidates

try:
    from streamlit_searchbox import st_searchbox
except ImportError:  # pragma: no cover - optional dependency
    st_searchbox = None

_SEARCHBOX_CACHE_KEY = "_ticker_autocomplete_cache"


def _cache_entry(key: str) -> dict:
    """Ensure cache entry exists and normalize legacy structures."""
    bucket = st.session_state.setdefault(_SEARCHBOX_CACHE_KEY, {})
    entry = bucket.get(key)
    if entry is None:
        entry = {"options": {}, "selection": None}
    elif "options" not in entry or "selection" not in entry:
        options = entry if isinstance(entry, dict) else {}
        entry = {"options": options, "selection": None}
    bucket[key] = entry
    return entry


def _store_suggestions(key: str, suggestions: list[TickerSuggestion]) -> None:
    entry = _cache_entry(key)
    entry["options"] = {suggestion.display: suggestion for suggestion in suggestions}
    if entry["selection"] not in entry["options"]:
        entry["selection"] = None


def _pick_suggestion_from_cache(key: str, selection: str | None) -> TickerSuggestion | None:
    entry = _cache_entry(key)
    target_selection = selection if selection else entry.get("selection")
    if not target_selection:
        return None

    suggestion = entry["options"].get(target_selection)
    if selection:
        entry["selection"] = target_selection if suggestion else None
    return suggestion


def render_ticker_autocomplete(
    *,
    query: str | None = None,
    label: str,
    key: str,
    help_text: str | None = None,
    limit: int = 20,
    show_input: bool = True,
) -> TickerSuggestion | None:
    """Render an autocomplete widget for ticker suggestions.

    When streamlit-searchbox is installed, this shows a dynamic dropdown. Otherwise,
    it falls back to a static selectbox fed by the current query string.
    """

    if st_searchbox is not None:
        with st.container():
            st.write(label)
            if help_text:
                st.caption(help_text)

            def _search(term: str) -> list[str]:
                suggestions = find_ticker_candidates(term, limit=limit)
                _store_suggestions(key, suggestions)
                return [suggestion.display for suggestion in suggestions]

            selection = st_searchbox(
                search_function=_search,
                key=f"{key}_searchbox",
                placeholder="종목명 또는 코드를 입력해 주세요.",
            )
        return _pick_suggestion_from_cache(key, selection)

    # Fallback: use selectbox based on the existing query input.
    stripped = (query or "").strip()
    if not stripped and show_input:
        fallback_value = st.text_input(
            f"{label} 검색",
            value="",
            key=f"{key}_fallback_input",
            placeholder="종목명 또는 코드를 입력해 주세요.",
            help=help_text,
        )
        stripped = fallback_value.strip()
    if not stripped:
        return None

    suggestions = find_ticker_candidates(stripped, limit=limit)
    if not suggestions:
        st.info("일치하는 종목이 없습니다. 다른 키워드를 입력해 주세요.")
        return None

    option = st.selectbox(
        label,
        options=list(range(len(suggestions))),
        format_func=lambda idx: suggestions[idx].display,
        key=f"{key}_select",
        help=help_text,
    )
    return suggestions[option]
