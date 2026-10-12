from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from techdeals.adapters import get_adapter, list_sources
from techdeals.adapters.html_retailers import (
    CentralComputersAdapter,
    DisctechAdapter,
    DiskpricesAdapter,
    GoHarddriveAdapter,
    ServerorbitAdapter,
    ServerSupplyAdapter,
)
from techdeals.ingestion.contract import IngestionStatus, RawCapture

FETCHED_AT = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)

LEGACY_ROOT = Path(
    "/home/coldaine/TechdealsHandoff/scripts/ingest"
)


def _corpus(adapter: CentralComputersAdapter) -> Path | None:
    if adapter.fixture_path is None or not adapter.fixture_path.exists():
        return None
    return adapter.fixture_path


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_registry_discovers_all_html_retailers() -> None:
    sources = list_sources()
    for name in (
        "central_computers",
        "diskprices",
        "goharddrive",
        "serversupply",
        "serverorbit",
        "disctech",
    ):
        assert name in sources
        adapter = get_adapter(name)
        assert adapter.source_name == name
        assert adapter.fixture_path is not None


def test_html_retailer_captures_are_valid_raw_captures() -> None:
    for cls in (
        CentralComputersAdapter,
        DiskpricesAdapter,
        GoHarddriveAdapter,
        ServerSupplyAdapter,
        ServerorbitAdapter,
        DisctechAdapter,
    ):
        adapter = cls()
        if _corpus(adapter) is None:
            continue
        for capture in adapter.load_fixtures():
            RawCapture.model_validate(capture.model_dump())
            assert capture.source_listing_id
            assert capture.url
            assert "parse_error" not in capture.metadata


# ---------------------------------------------------------------------------
# central_computers
# ---------------------------------------------------------------------------

CC_JSONLD_PAGE = """
<html><body>
<script type="application/ld+json">
{"@type": "WebPage", "mainEntity": {"@type": "OfferCatalog", "itemListElement": [
  {"@type": "Product", "name": "Widget One", "sku": "SKU-1", "brand": "Acme",
   "category": "Widgets",
   "offers": {"price": 12.5, "url": "https://www.centralcomputer.com/widget-one.html",
              "availability": "https://schema.org/InStock"}},
  {"@type": "Product", "name": "Widget Two", "productID": "SKU-2",
   "offers": {"price": "30.00", "url": "https://www.centralcomputer.com/widget-two.html",
              "availability": "https://schema.org/OutOfStock"}}
]}}
</script>
<ul class="products">
  <li class="item product product-item"><div class="product-item-info" id="product-item-info_111">
    <a class="product-item-photo" href="https://www.centralcomputer.com/widget-one.html"></a>
    <div class="price-box"><span data-price-amount="12.5"></span>
      <span class="old-price"><span data-price-amount="15.0"></span></span></div>
  </div></li>
</ul>
</body></html>
"""

CC_CSS_PAGE = """
<html><body><ul class="products">
  <li class="item product product-item">
    <div class="product-item-info" id="product-item-info_452449">
      <a class="product-item-photo" href="/belkin-charger.html"></a>
      <strong class="product name product-item-name">
        <a class="product-item-link" href="/belkin-charger.html">Belkin Charger</a></strong>
      <div class="price-box" data-product-id="452449">
        <span data-price-amount="15.99"></span></div>
    </div>
  </li>
  <li class="item product product-item">
    <div class="product-item-info" id="product-item-info_452450">
      <a class="product-item-link" href="/quickview/catalog_product/view/id/777"
         title="SSD Drive">SSD</a>
      <div class="price-box"><span data-price-amount="89.00"></span>
        <span class="old-price"><span data-price-amount="99.00"></span></span></div>
    </div>
  </li>
</ul></body></html>
"""


def test_central_computers_jsonld_listing_page() -> None:
    adapter = CentralComputersAdapter()
    captures = list(adapter.parse_raw(CC_JSONLD_PAGE, fetched_at=FETCHED_AT))

    assert [c.source_listing_id for c in captures] == ["SKU-1", "SKU-2"]
    assert captures[0].url == "https://www.centralcomputer.com/widget-one.html"
    assert captures[0].payload_format == "json"
    assert captures[0].fetched_at == FETCHED_AT

    first = captures[0].metadata
    assert first["title"] == "Widget One"
    assert first["price"] == 12.5
    assert first["listed_price"] == 15.0
    assert first["availability"] == "InStock"
    assert first["manufacturer"] == "Acme"
    assert first["category_path"] == "Widgets"
    assert first["sku"] == "SKU-1"

    second = captures[1].metadata
    assert second["price"] == 30.0
    assert second["availability"] == "OutOfStock"
    assert second["listed_price"] is None
    assert second["manufacturer"] is None
    for capture in captures:
        RawCapture.model_validate(capture.model_dump())


def test_central_computers_css_fallback_without_jsonld() -> None:
    adapter = CentralComputersAdapter()
    captures = list(adapter.parse_raw(CC_CSS_PAGE, fetched_at=FETCHED_AT))

    assert [c.source_listing_id for c in captures] == ["452449", "777"]
    assert captures[0].url == "https://www.centralcomputer.com/belkin-charger.html"
    assert captures[0].payload_format == "html"
    assert captures[0].metadata["title"] == "Belkin Charger"
    assert captures[0].metadata["price"] == 15.99
    assert captures[0].metadata["listed_price"] is None

    assert captures[1].source_listing_id == "777"
    assert captures[1].metadata["price"] == 89.0
    assert captures[1].metadata["listed_price"] == 99.0
    assert captures[1].metadata["title"] == "SSD Drive"


def test_central_computers_page_without_products_is_flagged() -> None:
    adapter = CentralComputersAdapter()
    html = "<html><body><p>nothing here</p></body></html>"
    captures = list(adapter.parse_raw(html, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_items_found"
    assert captures[0].raw_payload == html
    RawCapture.model_validate(captures[0].model_dump())


def test_central_computers_load_fixtures_from_corpus() -> None:
    adapter = CentralComputersAdapter()
    if _corpus(adapter) is None:
        pytest.skip("legacy fixture corpus not available")

    captures = list(adapter.load_fixtures())
    assert len(captures) == 96
    assert captures[0].source_listing_id == "POWBEL8DQWHR"
    assert captures[0].metadata["price"] == 15.99
    assert captures[0].metadata["availability"] == "InStock"
    assert captures[0].metadata["manufacturer"] == "Belkin"
    assert captures[0].metadata["category_path"] == "All Products"
    discounted = [c for c in captures if c.metadata["listed_price"] is not None]
    assert len(discounted) == 2
    assert {c.metadata["product_id"] for c in discounted} == {"GAMMOZRS078R", "GAMMOZAS004R"}
    for capture in captures:
        assert capture.source == "central_computers"
        assert "parse_error" not in capture.metadata


# ---------------------------------------------------------------------------
# diskprices
# ---------------------------------------------------------------------------


def _dp_table(headers: str, rows: str) -> str:
    return (
        "<html><body><table><thead><tr>" + headers + "</tr></thead><tbody>" + rows + "</tbody>"
        "</table></body></html>"
    )


DP_HEADERS = (
    "<th>Price per GB</th><th>Price per TB</th><th>Price</th><th>Capacity</th>"
    "<th>Warranty</th><th>Form</th><th>Type</th><th>Condition</th><th>Name</th>"
)
DP_ROW = (
    "<tr><td>$0.0125</td><td>$12.50</td><td>$100.00</td><td>8 TB</td><td>3 years</td>"
    '<td>3.5&quot;</td><td>HDD</td><td>New</td>'
    '<td><a href="https://www.amazon.com/dp/B08N5WRWNW">Seagate IronWolf 8TB</a></td></tr>'
)
DP_PACK_ROW = (
    "<tr><td>$0.0080</td><td>$8.00</td><td>$160.00</td><td>20 TB x10</td><td>1 year</td>"
    "<td>LTO</td><td>Tape</td><td>New</td>"
    '<td><a href="https://www.amazon.com/dp/B0TAPE1234">LTO Tape Pack</a></td></tr>'
)


def test_diskprices_parses_table_rows() -> None:
    adapter = DiskpricesAdapter()
    html = _dp_table(DP_HEADERS, DP_ROW + DP_PACK_ROW)
    captures = list(adapter.parse_raw(html, fetched_at=FETCHED_AT))

    assert len(captures) == 2
    first = captures[0]
    assert first.url == "https://www.amazon.com/dp/B08N5WRWNW"
    assert first.source_listing_id.startswith("disk-")
    meta = first.metadata
    assert meta["price_per_tb"] == 12.5
    assert meta["price"] == 100.0
    assert meta["capacity_raw"] == "8 TB"
    assert meta["tb_per_drive"] == 8.0
    assert meta["pack_count"] == 1
    assert meta["total_tb"] == 8.0
    assert meta["warranty"] == "3 years"
    assert meta["form_factor"] == '3.5"'
    assert meta["technology"] == "HDD"
    assert meta["condition"] == "New"
    assert meta["title"] == "Seagate IronWolf 8TB"

    second = captures[1].metadata
    assert second["pack_count"] == 10
    assert second["total_tb"] == 200.0
    for capture in captures:
        RawCapture.model_validate(capture.model_dump())


def test_diskprices_accepts_renamed_header_aliases() -> None:
    adapter = DiskpricesAdapter()
    headers = (
        "<th>Price per GB</th><th>Price per TB</th><th>Price</th><th>Capacity</th>"
        "<th>Warranty</th><th>Form Factor</th><th>Technology</th><th>Condition</th>"
        "<th>Affiliate Link</th>"
    )
    row = (
        "<tr><td>$0.0125</td><td>$12.50</td><td>$100.00</td><td>8 TB</td><td>3 years</td>"
        '<td>3.5&quot;</td><td>HDD</td><td>Used</td>'
        '<td><a href="https://www.amazon.com/dp/B08N5WRWNW">Disk</a></td></tr>'
    )
    captures = list(adapter.parse_raw(_dp_table(headers, row), fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["form_factor"] == '3.5"'
    assert captures[0].metadata["technology"] == "HDD"
    assert captures[0].metadata["title"] == "Disk"


def test_diskprices_refuses_renamed_critical_header() -> None:
    adapter = DiskpricesAdapter()
    headers = DP_HEADERS.replace("<th>Price</th>", "<th>Cost</th>")
    captures = list(adapter.parse_raw(_dp_table(headers, DP_ROW), fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert "refusing positional fallback" in capture.metadata["parse_error"]
    assert capture.status == IngestionStatus.raw
    RawCapture.model_validate(capture.model_dump())


def test_diskprices_headerless_table_falls_back_to_positions() -> None:
    adapter = DiskpricesAdapter()
    html = "<html><body><table>" + DP_ROW + "</table></body></html>"
    captures = list(adapter.parse_raw(html, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["price"] == 100.0
    assert captures[0].metadata["title"] == "Seagate IronWolf 8TB"


def test_diskprices_page_without_rows_is_flagged() -> None:
    adapter = DiskpricesAdapter()
    html = "<html><body><p>no table</p></body></html>"
    captures = list(adapter.parse_raw(html, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_items_found"


def test_diskprices_load_fixtures_from_corpus() -> None:
    adapter = DiskpricesAdapter()
    if _corpus(adapter) is None:
        pytest.skip("legacy fixture corpus not available")

    captures = list(adapter.load_fixtures())
    assert len(captures) == 2
    assert captures[0].metadata["title"] == "Seagate IronWolf 8TB"
    assert captures[1].metadata["pack_count"] == 10
    assert captures[1].metadata["total_tb"] == 200.0
    for capture in captures:
        assert capture.source == "diskprices"


# ---------------------------------------------------------------------------
# goharddrive
# ---------------------------------------------------------------------------

GHD_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.goHardDrive.com/</loc><lastmod>2026-09-23</lastmod></url>
<url><loc>https://www.goHardDrive.com/category-s/49.htm</loc><lastmod>2019-07-29</lastmod></url>
<url><loc>https://www.goHardDrive.com/Avolusion-250GB-p/g03-1391-win.htm</loc>
  <lastmod>2020-01-23</lastmod></url>
<url><loc>https://www.goHardDrive.com/Seagate-Exos-p/g01-1519-cr.htm</loc>
  <lastmod>2026-09-20</lastmod></url>
</urlset>
"""

GHD_PRODUCT_PAGE = """
<html><head>
<meta itemprop="manufacturer" content="Seagate">
<meta itemprop="itemCondition" content="Used">
<meta itemprop="availability" content="InStock">
</head><body>
<span itemprop="name">Seagate Exos 8TB Enterprise Drive</span>
<span itemprop="price" content="129.99"></span>
</body></html>
"""


def test_goharddrive_sitemap_yields_product_entries() -> None:
    adapter = GoHarddriveAdapter()
    captures = list(adapter.parse_raw(GHD_SITEMAP, fetched_at=FETCHED_AT))

    assert [c.source_listing_id for c in captures] == ["G03-1391-WIN", "G01-1519-CR"]
    assert captures[0].url == "https://www.goHardDrive.com/Avolusion-250GB-p/g03-1391-win.htm"
    assert captures[0].payload_format == "xml"
    meta = captures[0].metadata
    assert meta["record_kind"] == "sitemap_entry"
    assert meta["sku"] == "G03-1391-WIN"
    assert meta["lastmod"] == "2020-01-23"
    for capture in captures:
        RawCapture.model_validate(capture.model_dump())


def test_goharddrive_sitemap_without_products_is_flagged() -> None:
    adapter = GoHarddriveAdapter()
    html = "<urlset><url><loc>https://www.goHardDrive.com/</loc></url></urlset>"
    captures = list(adapter.parse_raw(html, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_items_found"


def test_goharddrive_product_page_fields() -> None:
    adapter = GoHarddriveAdapter()
    url = "https://www.goHardDrive.com/Seagate-Exos-p/g01-1519-cr.htm"
    captures = list(adapter.parse_raw(GHD_PRODUCT_PAGE, source_url=url, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert capture.source_listing_id == "G01-1519-CR"
    assert capture.url == url
    assert capture.payload_format == "html"
    meta = capture.metadata
    assert meta["record_kind"] == "product"
    assert meta["sku"] == "G01-1519-CR"
    assert meta["title"] == "Seagate Exos 8TB Enterprise Drive"
    assert meta["price"] == 129.99
    assert meta["manufacturer"] == "Seagate"
    assert meta["condition_raw"] == "Used"
    assert meta["availability"] == "InStock"
    RawCapture.model_validate(capture.model_dump())


def test_goharddrive_out_of_stock_fallback() -> None:
    adapter = GoHarddriveAdapter()
    html = (
        "<html><body><span itemprop='name'>Old Drive</span>"
        "<div class='StockQuantity_OutOfStock'></div></body></html>"
    )
    captures = list(adapter.parse_raw(html, source_url="https://x/p/g02-1111.htm"))

    assert captures[0].metadata["availability"] == "OutOfStock"
    assert captures[0].metadata["price"] is None
    assert captures[0].metadata["condition_raw"] is None


def test_goharddrive_page_without_name_is_flagged() -> None:
    adapter = GoHarddriveAdapter()
    html = "<html><body><p>retired listing</p></body></html>"
    captures = list(adapter.parse_raw(html, source_url="https://x/p/g02-2222.htm"))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_product_name"
    assert captures[0].raw_payload == html
    RawCapture.model_validate(captures[0].model_dump())


def test_goharddrive_load_fixtures_from_corpus() -> None:
    adapter = GoHarddriveAdapter()
    if _corpus(adapter) is None:
        pytest.skip("legacy fixture corpus not available")

    captures = list(adapter.load_fixtures())
    assert len(captures) == 4

    products = [c for c in captures if c.metadata["record_kind"] == "product"]
    entries = [c for c in captures if c.metadata["record_kind"] == "sitemap_entry"]
    assert {c.source_listing_id for c in products} == {"G01-1519-CR", "G03-1391-WIN"}
    assert {c.source_listing_id for c in entries} == {"G01-1519-CR", "G03-1391-WIN"}

    by_id = {c.source_listing_id: c for c in products}
    g01 = by_id["G01-1519-CR"]
    assert g01.metadata["price"] == 399.95
    assert g01.metadata["manufacturer"] == "Seagate"
    assert g01.metadata["availability"] == "OutOfStock"
    assert g01.metadata["condition_raw"] == "SED"
    assert g01.metadata["title"].startswith("Seagate Exos X16 ST14000NM005G 14TB")

    g03 = by_id["G03-1391-WIN"]
    assert g03.metadata["price"] == 29.99
    assert g03.metadata["availability"] == "InStock"
    assert g03.metadata["manufacturer"] == "Avolusion"


# ---------------------------------------------------------------------------
# serversupply
# ---------------------------------------------------------------------------

SS_LISTING_PAGE = """
<html><body><h5>2 items found for "TEST"</h5>
<div class="productbox">
  <div class="imgBox"><a href="/CAT/ST1234_555.htm"><img alt="ST1234"></a></div>
  <div class="ptitle">
    <a class="pdes" href="/CAT/ST1234_555.htm">
      <p>New | Seagate Drive ST1234 600GB SAS HDD</p></a>
  </div>
  <div class="pcost">$75.00<span class="wpcost">$100.00</span></div>
</div>
<div class="productbox">
  <div class="ptitle">
    <a class="pdes" href="/CAT/PLAIN_666.htm"><p>Plain Drive Without Prefix</p></a>
  </div>
  <div class="pcost">$40.00</div>
</div>
</body></html>
"""


def test_serversupply_listing_page_cards() -> None:
    adapter = ServerSupplyAdapter()
    captures = list(
        adapter.parse_raw(
            SS_LISTING_PAGE, fetched_at=FETCHED_AT, metadata={"category_path": "hard-drives"}
        )
    )

    assert [c.source_listing_id for c in captures] == ["555", "666"]
    first = captures[0]
    assert first.url == "https://www.serversupply.com/CAT/ST1234_555.htm"
    assert first.payload_format == "html"
    meta = first.metadata
    assert meta["condition_raw"] == "New"
    assert meta["title"] == "Seagate Drive ST1234 600GB SAS HDD"
    assert meta["price"] == 75.0
    assert meta["listed_price"] == 100.0
    assert meta["model_number"] == "ST1234"
    assert meta["category_path"] == "hard-drives"

    second = captures[1].metadata
    assert second["condition_raw"] is None
    assert second["title"] == "Plain Drive Without Prefix"
    assert second["price"] == 40.0
    assert second["listed_price"] is None
    for capture in captures:
        RawCapture.model_validate(capture.model_dump())


def test_serversupply_page_without_products_is_flagged() -> None:
    adapter = ServerSupplyAdapter()
    html = "<html><body><p>0 items found</p></body></html>"
    captures = list(adapter.parse_raw(html, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_items_found"


def test_serversupply_load_fixtures_from_corpus() -> None:
    adapter = ServerSupplyAdapter()
    if _corpus(adapter) is None:
        pytest.skip("legacy fixture corpus not available")

    captures = list(adapter.load_fixtures())
    assert len(captures) == 20
    first = captures[0]
    assert first.source_listing_id == "191875"
    assert first.metadata["condition_raw"] == "Refurbished"
    assert first.metadata["price"] == 35.0
    assert first.metadata["listed_price"] == 60.0
    assert first.metadata["model_number"] == "ST300MM0006"
    assert first.url.endswith("ST300MM0006_191875.htm")
    for capture in captures:
        assert capture.source == "serversupply"


# ---------------------------------------------------------------------------
# serverorbit
# ---------------------------------------------------------------------------

SO_LISTING_PAGE = """
<html><body>
  <div class="ty-discount-banner">
    <span class="ty-discount-notice">Extra 7% checkout discount applied automatically</span>
  </div>
  <div class="ty-grid-list">
    <div class="ty-grid-list__item ut2-gl__body" id="product_101">
      <div class="ty-grid-list__item-name">
        <a href="https://serverorbit.com/samsung-ssd.html" class="product-title">
          Samsung PM9A1 1.92TB NVMe SSD</a>
      </div>
      <div class="ty-control-group ty-sku">
        <span class="ty-control-group__label">SKU / MPN:</span>
        <span class="ty-control-group__item" id="sku_101">MZ-V9P1T0B/AM</span>
      </div>
      <div class="ty-product-feature">
        <span class="ty-control-group__label">Brand / Manufacturer:</span>
        <span class="ty-control-group__item">Samsung</span>
      </div>
      <div class="ty-product-feature">
        <span class="ty-control-group__label">Condition:</span>
        <span class="ty-control-group__item">New / Sealed (NIB)</span>
      </div>
      <div class="ty-product-prices">
        <span class="ty-price-num">$189.99</span>
        <span class="ty-list-price">$249.99</span>
      </div>
      <div class="ty-qty-in-stock">
        <span class="ty-qty-in-stock__title">In Stock</span>
        <span class="ty-qty-in-stock__num">(15 available - Ships same day)</span>
      </div>
    </div>
    <div class="ty-column4"><p>not a product</p></div>
    <div class="ty-grid-list__item" id="product_102">
      <div class="ty-grid-list__item-name">
        <a href="https://serverorbit.com/intel-cpu.html" class="product-title">
          Intel Xeon Processor (CD8069504283004)</a>
      </div>
      <div class="ty-product-feature">
        <span class="ty-control-group__label">Condition:</span>
        <span class="ty-control-group__item">System Pull</span>
      </div>
      <div class="ty-product-prices"><span class="ty-price-num">$495.00</span></div>
    </div>
  </div>
</body></html>
"""


def test_serverorbit_grid_items() -> None:
    adapter = ServerorbitAdapter()
    captures = list(adapter.parse_raw(SO_LISTING_PAGE, fetched_at=FETCHED_AT))

    products = [c for c in captures if "parse_error" not in c.metadata]
    errors = [c for c in captures if "parse_error" in c.metadata]

    assert [c.source_listing_id for c in products] == ["MZ-V9P1T0B/AM", "CD8069504283004"]
    assert len(errors) == 1
    assert errors[0].metadata["parse_error"] == "missing_title"
    assert "not a product" in errors[0].raw_payload
    RawCapture.model_validate(errors[0].model_dump())

    first = products[0]
    assert first.url == "https://serverorbit.com/samsung-ssd.html"
    meta = first.metadata
    assert meta["title"] == "Samsung PM9A1 1.92TB NVMe SSD"
    assert meta["price"] == 189.99
    assert meta["listed_price"] == 249.99
    assert meta["manufacturer"] == "Samsung"
    assert meta["condition_raw"] == "New / Sealed (NIB)"
    assert meta["availability"] == "In Stock (15 available - Ships same day)"
    assert meta["product_id"] == "product_101"
    assert meta["discount_text"] == "Extra 7% checkout discount applied automatically"

    second = products[1].metadata
    assert second["sku"] == "CD8069504283004"
    assert second["listed_price"] is None
    assert second["availability"] == "In Stock"
    assert second["condition_raw"] == "System Pull"
    for capture in products:
        RawCapture.model_validate(capture.model_dump())


def test_serverorbit_item_without_price_is_flagged_not_dropped() -> None:
    adapter = ServerorbitAdapter()
    html = """
    <div class="ty-grid-list__item">
      <a href="/x.html" class="product-title">Drive (ST16000NM001G)</a>
    </div>
    """
    captures = list(adapter.parse_raw(html))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "missing_price"
    assert "Drive (ST16000NM001G)" in captures[0].raw_payload
    RawCapture.model_validate(captures[0].model_dump())


def test_serverorbit_sku_falls_back_to_title_parenthetical() -> None:
    adapter = ServerorbitAdapter()
    html = """
    <div class="ty-grid-list__item">
      <a href="/x.html" class="product-title">Drive (ST16000NM001G)</a>
      <span class="ty-price">$10.00</span>
    </div>
    """
    captures = list(adapter.parse_raw(html))

    assert captures[0].source_listing_id == "ST16000NM001G"
    assert captures[0].metadata["sku"] == "ST16000NM001G"
    assert captures[0].metadata["price"] == 10.0


def test_serverorbit_page_without_items_is_flagged() -> None:
    adapter = ServerorbitAdapter()
    html = "<html><body><p>empty grid</p></body></html>"
    captures = list(adapter.parse_raw(html, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_items_found"


def test_serverorbit_load_fixtures_from_corpus() -> None:
    adapter = ServerorbitAdapter()
    if _corpus(adapter) is None:
        pytest.skip("legacy fixture corpus not available")

    captures = list(adapter.load_fixtures())
    assert len(captures) == 3
    assert [c.source_listing_id for c in captures] == [
        "MZ-V9P1T0B/AM",
        "ST16000NM001G",
        "CD8069504283004",
    ]
    assert captures[0].metadata["price"] == 189.99
    assert captures[0].metadata["manufacturer"] == "Samsung"
    assert captures[1].metadata["condition_raw"] == "Refurbished"
    assert captures[2].metadata["price"] == 495.0
    assert captures[2].metadata["availability"] == "Out of Stock"
    for capture in captures:
        assert capture.metadata["discount_text"] == (
            "Extra 7% checkout discount applied automatically"
        )


# ---------------------------------------------------------------------------
# disctech
# ---------------------------------------------------------------------------

DT_ENV = """
SC.CATEGORIES = [{"name": "Root", "fullurl": "/root", "categories": [
  {"name": "Leaf A", "fullurl": "/root/leaf-a", "internalid": "101", "categories": []},
  {"name": "Branch", "fullurl": "/root/branch", "internalid": "102", "categories": [
    {"name": "Leaf B", "fullurl": "/root/branch/leaf-b", "internalid": "103", "categories": []}
  ]}
]}];
"""

DT_LISTING_PAGE = """
<html><body>
<div class="facets-item-cell-list" data-item-id="17037" data-sku="DEL-345-BHSC-BN-OE"
     data-track-productlist-category="/storage/ssd">
  <a class="facets-item-cell-list-anchor" href="/Dell-345-BHSC-SSD" title="Dell SSD 960GB"></a>
  <h2 class="facets-item-cell-list-title">
    <a class="facets-item-cell-list-name" href="/Dell-345-BHSC-SSD" title="Dell SSD 960GB">
      <span>ignored</span></a></h2>
  <div class="facets-item-cell-list-price">
    <span class="product-price product-views-price-lead"> $799.00 </span>
    <span class="product-views-price-old">$899.00</span>
  </div>
  <div class="product-line-stock">In Stock</div>
</div>
<div class="facets-item-cell-list" data-sku="ABC-123-RF-OE">
  <a href="/Abc-Drive">Abc Drive</a>
  <span class="product-price product-views-price-lead">$50.00</span>
</div>
<div class="facets-item-cell-list"><a href="/no-ids">No ids</a></div>
</body></html>
"""


def test_disctech_categories_env_yields_leaf_categories() -> None:
    adapter = DisctechAdapter()
    captures = list(adapter.parse_raw(DT_ENV, fetched_at=FETCHED_AT))

    assert [c.source_listing_id for c in captures] == ["101", "103"]
    first = captures[0]
    assert first.payload_format == "json"
    assert first.url == "https://www.disctech.com/root/leaf-a"
    meta = first.metadata
    assert meta["record_kind"] == "category"
    assert meta["category_name"] == "Leaf A"
    assert meta["category_path"] == "root/leaf-a"
    assert meta["department"] == "root"
    assert json.loads(first.raw_payload)["name"] == "Leaf A"
    for capture in captures:
        RawCapture.model_validate(capture.model_dump())


def test_disctech_malformed_categories_payload_is_flagged() -> None:
    adapter = DisctechAdapter()
    for payload in ("SC.CATEGORIES = [oops];", "SC.CATEGORIES = 5;"):
        captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))
        assert len(captures) == 1
        assert "parse_error" in captures[0].metadata
        RawCapture.model_validate(captures[0].model_dump())


def test_disctech_listing_page_cells() -> None:
    adapter = DisctechAdapter()
    captures = list(adapter.parse_raw(DT_LISTING_PAGE, fetched_at=FETCHED_AT))

    assert [c.source_listing_id for c in captures] == ["17037", "ABC-123-RF-OE"]
    first = captures[0]
    assert first.url == "https://www.disctech.com/Dell-345-BHSC-SSD"
    meta = first.metadata
    assert meta["record_kind"] == "product"
    assert meta["sku"] == "DEL-345-BHSC-BN-OE"
    assert meta["title"] == "Dell SSD 960GB"
    assert meta["price"] == 799.0
    assert meta["listed_price"] == 899.0
    assert meta["availability"] == "In Stock"
    assert meta["condition_raw"] == "Brand New OEM"
    assert meta["category_path"] == "storage/ssd"

    second = captures[1].metadata
    assert second["item_id"] == "ABC-123-RF-OE"
    assert second["condition_raw"] == "Refurbished OEM"
    assert second["availability"] is None
    for capture in captures:
        RawCapture.model_validate(capture.model_dump())


def test_disctech_page_without_items_is_flagged() -> None:
    adapter = DisctechAdapter()
    html = "<html><body><p>no cells</p></body></html>"
    captures = list(adapter.parse_raw(html, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_items_found"


def test_disctech_load_fixtures_from_corpus() -> None:
    adapter = DisctechAdapter()
    if _corpus(adapter) is None:
        pytest.skip("legacy fixture corpus not available")

    captures = list(adapter.load_fixtures())
    products = [c for c in captures if c.metadata["record_kind"] == "product"]
    categories = [c for c in captures if c.metadata["record_kind"] == "category"]
    assert len(captures) == 93
    assert len(products) == 24
    assert len(categories) == 69

    first = products[0]
    assert first.source_listing_id == "17037"
    assert first.metadata["sku"] == "DEL-345-BHSC-BN-OE"
    assert first.metadata["condition_raw"] == "Brand New OEM"
    assert first.metadata["price"] == 799.0
    assert first.metadata["title"] == "Dell 345-BHSC 50VHM  050VHM PowerVault 960GB SED SSD Dell"
    assert first.metadata["category_path"] == "data-storage/internal-storage/ssd-solid-state-drives"

    assert categories[0].source_listing_id == "58"
    assert categories[0].metadata["category_name"] == "A/V Cables & Adapters"
    for capture in captures:
        assert capture.source == "disctech"


# ---------------------------------------------------------------------------
# shared behavior
# ---------------------------------------------------------------------------


def test_bytes_payload_is_accepted() -> None:
    adapter = ServerorbitAdapter()
    captures = list(adapter.parse_raw(SO_LISTING_PAGE.encode("utf-8"), fetched_at=FETCHED_AT))

    products = [c for c in captures if "parse_error" not in c.metadata]
    assert len(products) == 2
    assert products[0].source_listing_id == "MZ-V9P1T0B/AM"


def test_source_url_and_metadata_passthrough() -> None:
    adapter = CentralComputersAdapter()
    captures = list(
        adapter.parse_raw(
            CC_JSONLD_PAGE,
            source_url="https://www.centralcomputer.com/all-products.html?p=1",
            fetched_at=FETCHED_AT,
            metadata={"crawl_run": "2026-10-12"},
        )
    )

    assert captures[0].metadata["source_url"] == (
        "https://www.centralcomputer.com/all-products.html?p=1"
    )
    assert captures[0].metadata["crawl_run"] == "2026-10-12"
