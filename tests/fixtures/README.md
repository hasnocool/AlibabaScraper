# Sanitized Alibaba response fixtures

These fixtures preserve only the small public-data fragments needed for parser regression tests.
They are not complete page copies.

Captured/verified: 2026-08-08.

- `lifepo4_tiered_public.html` mirrors the public tier-price and supplier facts observed at
  `https://wholesaler.alibaba.com/product-detail/GFB-ffh4d3-rechargeable-lifepo4-battery-3_1906993224.html`.
- `power_station_public.html` mirrors the public tier-price facts observed at
  `https://www.alibaba.com/product-introduction/300w-Lithium-Battery-Solar-Portable-Lifepo4_1600984312491.html`.

Only title/supplier/price/MOQ-style fields used by the parser are retained.
