# src/alibaba_scraper/scraper.py
"""Asynchronous network, discovery, and product parsing layer."""

import asyncio
import json
import re
import time
from collections.abc import Iterable, Iterator
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from .config import Settings
from .discovery import build_search_url, extract_product_id, parse_search_results
from .models import PriceRange, PriceTier, ProductRecord, SearchResult

MOQ_RE = re.compile(
    r"(?:MOQ|Min(?:imum)?\.?\s*Order)\s*:?\s*"
    r"(?P<quantity>\d[\d,.]*)\s*(?P<unit>[A-Za-z][A-Za-z /.-]{0,30})",
    re.IGNORECASE,
)
TIER_RANGE_RE = re.compile(
    r"(?P<minimum>\d[\d,]*(?:\.\d+)?)\s*[-–]\s*"
    r"(?P<maximum>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>[A-Za-z][A-Za-z.-]{0,20})\s*"
    r"(?:US\s*)?\$(?P<price>\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)
TIER_OPEN_RE = re.compile(
    r"(?:>=|≥)\s*(?P<minimum>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>[A-Za-z][A-Za-z.-]{0,20})\s*"
    r"(?:US\s*)?\$(?P<price>\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)
COUNTRY_RE = re.compile(r"\b([A-Z][A-Za-z .'-]+),\s*(China|CN)\b")


class AsyncRateLimiter:
    """Coroutine-safe request-start limiter that never blocks a worker thread."""

    def __init__(self, requests_per_second: float) -> None:
        self._interval = 1.0 / requests_per_second
        self._next_allowed = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        """Wait until the next request start is permitted."""
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_allowed - now)
            if delay:
                await asyncio.sleep(delay)
                now = time.monotonic()
            self._next_allowed = max(now, self._next_allowed) + self._interval


class AlibabaScraper:
    """Bounded async collector for publicly accessible Alibaba pages."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrency)
        self._rate_limiter = AsyncRateLimiter(self.settings.requests_per_second)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.timeout_seconds),
            follow_redirects=True,
            http2=True,
            headers={"User-Agent": self.settings.user_agent},
        )

    async def __aenter__(self) -> "AlibabaScraper":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close open network resources."""
        await self._client.aclose()

    async def fetch_text(self, url: str) -> str:
        """Fetch one public page with bounded concurrency and async retry/backoff."""
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                await self._rate_limiter.wait()
                async with self._semaphore:
                    response = await self._client.get(url)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response.text
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt >= self.settings.max_retries:
                    raise
                delay = self.settings.retry_backoff_seconds * (2**attempt)
                if isinstance(exc, httpx.HTTPStatusError):
                    retry_after = exc.response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        delay = min(float(retry_after), 120.0)
                await asyncio.sleep(delay)

        raise RuntimeError("request retry loop exited unexpectedly") from last_error

    async def discover(self, query: str, page: int = 1) -> list[SearchResult]:
        """Discover public product-detail URLs from one search page."""
        search_url = build_search_url(query, page)
        html = await self.fetch_text(search_url)
        return parse_search_results(html, search_url)

    async def fetch_product(self, url: str) -> ProductRecord:
        """Fetch and normalize one public product page."""
        html = await self.fetch_text(url)
        return self.parse_product(url, html)

    async def fetch_many(self, urls: Iterable[str]) -> list[ProductRecord | Exception]:
        """Fetch multiple URLs concurrently while preserving input order."""
        tasks = [self.fetch_product(url) for url in urls]
        return list(await asyncio.gather(*tasks, return_exceptions=True))

    @staticmethod
    def parse_product(url: str, html: str) -> ProductRecord:
        """Parse stable metadata first, then use conservative HTML fallbacks."""
        tree = HTMLParser(html)
        json_objects = list(_json_ld_objects(tree))
        product_json = next((obj for obj in json_objects if _is_product(obj)), None)

        canonical_url = _canonical_url(tree, url)
        title = _product_title(tree, product_json)
        supplier_name, supplier_url = _supplier(tree, product_json, url)
        attributes = _attributes(tree, product_json)
        image_urls = _images(tree, product_json, url)
        page_text = tree.text(separator=" ", strip=True)
        price = _price(product_json, page_text)
        moq, moq_unit = _moq(product_json, page_text, price)

        country = None
        origin = attributes.get("Place of Origin") or attributes.get("place of origin")
        if origin:
            country = origin
        elif (match := COUNTRY_RE.search(page_text)) is not None:
            country = match.group(2)

        category = None
        if product_json:
            raw_category = product_json.get("category")
            if isinstance(raw_category, str):
                category = raw_category.strip() or None

        return ProductRecord(
            source_url=url,
            canonical_url=canonical_url,
            title=title,
            product_id=extract_product_id(canonical_url or url),
            supplier_name=supplier_name,
            supplier_url=supplier_url,
            supplier_country=country,
            category=category,
            minimum_order_quantity=moq,
            minimum_order_unit=moq_unit,
            price=price,
            image_urls=image_urls,
            attributes=attributes,
        )


def _json_ld_objects(tree: HTMLParser) -> Iterator[dict[str, Any]]:
    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text(strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        yield from _walk_json(payload)


def _walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _is_product(obj: dict[str, Any]) -> bool:
    raw_type = obj.get("@type")
    if isinstance(raw_type, str):
        return raw_type.lower() == "product"
    if isinstance(raw_type, list):
        return any(str(item).lower() == "product" for item in raw_type)
    return False


def _canonical_url(tree: HTMLParser, fallback: str) -> str:
    node = tree.css_first('link[rel="canonical"]')
    href = node.attributes.get("href") if node else None
    return urljoin(fallback, href) if href else fallback


def _product_title(tree: HTMLParser, product_json: dict[str, Any] | None) -> str | None:
    if product_json and isinstance(product_json.get("name"), str):
        return product_json["name"].strip() or None
    node = tree.css_first("h1")
    return node.text(strip=True) if node else None


def _supplier(
    tree: HTMLParser,
    product_json: dict[str, Any] | None,
    base_url: str,
) -> tuple[str | None, str | None]:
    if product_json:
        for key in ("seller", "manufacturer", "brand"):
            candidate = product_json.get(key)
            if isinstance(candidate, dict):
                name = candidate.get("name")
                supplier_url = candidate.get("url")
                if isinstance(name, str) and name.strip():
                    normalized_url = (
                        urljoin(base_url, supplier_url) if isinstance(supplier_url, str) else None
                    )
                    return name.strip(), normalized_url

    for node in tree.css('a[href*=".en.alibaba.com"], a[href*="trustpass.alibaba.com"]'):
        href = node.attributes.get("href")
        name = node.text(strip=True)
        if href and name:
            return name, urljoin(base_url, href)
    return None, None


def _images(
    tree: HTMLParser,
    product_json: dict[str, Any] | None,
    base_url: str,
) -> list[str]:
    images: list[str] = []
    if product_json:
        raw_images = product_json.get("image")
        if isinstance(raw_images, str):
            images.append(urljoin(base_url, raw_images))
        elif isinstance(raw_images, list):
            images.extend(urljoin(base_url, value) for value in raw_images if isinstance(value, str))

    for node in tree.css("img"):
        src = node.attributes.get("src") or node.attributes.get("data-src")
        if src and not src.startswith("data:"):
            images.append(urljoin(base_url, src))

    return list(dict.fromkeys(images))[:30]


def _attributes(tree: HTMLParser, product_json: dict[str, Any] | None) -> dict[str, str]:
    attributes: dict[str, str] = {}
    if product_json:
        additional = product_json.get("additionalProperty")
        if isinstance(additional, list):
            for item in additional:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                value = item.get("value")
                if isinstance(name, str) and value is not None:
                    attributes[name.strip()] = str(value).strip()

    for row in tree.css("tr"):
        cells = row.css("th,td")
        if len(cells) == 2:
            key = cells[0].text(separator=" ", strip=True)
            value = cells[1].text(separator=" ", strip=True)
            if key and value and len(key) <= 100 and len(value) <= 500:
                attributes.setdefault(key, value)
        if len(attributes) >= 100:
            break

    return attributes


def _price(product_json: dict[str, Any] | None, page_text: str) -> PriceRange | None:
    price = _price_from_json(product_json) if product_json else None
    tiers = _price_tiers_from_text(page_text)
    if price is None and not tiers:
        return None
    if price is None:
        values = [tier.price for tier in tiers]
        price = PriceRange(currency=_common_currency(tiers), minimum=min(values), maximum=max(values))
    price.tiers = tiers
    if price.minimum is None and tiers:
        price.minimum = min(tier.price for tier in tiers)
    if price.maximum is None and tiers:
        price.maximum = max(tier.price for tier in tiers)
    return price


def _price_from_json(product_json: dict[str, Any]) -> PriceRange | None:
    offers = product_json.get("offers")
    candidates = offers if isinstance(offers, list) else [offers]
    lows: list[Decimal] = []
    highs: list[Decimal] = []
    currency: str | None = None
    for offer in candidates:
        if not isinstance(offer, dict):
            continue
        currency = _normalize_currency(offer.get("priceCurrency")) or currency
        low = _decimal(offer.get("lowPrice") or offer.get("price"))
        high = _decimal(offer.get("highPrice") or offer.get("price"))
        if low is not None:
            lows.append(low)
        if high is not None:
            highs.append(high)
    if not lows and not highs:
        return None
    return PriceRange(
        currency=currency,
        minimum=min(lows or highs),
        maximum=max(highs or lows),
    )


def _price_tiers_from_text(text: str) -> list[PriceTier]:
    tiers: list[PriceTier] = []
    for regex, open_ended in ((TIER_RANGE_RE, False), (TIER_OPEN_RE, True)):
        for match in regex.finditer(text):
            minimum = _decimal(match.group("minimum"))
            maximum = None if open_ended else _decimal(match.groupdict().get("maximum"))
            amount = _decimal(match.group("price"))
            if minimum is None or amount is None:
                continue
            tiers.append(
                PriceTier(
                    minimum_quantity=minimum,
                    maximum_quantity=maximum,
                    unit=match.group("unit").strip(),
                    price=amount,
                    currency="USD",
                )
            )
    unique: dict[tuple[Decimal | None, Decimal | None, str | None, Decimal], PriceTier] = {}
    for tier in tiers:
        unique[(tier.minimum_quantity, tier.maximum_quantity, tier.unit, tier.price)] = tier
    return list(unique.values())[:20]


def _moq(
    product_json: dict[str, Any] | None,
    page_text: str,
    price: PriceRange | None,
) -> tuple[Decimal | None, str | None]:
    if product_json:
        for key in ("minimumOrderQuantity", "minOrderQuantity", "minimum_order_quantity"):
            value = product_json.get(key)
            if isinstance(value, dict):
                quantity = _decimal(value.get("value"))
                unit = value.get("unitText") or value.get("unitCode")
                if quantity is not None:
                    return quantity, str(unit) if unit else None
            quantity = _decimal(value)
            if quantity is not None:
                return quantity, None

    match = MOQ_RE.search(page_text)
    if match:
        return _decimal(match.group("quantity")), match.group("unit").strip()

    if price and price.tiers:
        first = min(
            (tier for tier in price.tiers if tier.minimum_quantity is not None),
            key=lambda tier: tier.minimum_quantity or Decimal(0),
            default=None,
        )
        if first:
            return first.minimum_quantity, first.unit
    return None, None


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _normalize_currency(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper().replace("US$", "USD").replace("$", "USD")
    return normalized or None


def _common_currency(tiers: list[PriceTier]) -> str | None:
    for tier in tiers:
        if tier.currency:
            return tier.currency
    return None
