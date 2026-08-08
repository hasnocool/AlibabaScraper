# tests/test_parser.py
"""Parser unit tests."""

from alibaba_scraper.scraper import AlibabaScraper


def test_parse_product_title_and_image() -> None:
    html = """
    <html>
      <body>
        <h1>Example Product</h1>
        <img src="https://example.com/product.jpg">
      </body>
    </html>
    """

    record = AlibabaScraper.parse_product("https://www.alibaba.com/product-detail/example", html)

    assert record.title == "Example Product"
    assert str(record.image_urls[0]) == "https://example.com/product.jpg"
