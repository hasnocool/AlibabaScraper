# src/alibaba_scraper/discovery.py
"""Alibaba search URL construction and product-link discovery."""

import re
from urllib.parse import parse_qsl, quote_plus, urlencode, urljoin, urlsplit, urlunsplit

from selectolax.parser import HTMLParser

from .models import SearchResult

PRODUCT_ID_RE = re.compile(r"_(?P<product_id>\d{6,})\.html(?:$|[?#])", re.IGNORECASE)
PRODUCT_PATH_RE = re.compile(r"/product-detail/[^?#]+?_(\d{6,})\.html", re.IGNORECASE)
TRACKING_QUERY_PREFIXES = ("spm", "from", "scm", "pvid", "src", "utm_")


def build_search_url(query: str, page: int = 1) -> str:
    """Build the current public Alibaba product-search URL."""
    if page < 1:
        raise ValueError("page must be >= 1")
    encoded = quote_plus(query.strip())
    return (
        "https://www.alibaba.com/search/page"
        f"?SearchScene=proSearch&SearchText={encoded}&page={page}"
    )


def extract_product_id(url: str) -> str | None:
    """Extract Alibaba's numeric product id from a product-detail URL."""
    match = PRODUCT_ID_RE.search(url)
    return match.group("product_id") if match else None


def canonicalize_product_url(url: str, base_url: str = "https://www.alibaba.com/") -> str | None:
    """Return a stable public product-detail URL or ``None`` for unrelated links."""
    absolute = urljoin(base_url, url)
    split = urlsplit(absolute)
    host = split.netloc.lower()
    if host not in {"www.alibaba.com", "m.alibaba.com"}:
        return None
    if not PRODUCT_PATH_RE.search(split.path):
        return None

    kept_query = [
        (key, value)
        for key, value in parse_qsl(split.query, keep_blank_values=True)
        if not key.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    query = urlencode(kept_query, doseq=True)
    return urlunsplit(("https", "www.alibaba.com", split.path, query, ""))


def parse_search_results(
    html: str,
    base_url: str = "https://www.alibaba.com/",
) -> list[SearchResult]:
    """Extract and deduplicate product URLs from a public search result page."""
    tree = HTMLParser(html)
    seen: set[str] = set()
    results: list[SearchResult] = []

    for node in tree.css("a[href]"):
        href = node.attributes.get("href")
        if not href:
            continue
        canonical = canonicalize_product_url(href, base_url)
        if canonical is None or canonical in seen:
            continue
        seen.add(canonical)
        title = node.attributes.get("title") or node.text(strip=True) or None
        results.append(
            SearchResult(
                url=canonical,
                product_id=extract_product_id(canonical),
                title=title,
            )
        )

    return results
