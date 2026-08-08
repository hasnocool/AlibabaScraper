# tests/test_discovery.py
"""Search URL and result discovery tests."""

from alibaba_scraper.discovery import (
    build_search_url,
    canonicalize_product_url,
    extract_product_id,
    parse_search_results,
)


def test_build_search_url() -> None:
    url = build_search_url("solar panel", page=2)
    assert "SearchText=solar+panel" in url
    assert "page=2" in url


def test_product_url_canonicalization_and_id() -> None:
    url = (
        "//www.alibaba.com/product-detail/Example-Product_1601732011579.html"
        "?spm=a2700.foo&foo=bar"
    )
    canonical = canonicalize_product_url(url)
    assert canonical == (
        "https://www.alibaba.com/product-detail/Example-Product_1601732011579.html?foo=bar"
    )
    assert extract_product_id(canonical) == "1601732011579"


def test_parse_search_results_deduplicates() -> None:
    html = """
    <a href="//www.alibaba.com/product-detail/A_1601732011579.html?spm=1">A</a>
    <a href="https://www.alibaba.com/product-detail/A_1601732011579.html">A duplicate</a>
    <a href="https://example.com/product-detail/B_1600000000000.html">external</a>
    <a href="https://www.alibaba.com/about">not a product</a>
    """
    results = parse_search_results(html)
    assert len(results) == 1
    assert results[0].product_id == "1601732011579"
