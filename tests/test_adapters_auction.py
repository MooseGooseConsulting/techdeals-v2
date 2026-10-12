from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from techdeals.adapters import get_adapter, list_sources
from techdeals.adapters.govdeals import GovDealsAdapter
from techdeals.adapters.liquidation import LiquidationComAdapter
from techdeals.ingestion.contract import IngestionStatus, RawCapture

FETCHED_AT = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)

GOVDEALS_ASSET = {
    "accountId": 30467,
    "assetId": 94,
    "auctionId": 1,
    "assetShortDesc": "Lot of 64 HP 32GB DDR4 ECC LRDIMM Server Memory",
    "assetLongDesc": "<p>64 modules. <strong>Used / surplus.</strong> Sold as-is.</p>",
    "companyName": "Abtron Computer Services, ON",
    "sellerTypeId": 2,
    "city": "North York",
    "state": "ON",
    "zipCode": "M3H 5S4",
    "currencyCode": "USD",
    "catDesc": "Computer accessories",
    "willShip": False,
    "assetConditionCd": "SD",
    "assetStatusCd": "STA",
    "assetPhotos": ["/photos/30467/30467_94_example.jpg"],
    "assetAttributeGroups": [
        {
            "name": "All",
            "assetAttributes": [
                {"label": "Condition", "value": "Used/See Description"},
                {"label": "Lot Number", "value": "30467-94"},
            ],
        }
    ],
    "removalInstructions": "<p>SHIPPING IS NOT AVAILABLE. Buyer pickup.</p>",
    "watch_priority": "worth",
    "judgment": {"skip_reason": "chat only"},
}

GOVDEALS_BIDBOX = {
    "accountId": 30467,
    "assetId": 94,
    "auctionId": 1,
    "assetStatusCd": "STA",
    "assetAuctionEndDateUTC": "2030-06-01T12:00:00Z",
    "currentBid": 7360.0,
    "bidCount": 1,
    "watcherCount": 17,
    "premiumPercent": 12.5,
    "hasReservePrice": False,
    "isReserveNotMet": False,
    "all_in_estimate_usd": 8280.0,
}

LISTING_CARD_HTML = """
<div class="item grid-group-item search_list_view" data-id="21256289">
  <a href="/auction/view?id=21256289">26TB, 8TB, 4TB, NAS, Desktop PC HDD / SSD Lot</a>
  <div class="current-bid">Current Bid: $3200.00</div>
  <div class="est-retail">Est. Retail: $11100.00</div>
  <a href="/seller/newegg">Newegg_Business</a>
  <div>Closing: Jun 25  9:15AM
  California | Returns | 3 Packages | 25 items
  1 bids 5 watchers 144 views</div>
</div>
"""

AUCTION_DETAIL_HTML = """
<h1>26TB, 8TB, 4TB, NAS, Desktop PC HDD / SSD Lot</h1>
<div>Current Bid: $3200.00</div>
<div>Minimum Bid: $3300.00</div>
<div>Est. Retail: $11,100.00</div>
<div>Closes: 06/25/2026 09:15 AM ET</div>
<div>Location: California</div>
<div>Seller: Newegg_Business</div>
<div>Buyer's Premium: 11%</div>
<div>Shipping Terms: Buyer pays shipping</div>
<div>25 items in lot</div>
<div>Auction Type: Standard</div>
<a href="/aucimg/21256/m21256289.html">View Manifest</a>
"""

MANIFEST_HTML = """
<table>
<tr><th>Description</th><th>Quantity</th><th>Retail Price</th><th>Ext Retail Price</th>
<th>Make</th><th>Model</th><th>Product Category</th></tr>
<tr><td>4TB - SAMSUNG SSD 990 PRO 4TB</td><td>2</td><td>1099.99</td><td>2199.98</td>
<td>SAMSUNG</td><td>MZ-V9P4T0B/AM</td><td>Solid State Disk</td></tr>
<tr><td>18TB - WD Red Pro NAS HDD</td><td>1</td><td>734.99</td><td>734.99</td>
<td>Western Digital</td><td>WD181KFGX</td><td>Hard Drives</td></tr>
</table>
"""

COMBINED_LOT_HTML = (
    f"<!-- listing_card_21256289.html -->\n{LISTING_CARD_HTML}\n\n"
    f"<!-- auction_detail_21256289.html -->\n{AUCTION_DETAIL_HTML}\n\n"
    f"<!-- manifest_21256289.html -->\n{MANIFEST_HTML}"
)

GOVDEALS_FIXTURES = Path("/home/coldaine/TechdealsHandoff/scripts/ingest/govdeals/fixtures")
LIQUIDATION_FIXTURES = Path(
    "/home/coldaine/TechdealsHandoff/scripts/ingest/liquidation_com/fixtures"
)


# --- GovDeals ---


def test_govdeals_combined_asset_and_bidbox() -> None:
    adapter = GovDealsAdapter()
    payload = json.dumps({"asset": GOVDEALS_ASSET, "bidbox": GOVDEALS_BIDBOX})
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert capture.source == "govdeals"
    assert capture.source_listing_id == "30467-94"
    assert capture.url == "https://www.govdeals.com/en/asset/94/30467"
    assert capture.payload_format == "json"
    assert capture.fetched_at == FETCHED_AT
    assert capture.status == IngestionStatus.raw
    assert capture.checksum == hashlib.sha256(payload.encode()).hexdigest()
    assert json.loads(capture.raw_payload) == {
        "asset": GOVDEALS_ASSET,
        "bidbox": GOVDEALS_BIDBOX,
    }
    RawCapture.model_validate(capture.model_dump())

    meta = capture.metadata
    assert meta["native_lot_id"] == "30467-94"
    assert meta["asset_id"] == 94
    assert meta["account_id"] == 30467
    assert meta["auction_id"] == 1
    assert meta["title"] == "Lot of 64 HP 32GB DDR4 ECC LRDIMM Server Memory"
    assert meta["description_html"] == GOVDEALS_ASSET["assetLongDesc"]
    assert meta["seller_name"] == "Abtron Computer Services, ON"
    assert meta["seller_type_id"] == 2
    assert meta["location"] == "North York, ON M3H 5S4"
    assert meta["city"] == "North York"
    assert meta["state"] == "ON"
    assert meta["zip"] == "M3H 5S4"
    assert meta["category"] == "Computer accessories"
    assert meta["currency"] == "USD"
    assert meta["ship_mode"] == "pickup"
    assert meta["ship_notes"] == "SHIPPING IS NOT AVAILABLE. Buyer pickup."
    assert meta["condition"] == "Used/See Description"
    assert meta["photo_urls"] == ["https://www.govdeals.com/photos/30467/30467_94_example.jpg"]
    assert meta["status"] == "open"
    assert meta["closes_at"] == "2030-06-01T12:00:00+00:00"
    assert meta["current_bid"] == 7360.0
    assert meta["bid_count"] == 1
    assert meta["watcher_count"] == 17
    assert meta["buyers_premium_pct"] == 12.5
    assert meta["reserve_met"] is None
    assert meta["bidbox"] == GOVDEALS_BIDBOX


def test_govdeals_bare_asset_document_yields_capture_without_bidbox() -> None:
    adapter = GovDealsAdapter()
    captures = list(adapter.parse_raw(json.dumps(GOVDEALS_ASSET), fetched_at=FETCHED_AT))

    assert len(captures) == 1
    meta = captures[0].metadata
    assert captures[0].source_listing_id == "30467-94"
    assert meta["bidbox"] is None
    assert meta["current_bid"] is None
    assert meta["closes_at"] is None
    assert meta["status"] == "open"


def test_govdeals_bare_bidbox_document_is_tape_only_capture() -> None:
    adapter = GovDealsAdapter()
    captures = list(adapter.parse_raw(json.dumps(GOVDEALS_BIDBOX), fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert capture.source_listing_id == "30467-94"
    meta = capture.metadata
    assert meta["bidbox_only"] is True
    assert meta["bidbox"] == GOVDEALS_BIDBOX
    assert meta["current_bid"] == 7360.0
    assert meta["bid_count"] == 1
    assert meta["watcher_count"] == 17
    assert meta["buyers_premium_pct"] == 12.5
    assert meta["status"] == "open"


def test_govdeals_search_results_yield_one_capture_per_asset() -> None:
    adapter = GovDealsAdapter()
    second = {**GOVDEALS_ASSET, "assetId": 95}
    payload = json.dumps({"assetSearchResults": [GOVDEALS_ASSET, second]})
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert [c.source_listing_id for c in captures] == ["30467-94", "30467-95"]


def test_govdeals_non_usd_bid_is_rejected() -> None:
    adapter = GovDealsAdapter()
    asset = {**GOVDEALS_ASSET, "currencyCode": "CAD"}
    payload = json.dumps({"asset": asset, "bidbox": GOVDEALS_BIDBOX})
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    meta = captures[0].metadata
    assert meta["currency"] == "CAD"
    assert meta["current_bid"] is None


def test_govdeals_reserve_and_status_semantics() -> None:
    adapter = GovDealsAdapter()

    def tape(box: dict) -> dict:
        captures = list(
            adapter.parse_raw(
                json.dumps({"asset": GOVDEALS_ASSET, "bidbox": box}), fetched_at=FETCHED_AT
            )
        )
        return captures[0].metadata

    box = {**GOVDEALS_BIDBOX, "hasReservePrice": True}
    box.pop("isReserveNotMet")
    assert tape(box)["reserve_met"] is None
    unmet = {**GOVDEALS_BIDBOX, "hasReservePrice": True, "isReserveNotMet": True}
    assert tape(unmet)["reserve_met"] is False
    reserve_box = {**GOVDEALS_BIDBOX, "hasReservePrice": True, "isReserveNotMet": False}
    assert tape(reserve_box)["reserve_met"] is True

    past = {**GOVDEALS_BIDBOX, "assetAuctionEndDateUTC": "2020-01-01T00:00:00Z"}
    assert tape(past)["status"] == "closed"
    pending = {**past, "assetStatusCd": "RFR"}
    assert tape(pending)["status"] == "seller_approval_pending"


def test_govdeals_unparseable_payloads_are_flagged_not_dropped() -> None:
    adapter = GovDealsAdapter()

    orphan = list(adapter.parse_raw(json.dumps({"asset": {"assetShortDesc": "x"}})))
    assert len(orphan) == 1
    assert orphan[0].metadata["parse_error"] == "missing_ids"
    RawCapture.model_validate(orphan[0].model_dump())

    empty = list(adapter.parse_raw("[]"))
    assert len(empty) == 1
    assert empty[0].metadata["parse_error"] == "no_items_found"
    RawCapture.model_validate(empty[0].model_dump())


def test_govdeals_load_fixtures_pairs_asset_with_bidbox() -> None:
    adapter = GovDealsAdapter()
    if adapter.fixture_path is None or not adapter.fixture_path.exists():
        pytest.skip("legacy fixture corpus not available")

    captures = list(adapter.load_fixtures())
    assert len(captures) == 1
    capture = captures[0]
    assert capture.source == "govdeals"
    assert capture.source_listing_id == "30467-94"
    assert capture.payload_format == "json"
    meta = capture.metadata
    assert meta["title"] == "Lot of 64 HP 32GB DDR4 ECC LRDIMM Server Memory"
    assert meta["bidbox"]["currentBid"] == 7360.0
    assert meta["bidbox"]["bidCount"] == 1
    assert meta["current_bid"] == 7360.0
    assert meta["watcher_count"] == 17
    assert meta["fixture_file"].endswith("asset_30467_94.json")
    assert len(meta["fixture_files"]) == 2


def test_govdeals_load_fixtures_flags_bad_file_and_continues(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text('{"asset": ')
    (tmp_path / "asset_77_5.json").write_text(
        json.dumps({**GOVDEALS_ASSET, "accountId": 77, "assetId": 5})
    )
    (tmp_path / "bidbox_77_5.json").write_text(
        json.dumps({**GOVDEALS_BIDBOX, "accountId": 77, "assetId": 5})
    )

    adapter = GovDealsAdapter()
    adapter.fixture_path = tmp_path
    captures = list(adapter.load_fixtures())

    failures = [c for c in captures if c.status == IngestionStatus.failed]
    assert len(failures) == 1
    assert "JSONDecodeError" in failures[0].metadata["parse_error"]
    assert failures[0].metadata["fixture_file"].endswith("bad.json")
    RawCapture.model_validate(failures[0].model_dump())

    good = [c for c in captures if c.status != IngestionStatus.failed]
    assert [c.source_listing_id for c in good] == ["77-5"]
    assert good[0].metadata["bidbox"]["currentBid"] == 7360.0


def test_registry_discovers_govdeals() -> None:
    assert "govdeals" in list_sources()
    adapter = get_adapter("govdeals")
    assert isinstance(adapter, GovDealsAdapter)
    assert adapter.source_name == "govdeals"
    assert adapter.fixture_path is not None


# --- Liquidation.com ---


def test_liquidation_combined_html_yields_one_capture_per_lot() -> None:
    adapter = LiquidationComAdapter()
    captures = list(adapter.parse_raw(COMBINED_LOT_HTML, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert capture.source == "liquidation_com"
    assert capture.source_listing_id == "21256289"
    assert capture.url == "https://www.liquidation.com/auction/view?id=21256289"
    assert capture.payload_format == "html"
    assert capture.fetched_at == FETCHED_AT
    assert capture.raw_payload == COMBINED_LOT_HTML
    RawCapture.model_validate(capture.model_dump())

    meta = capture.metadata
    assert meta["lot_id"] == "21256289"
    assert meta["title"] == "26TB, 8TB, 4TB, NAS, Desktop PC HDD / SSD Lot"
    assert meta["current_bid"] == 3200.0
    assert meta["minimum_bid"] == 3300.0
    assert meta["est_retail"] == 11100.0
    assert meta["close_time"] == "06/25/2026 09:15 AM ET"
    assert meta["status"] == "closing: Jun 25 9:15AM"
    assert meta["seller"] == "Newegg_Business"
    assert meta["location"] == "California"
    assert meta["condition"] == "Returns"
    assert meta["packages"] == "3 Packages"
    assert meta["item_count"] == 25
    assert meta["quantity_in_lot"] == 25
    assert meta["bids"] == 1
    assert meta["watchers"] == 5
    assert meta["views"] == 144
    assert meta["buyers_premium"] == "11%"
    assert meta["shipping_terms"] == "Buyer pays shipping"
    assert meta["auction_type"] == "Standard"
    assert meta["manifest_url"] == "https://www.liquidation.com/aucimg/21256/m21256289.html"
    assert meta["download_url"] is None

    manifest = meta["manifest"]
    assert manifest["total_quantity"] == 3
    assert manifest["total_ext_retail"] == pytest.approx(2934.97)
    assert len(manifest["items"]) == 2
    assert manifest["items"][0] == {
        "description": "4TB - SAMSUNG SSD 990 PRO 4TB",
        "quantity": 2,
        "retail_price": 1099.99,
        "ext_retail_price": 2199.98,
        "make": "SAMSUNG",
        "model": "MZ-V9P4T0B/AM",
        "product_category": "Solid State Disk",
    }


def test_liquidation_listing_page_yields_one_capture_per_card() -> None:
    adapter = LiquidationComAdapter()
    html = """
    <html><body>
      <div data-id="100"><a href="/auction/view?id=100">Item 100</a>
        <div class="current-bid">Current Bid: $10.00</div></div>
      <div data-id="200"><a href="/auction/view?id=200">Item 200</a>
        <div class="current-bid">Current Bid: $50.00</div></div>
    </body></html>
    """
    captures = list(adapter.parse_raw(html, fetched_at=FETCHED_AT))

    assert [c.source_listing_id for c in captures] == ["100", "200"]
    assert [c.url for c in captures] == [
        "https://www.liquidation.com/auction/view?id=100",
        "https://www.liquidation.com/auction/view?id=200",
    ]
    assert captures[0].metadata["current_bid"] == 10.0
    assert captures[1].metadata["current_bid"] == 50.0
    assert captures[0].metadata["manifest"] is None
    for capture in captures:
        RawCapture.model_validate(capture.model_dump())


def test_liquidation_standalone_detail_document_gets_lot_id_from_manifest_link() -> None:
    adapter = LiquidationComAdapter()
    captures = list(adapter.parse_raw(AUCTION_DETAIL_HTML, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert capture.source_listing_id == "21256289"
    meta = capture.metadata
    assert meta["minimum_bid"] == 3300.0
    assert meta["close_time"] == "06/25/2026 09:15 AM ET"
    assert meta["manifest_url"] == "https://www.liquidation.com/aucimg/21256/m21256289.html"
    assert meta["manifest"] is None
    assert meta["status"] is None


def test_liquidation_unrecognized_document_is_flagged_not_dropped() -> None:
    adapter = LiquidationComAdapter()
    html = "<html><body><p>no lot here</p></body></html>"
    captures = list(adapter.parse_raw(html, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert capture.metadata["parse_error"] == "no_lot_found"
    assert capture.source_listing_id.startswith("lot-")
    assert capture.raw_payload == html
    RawCapture.model_validate(capture.model_dump())


def test_liquidation_load_fixtures_combines_files_per_lot() -> None:
    adapter = LiquidationComAdapter()
    if adapter.fixture_path is None or not adapter.fixture_path.exists():
        pytest.skip("legacy fixture corpus not available")

    captures = list(adapter.load_fixtures())
    assert len(captures) == 1
    capture = captures[0]
    assert capture.source == "liquidation_com"
    assert capture.source_listing_id == "21256289"
    assert capture.url == "https://www.liquidation.com/auction/view?id=21256289"
    meta = capture.metadata
    assert meta["title"] == "26TB, 8TB, 4TB, NAS, Desktop PC HDD / SSD Lot"
    assert meta["current_bid"] == 3200.0
    assert meta["minimum_bid"] == 3300.0
    assert meta["manifest"]["total_quantity"] == 25
    assert meta["manifest"]["total_ext_retail"] == pytest.approx(11165.75)
    assert len(meta["manifest"]["items"]) == 25
    assert meta["manifest"]["items"][0]["model"] == "MZ-V9P4T0B/AM"
    assert meta["fixture_file"].endswith("listing_card_21256289.html")
    assert len(meta["fixture_files"]) == 3


def test_liquidation_load_fixtures_flags_unrecognized_file_and_continues(tmp_path: Path) -> None:
    (tmp_path / "listing_card_555.html").write_text(LISTING_CARD_HTML)
    (tmp_path / "auction_detail_555.html").write_text(AUCTION_DETAIL_HTML)
    (tmp_path / "manifest_555.html").write_text(MANIFEST_HTML)
    (tmp_path / "garbage_111.html").write_text("<html><body><p>no lot here</p></body></html>")

    adapter = LiquidationComAdapter()
    adapter.fixture_path = tmp_path
    captures = list(adapter.load_fixtures())

    assert len(captures) == 2
    good, bad = captures
    assert good.source_listing_id == "555"
    assert good.metadata["lot_id"] == "555"
    assert good.metadata["current_bid"] == 3200.0
    assert good.metadata["manifest"]["total_quantity"] == 3
    RawCapture.model_validate(good.model_dump())

    assert bad.source_listing_id == "111"
    assert bad.metadata["parse_error"] == "no_lot_found"
    RawCapture.model_validate(bad.model_dump())


def test_registry_discovers_liquidation_com() -> None:
    assert "liquidation_com" in list_sources()
    adapter = get_adapter("liquidation_com")
    assert isinstance(adapter, LiquidationComAdapter)
    assert adapter.source_name == "liquidation_com"
    assert adapter.fixture_path is not None
