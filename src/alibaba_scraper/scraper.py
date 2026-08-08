# src/alibaba_scraper/scraper.py
"""Asynchronous network and parsing layer."""

import asyncio
from collections.abc import Iterable

import httpx
from selectolax.parser import HTMLParser

from .config import Settings
from .models import ProductRecord


class AlibabaScraper:
    """Bounded async scraper for publicly accessible product pages.

    The parser is deliberately conservative. Alibaba changes markup frequently,
    so selectors should be maintained in one place rather than spread through
    the application.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrency)
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

    async def fetch_product(self, url: str) -> ProductRecord:
        """Fetch and normalize one public product page."""
        async with self._semaphore:
            response = await self._client.get(url)
            response.raise_for_status()

            # Rate-limit without blocking the event loop.
            await asyncio.sleep(1.0 / self.settings.requests_per_second)

        return self.parse_product(url, response.text)

    async def fetch_many(self, urls: Iterable[str]) -> list[ProductRecord | Exception]:
        """Fetch multiple URLs concurrently while preserving input order."""
        tasks = [self.fetch_product(url) for url in urls]
        return list(await asyncio.gather(*tasks, return_exceptions=True))

    @staticmethod
    def parse_product(url: str, html: str) -> ProductRecord:
        """Parse a product page using stable fallbacks where possible."""
        tree = HTMLParser(html)

        title_node = tree.css_first("h1")
        title = title_node.text(strip=True) if title_node else None

        image_urls: list[str] = []
        for node in tree.css("img"):
            src = node.attributes.get("src") or node.attributes.get("data-src")
            if src and src.startswith(("http://", "https://")):
                image_urls.append(src)

        # Deduplicate while retaining page order and cap initial noise.
        unique_images = list(dict.fromkeys(image_urls))[:20]

        return ProductRecord(
            source_url=url,
            title=title,
            image_urls=unique_images,
        )
