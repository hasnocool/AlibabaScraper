# tests/test_parser.py
"""Product parser unit tests."""

from decimal import Decimal

from alibaba_scraper.scraper import AlibabaScraper


def test_parse_product_json_ld_and_fallbacks() -> None:
    html = """
    <html>
      <head>
        <link rel="canonical" href="https://www.alibaba.com/product-detail/Test_1601732011579.html">
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Example Solar Product",
          "image": ["https://example.com/product.jpg"],
          "category": "Solar Panels",
          "manufacturer": {
            "@type": "Organization",
            "name": "Example Manufacturing Co., Ltd.",
            "url": "https://example.en.alibaba.com/"
          },
          "additionalProperty": [
            {"@type":"PropertyValue","name":"Place of Origin","value":"Guangdong, China"},
            {"@type":"PropertyValue","name":"Model Number","value":"SP-100"}
          ],
          "offers": {
            "@type": "AggregateOffer",
            "lowPrice": "12.50",
            "highPrice": "18.00",
            "priceCurrency": "USD"
          }
        }
        </script>
      </head>
      <body>
        <h1>Fallback title</h1>
        <div>MOQ: 10 pieces</div>
      </body>
    </html>
    """

    record = AlibabaScraper.parse_product(
        "https://www.alibaba.com/product-detail/source_1601732011579.html",
        html,
    )

    assert record.product_id == "1601732011579"
    assert record.title == "Example Solar Product"
    assert record.supplier_name == "Example Manufacturing Co., Ltd."
    assert record.supplier_country == "Guangdong, China"
    assert record.category == "Solar Panels"
    assert record.minimum_order_quantity == Decimal("10")
    assert record.minimum_order_unit == "pieces"
    assert record.price is not None
    assert record.price.minimum == Decimal("12.50")
    assert record.price.maximum == Decimal("18.00")
    assert record.price.currency == "USD"
    assert record.attributes["Model Number"] == "SP-100"


def test_parse_visible_quantity_price_tiers() -> None:
    html = """
    <html><body>
      <h1>Tiered Product</h1>
      <div>20,000 - 399,999 watts $0.1662</div>
      <div>400,000 - 999,999 watts $0.1524</div>
      <div>&gt;= 1,000,000 watts $0.1385</div>
    </body></html>
    """
    record = AlibabaScraper.parse_product(
        "https://www.alibaba.com/product-detail/Tiered_1601771345931.html",
        html,
    )
    assert record.price is not None
    assert len(record.price.tiers) == 3
    assert record.minimum_order_quantity == Decimal("20000")
    assert record.minimum_order_unit == "watts"
