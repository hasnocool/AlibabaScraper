# tests/test_discovery_variants.py
"""Current public Alibaba product URL variant tests."""

from alibaba_scraper.discovery import canonicalize_product_url, extract_product_id


def test_product_introduction_url_is_supported() -> None:
    url = (
        "https://www.alibaba.com/product-introduction/"
        "300w-Lithium-Battery-Solar-Portable-Lifepo4_1600984312491.html?spm=abc"
    )
    canonical = canonicalize_product_url(url)
    assert canonical is not None
    assert "spm=" not in canonical
    assert extract_product_id(canonical) == "1600984312491"


def test_wholesaler_product_detail_url_is_supported() -> None:
    url = (
        "https://wholesaler.alibaba.com/product-detail/"
        "GFB-ffh4d3-rechargeable-lifepo4-battery-3_1906993224.html"
    )
    canonical = canonicalize_product_url(url)
    assert canonical == url
    assert extract_product_id(canonical) == "1906993224"
