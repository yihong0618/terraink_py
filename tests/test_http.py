from __future__ import annotations

from terraink_py.http import CachedHttpClient


def test_cache_path_includes_request_headers(tmp_path) -> None:
    client = CachedHttpClient(
        cache_dir=tmp_path,
        user_agent="terraink/0.1",
        timeout_seconds=30,
    )

    english = client._cache_path(
        "GET",
        "https://example.com/search?q=sydney",
        None,
        {"Accept-Language": "en"},
    )
    chinese = client._cache_path(
        "GET",
        "https://example.com/search?q=sydney",
        None,
        {"Accept-Language": "zh-CN"},
    )

    assert english is not None
    assert chinese is not None
    assert english != chinese


def test_cache_path_ignores_header_order(tmp_path) -> None:
    client = CachedHttpClient(
        cache_dir=tmp_path,
        user_agent="terraink/0.1",
        timeout_seconds=30,
    )

    first = client._cache_path(
        "GET",
        "https://example.com/search?q=sydney",
        None,
        {"Accept-Language": "en", "X-Test": "1"},
    )
    second = client._cache_path(
        "GET",
        "https://example.com/search?q=sydney",
        None,
        {"X-Test": "1", "Accept-Language": "en"},
    )

    assert first == second
