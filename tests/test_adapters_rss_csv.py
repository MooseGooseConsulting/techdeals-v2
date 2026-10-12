from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from techdeals.adapters import get_adapter, list_sources
from techdeals.adapters.rss_csv import (
    AtlasGen5SsdAdapter,
    GoogleShoppingAdapter,
    SlickdealsAdapter,
    SplPsuTierListAdapter,
    SsdPricingRun1Adapter,
    extract_merchant,
    extract_price,
    extract_thread_id,
    is_mini_pc_deal,
)
from techdeals.ingestion.contract import IngestionStatus, RawCapture

FETCHED_AT = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)

LEGACY_ROOT = Path("/home/coldaine/TechdealsHandoff")
SLICKDEALS_CORPUS = LEGACY_ROOT / "scripts/ingest/slickdeals/fixtures/sample_rss.xml"
ATLAS_CORPUS = LEGACY_ROOT / "scripts/ingest/atlas_gen5_ssd/fixtures/complete-snapshot.json"
SPL_CORPUS = (
    LEGACY_ROOT / "research/reference_data/spl_psu_tier_list/SPL_PSU_Tier_List_All_Sheets.csv"
)
SSD_CORPUS = LEGACY_ROOT / "research/ssd-pricing-brightdata/ssd_prices_export.csv"


# ---------------------------------------------------------------------------
# slickdeals
# ---------------------------------------------------------------------------


def _sd_item(
    title: str,
    link: str,
    guid: str,
    description: str = "",
    pub_date: str = "Mon, 27 Jul 2026 10:15:00 GMT",
) -> str:
    return (
        "    <item>\n"
        f"      <title>{title}</title>\n"
        f"      <link>{link}</link>\n"
        f'      <guid isPermaLink="false">{guid}</guid>\n'
        f"      <pubDate>{pub_date}</pubDate>\n"
        f"      <description>{description}</description>\n"
        "    </item>"
    )


def _sd_feed(*items: str) -> str:
    body = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel><title>Slickdeals - Mini PC Deals</title>\n'
        f"{body}\n"
        "</channel></rss>"
    )


SD_MINIPC_ITEM = _sd_item(
    title="Beelink SER5 Mini PC AMD Ryzen 5 5560U 16GB DDR4 500GB NVMe SSD $219.99 @ Amazon",
    link="https://slickdeals.net/f/17654321-beelink-ser5",
    guid="sd:thread:17654321",
    description="Beelink SER5 Mini PC with clipped coupon.",
)
SD_EARBUDS_ITEM = _sd_item(
    title="Anker Soundcore Mini Wireless Bluetooth Earbuds $19.99 @ Amazon",
    link="https://slickdeals.net/f/17654324-anker-earbuds",
    guid="sd:thread:17654324",
    description="Compact Bluetooth wireless earbuds.",
)
SD_NO_MERCHANT_ITEM = _sd_item(
    title="GMKtec NucBox K6 Mini PC Intel Core i7-13620H 32GB RAM 1TB SSD $429.00",
    link="https://slickdeals.net/f/17654322-gmktec-nucbox-k6",
    guid="sd:thread:17654322",
    description="GMKtec NucBox K6 small desktop PC.",
)


def test_slickdeals_feed_yields_one_capture_per_item() -> None:
    adapter = SlickdealsAdapter()
    payload = _sd_feed(SD_MINIPC_ITEM, SD_EARBUDS_ITEM)
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert [c.source_listing_id for c in captures] == ["sd:thread:17654321", "sd:thread:17654324"]
    assert all(c.source == "slickdeals" for c in captures)
    assert all(c.payload_format == "xml" for c in captures)
    assert all(c.fetched_at == FETCHED_AT for c in captures)
    assert all(c.checksum == hashlib.sha256(c.raw_payload.encode()).hexdigest() for c in captures)


def test_slickdeals_extracts_title_price_merchant_thread() -> None:
    adapter = SlickdealsAdapter()
    capture = list(adapter.parse_raw(_sd_feed(SD_MINIPC_ITEM), fetched_at=FETCHED_AT))[0]
    meta = capture.metadata

    assert meta["title"].startswith("Beelink SER5 Mini PC")
    assert meta["price"] == 219.99
    assert meta["merchant"] == "Amazon"
    assert meta["thread_id"] == "17654321"
    assert meta["pub_date"] == "Mon, 27 Jul 2026 10:15:00 GMT"
    assert meta["is_mini_pc"] is True
    assert capture.url == "https://slickdeals.net/f/17654321-beelink-ser5"
    assert "Beelink" in capture.raw_payload
    RawCapture.model_validate(capture.model_dump())


def test_slickdeals_merchant_is_optional() -> None:
    adapter = SlickdealsAdapter()
    capture = list(adapter.parse_raw(_sd_feed(SD_NO_MERCHANT_ITEM), fetched_at=FETCHED_AT))[0]

    assert capture.metadata["merchant"] is None
    assert capture.metadata["price"] == 429.0
    assert capture.metadata["is_mini_pc"] is True


def test_slickdeals_non_mini_pc_items_are_quarantined_not_dropped() -> None:
    adapter = SlickdealsAdapter()
    payload = _sd_feed(SD_MINIPC_ITEM, SD_EARBUDS_ITEM)
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    deal, earbuds = captures
    assert deal.status == IngestionStatus.raw
    assert "quarantine_reason" not in deal.metadata

    assert earbuds.metadata["is_mini_pc"] is False
    assert earbuds.metadata["quarantine_reason"] == "not_mini_pc_deal"
    assert earbuds.status == IngestionStatus.quarantined
    RawCapture.model_validate(earbuds.model_dump())


def test_slickdeals_keyword_filter_semantics() -> None:
    assert is_mini_pc_deal("Minisforum UM780 XTX Mini PC $349.99")
    assert is_mini_pc_deal("Intel NUC barebone kit")
    assert not is_mini_pc_deal("Anker Soundcore Mini Wireless Bluetooth Earbuds")
    assert not is_mini_pc_deal("Steam PC Digital Game: Mini Motorways")
    assert not is_mini_pc_deal("Fractal Design Ridge Mini-ITX PC Case")
    assert extract_price("now $1,299.00 shipped") == 1299.0
    assert extract_price("no money here") is None
    assert extract_thread_id("sd:thread:99", "") == "99"
    assert extract_thread_id("", "https://slickdeals.net/f/1234567-deal") == "1234567"
    assert extract_merchant("Great drive $5 @ Newegg") == "Newegg"
    assert extract_merchant("Great drive $5") is None


def test_slickdeals_duplicate_thread_parsed_once() -> None:
    adapter = SlickdealsAdapter()
    captures = list(
        adapter.parse_raw(_sd_feed(SD_MINIPC_ITEM, SD_MINIPC_ITEM), fetched_at=FETCHED_AT)
    )

    assert [c.source_listing_id for c in captures] == ["sd:thread:17654321"]


def test_slickdeals_invalid_xml_is_flagged_not_raised() -> None:
    adapter = SlickdealsAdapter()
    captures = list(adapter.parse_raw("<rss><channel><item>", fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert "invalid_rss_xml" in captures[0].metadata["parse_error"]
    assert captures[0].raw_payload == "<rss><channel><item>"
    RawCapture.model_validate(captures[0].model_dump())


def test_slickdeals_feed_without_items_is_flagged() -> None:
    adapter = SlickdealsAdapter()
    empty_feed = "<rss><channel><title>empty</title></channel></rss>"
    captures = list(adapter.parse_raw(empty_feed, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_items_found"


def test_slickdeals_item_without_title_is_flagged_not_dropped() -> None:
    item = (
        "<item><link>https://slickdeals.net/f/1</link>"
        "<guid>sd:thread:1</guid></item>"
    )
    adapter = SlickdealsAdapter()
    captures = list(adapter.parse_raw(_sd_feed(item), fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "missing_title"


def test_slickdeals_registry_and_corpus_fixtures() -> None:
    assert "slickdeals" in list_sources()
    adapter = get_adapter("slickdeals")
    assert isinstance(adapter, SlickdealsAdapter)
    if adapter.fixture_path is None or not adapter.fixture_path.exists():
        pytest.skip("legacy fixture corpus not available")

    captures = list(adapter.load_fixtures())
    assert len(captures) == 6
    assert [c.source_listing_id for c in captures[:3]] == [
        "sd:thread:17654321",
        "sd:thread:17654322",
        "sd:thread:17654323",
    ]
    assert sum(1 for c in captures if c.metadata["is_mini_pc"]) == 3
    quarantined = [c for c in captures if c.status == IngestionStatus.quarantined]
    assert len(quarantined) == 3
    for capture in captures:
        assert capture.metadata["fixture_file"].endswith("sample_rss.xml")
        RawCapture.model_validate(capture.model_dump())


# ---------------------------------------------------------------------------
# google_shopping
# ---------------------------------------------------------------------------

GS_LEGACY_CSV = (
    "Product Name,Price,Merchant,Condition/Notes,Product URL\n"
    "Western Digital WD82PURX Purple 8TB 3.5-inch SATA HDD,$317.02,GotoDirect,Refurbished,"
    "https://www.gotodirect.com/western-digital-wd82purx-purple-pro-8tb\n"
    "Seagate SkyHawk Hard Drive | DVR & NVR Storage,$149.99,CCTV Security Pros,20TB,"
    "https://www.cctvsecuritypros.com/security-camera-hard-drives/\n"
)

GS_REDUCED_CSV = (
    "Product,Price,Store,Condition\n"
    "Western Digital WD82PURX Purple 8TB 3.5-inch SATA HDD,$317.02,GotoDirect,Refurbished\n"
)

GS_MIXED_CSV = (
    "Product,Price,Store,Condition,Product URL\n"
    "Samsung 870 EVO 1TB SATA III 2.5-inch SSD,$89.99,Amazon,New,"
    "https://www.amazon.com/dp/B08QBJ2YMG\n"
    "Samsung 870 EVO 1TB SATA III 2.5-inch SSD,$89.99,Amazon,New,\n"
)


def test_google_shopping_legacy_schema_rows() -> None:
    adapter = GoogleShoppingAdapter()
    captures = list(adapter.parse_raw(GS_LEGACY_CSV, fetched_at=FETCHED_AT))

    assert len(captures) == 2
    first = captures[0]
    meta = first.metadata
    assert meta["schema_mode"] == "legacy_url_export"
    assert meta["source_row_number"] == 1
    assert meta["observed_date"] == "2026-10-12"
    assert meta["product_name"].startswith("Western Digital WD82PURX")
    assert meta["title"] == meta["product_name"]
    assert meta["price"] == 317.02
    assert meta["merchant"] == "GotoDirect"
    assert meta["condition_class"] == "refurbished"
    assert meta["missing_url"] is False
    assert meta["brand_name"] == "Western Digital"
    assert meta["model_name"] == "WD82PURX"
    assert meta["capacity_raw"] == "8TB"
    assert meta["tb_per_drive"] == 8.0
    assert meta["form_factor"] == "3.5-inch"
    assert meta["interface_raw"] == "SATA"
    assert meta["technology"] == "HDD"
    assert first.url == "https://www.gotodirect.com/western-digital-wd82purx-purple-pro-8tb"
    assert first.source_listing_id.startswith("gs-url-")
    RawCapture.model_validate(first.model_dump())

    second = captures[1].metadata
    assert second["capacity_raw"] == "20TB"
    assert second["brand_name"] == "Seagate"
    assert second["technology"] == "HDD"


def test_google_shopping_reduced_schema_without_url() -> None:
    adapter = GoogleShoppingAdapter()
    captures = list(adapter.parse_raw(GS_REDUCED_CSV, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    meta = captures[0].metadata
    assert meta["schema_mode"] == "reduced_manual"
    assert meta["missing_url"] is True
    assert captures[0].url.startswith("urn:techdeals:google_shopping:")
    assert captures[0].source_listing_id.startswith("gs-row-")
    RawCapture.model_validate(captures[0].model_dump())


def test_google_shopping_mixed_rows_track_missing_url() -> None:
    adapter = GoogleShoppingAdapter()
    captures = list(adapter.parse_raw(GS_MIXED_CSV, fetched_at=FETCHED_AT))

    assert [c.metadata["missing_url"] for c in captures] == [False, True]
    assert captures[0].metadata["technology"] == "SSD"
    assert captures[0].metadata["form_factor"] == "2.5-inch"
    assert captures[0].metadata["capacity_raw"] == "1TB"


def test_google_shopping_observed_date_from_metadata() -> None:
    adapter = GoogleShoppingAdapter()
    captures = list(
        adapter.parse_raw(
            GS_LEGACY_CSV, fetched_at=FETCHED_AT, metadata={"observed_date": "2026-06-24"}
        )
    )

    assert captures[0].metadata["observed_date"] == "2026-06-24"


def test_google_shopping_bom_is_tolerated() -> None:
    adapter = GoogleShoppingAdapter()
    captures = list(adapter.parse_raw("\ufeff" + GS_LEGACY_CSV, fetched_at=FETCHED_AT))

    assert len(captures) == 2
    assert captures[0].metadata["product_name"].startswith("Western Digital")


def test_google_shopping_unsupported_schema_is_flagged() -> None:
    adapter = GoogleShoppingAdapter()
    payload = "foo,bar\n1,2\n"
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert "Unsupported Google Shopping columns" in captures[0].metadata["parse_error"]
    assert captures[0].raw_payload == payload
    RawCapture.model_validate(captures[0].model_dump())


def test_google_shopping_header_only_is_flagged() -> None:
    adapter = GoogleShoppingAdapter()
    captures = list(adapter.parse_raw(GS_LEGACY_CSV.splitlines()[0], fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_items_found"


def test_google_shopping_sample_fixture_loads() -> None:
    assert "google_shopping" in list_sources()
    adapter = get_adapter("google_shopping")
    assert isinstance(adapter, GoogleShoppingAdapter)
    assert adapter.fixture_path is not None and adapter.fixture_path.exists()

    captures = list(adapter.load_fixtures())
    assert len(captures) >= 2
    schemas = {c.metadata["schema_mode"] for c in captures}
    assert "legacy_url_export" in schemas
    assert "reduced_manual" in schemas
    for capture in captures:
        assert capture.source == "google_shopping"
        assert capture.metadata.get("parse_error") is None
        assert capture.metadata["title"] == capture.metadata["product_name"]
        assert capture.metadata["price"] is not None
        RawCapture.model_validate(capture.model_dump())


# ---------------------------------------------------------------------------
# spl_psu_tier_list
# ---------------------------------------------------------------------------

SPL_MAIN = "Main List (Proper Ratings Only)"
SPL_FULL = "Full List (With Limited Confidence Ratings)"


def _spl_csv(sheets: dict[str, list[list[str]]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for name, rows in sheets.items():
        writer.writerow([f"========== SHEET: {name} =========="])
        for row in rows:
            writer.writerow(row)
    return buffer.getvalue()


def _spl_main_row(
    row_id: str = "rowid-main-1",
    *,
    sub_series_2: str = "2021",
    wattages: str = "650/750/850W",
    tier: str = "A+",
    notes: str = "solid unit",
) -> list[str]:
    return [
        "Corsair",
        "RMx",
        "Gold",
        sub_series_2,
        wattages,
        tier,
        "2021",
        "ATX",
        "ATX 3.x",
        "100-240V",
        "Full",
        "Gold",
        "LLC",
        "SR",
        "DC-DC",
        "CWT",
        "CSZ",
        notes,
        row_id,
    ]


SPL_SAMPLE = _spl_csv(
    {
        "About": [["", "Welcome to SPL's PSU Tier List!", ""]],
        SPL_MAIN: [
            _spl_main_row(),
            _spl_main_row(
                "rowid-main-2",
                sub_series_2="2023",
                wattages="850/1000W",
                tier="A",
                notes="shift model",
            ),
        ],
        SPL_FULL: [
            [
                "Seasonic",
                "",
                "Focus",
                "Plus",
                "550-750W",
                "B",
                "",
                "ATX",
                "ATX 2.x",
                "100-240V",
                "No",
                "W",
                "DF",
                "PR",
                "GR",
                "Seasonic",
                "FOCUS",
                "notes here",
            ],
            ["EVGA", "G3", "SuperNova", ""],
            [
                "",
                "550/650W",
                "B",
                "2020",
                "ATX",
                "ATX 3.x",
                "100-240V",
                "No",
                "Gold",
                "LLC",
                "SR",
                "DC-DC",
                "EVGA",
                "G3",
                "short row notes",
            ],
            ["tiny", "row"],
        ],
    }
)


def test_spl_tier_rows_are_judgment_data_quarantined() -> None:
    adapter = SplPsuTierListAdapter()
    captures = list(adapter.parse_raw(SPL_SAMPLE, fetched_at=FETCHED_AT))
    records = [c for c in captures if not c.metadata.get("parse_error")]

    assert len(captures) == 5
    assert len(records) == 4
    for capture in records:
        assert capture.metadata["data_type"] == "judgment"
        assert capture.metadata["quarantine_reason"] == "reference_data_not_posting"
        assert capture.status == IngestionStatus.quarantined
        assert capture.payload_format == "json"
        assert capture.url.startswith("urn:techdeals:spl_psu_tier_list:")
        RawCapture.model_validate(capture.model_dump())


def test_spl_main_sheet_record_fields() -> None:
    adapter = SplPsuTierListAdapter()
    captures = list(adapter.parse_raw(SPL_SAMPLE, fetched_at=FETCHED_AT))
    record = captures[0]

    assert record.source_listing_id == "rowid-main-1"
    meta = record.metadata
    assert meta["source_sheet"] == SPL_MAIN
    assert meta["brand"] == "Corsair"
    assert meta["series"] == "RMx"
    assert meta["title"] == "Corsair RMx Gold 2021"
    assert meta["price"] is None
    assert meta["wattages_raw"] == "650/750/850W"
    assert meta["wattage_values"] == [650, 750, 850]
    assert meta["watt_min"] == 650
    assert meta["watt_max"] == 850
    assert meta["tier_raw"] == "A+"
    assert meta["tier"] == "A"
    assert meta["tier_mod"] == "+"
    assert meta["intro_year"] == 2021
    assert meta["odm"] == "CWT"
    assert meta["platform_code"] == "CSZ"
    assert meta["row_id"] == "rowid-main-1"
    assert meta["needs_manual_id"] is False
    assert json.loads(record.raw_payload)["notes"] == "solid unit"


def test_spl_full_sheet_identity_state_and_short_rows() -> None:
    adapter = SplPsuTierListAdapter()
    captures = list(adapter.parse_raw(SPL_SAMPLE, fetched_at=FETCHED_AT))
    full = [
        c
        for c in captures
        if not c.metadata.get("parse_error") and c.metadata["source_sheet"] == SPL_FULL
    ]

    assert len(full) == 2
    first, second = full

    assert first.metadata["brand"] == "Seasonic"
    assert first.metadata["sub_series_1"] == "Focus"
    assert first.metadata["sub_series_2"] == "Plus"
    assert first.metadata["tier"] == "B"
    assert first.metadata["notes"] == "notes here"
    assert first.metadata["needs_manual_id"] is False

    assert second.metadata["brand"] == "EVGA"
    assert second.metadata["series"] == "G3"
    assert second.metadata["sub_series_1"] == "SuperNova"
    assert second.metadata["sub_series_2"] == ""
    assert second.metadata["wattage_values"] == [550, 650]
    assert second.metadata["tier"] == "B"
    assert second.metadata["intro_year"] == 2020
    assert second.metadata["notes"] == "short row notes"


def test_spl_quarantined_rows_are_flagged_not_dropped() -> None:
    adapter = SplPsuTierListAdapter()
    captures = list(adapter.parse_raw(SPL_SAMPLE, fetched_at=FETCHED_AT))
    bad = [c for c in captures if c.metadata.get("parse_error")]

    assert len(bad) == 1
    assert bad[0].metadata["parse_error"] == "unexpected_width:2"
    assert bad[0].metadata["data_type"] == "judgment"
    assert bad[0].metadata["source_sheet"] == SPL_FULL
    assert "tiny" in bad[0].raw_payload
    RawCapture.model_validate(bad[0].model_dump())


def test_spl_row_without_wattage_tier_or_notes_is_quarantined() -> None:
    empty_record_row = [""] * 7 + ["ATX"] + [""] * 11
    payload = _spl_csv({SPL_MAIN: [_spl_main_row(), empty_record_row]})
    adapter = SplPsuTierListAdapter()
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert len(captures) == 2
    bad = captures[1]
    assert bad.metadata["parse_error"] == "no_wattage_tier_or_notes"
    assert bad.metadata["source_row_number"] == 3


def test_spl_missing_row_id_falls_back_to_stable_key() -> None:
    row = _spl_main_row(row_id="")
    payload = _spl_csv({SPL_MAIN: [row]})
    adapter = SplPsuTierListAdapter()
    capture = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))[0]

    assert len(capture.source_listing_id) == 64
    assert capture.metadata["stable_key"] == capture.source_listing_id
    assert capture.metadata["needs_manual_id"] is True


def test_spl_stable_key_separates_inherited_identity_rows() -> None:
    record_row = [
        "",
        "1200W",
        "C+*",
        "",
        "ATX",
        "ATX 3.x",
        "100-240V",
        "No",
        "Gold",
        "LLC",
        "SR",
        "DC-DC",
        "OEM",
        "PLAT",
        "No OTP claimed, no performance or protections data",
    ]
    payload = _spl_csv(
        {
            SPL_FULL: [
                ["Apevia", "Galaxy", "", "ATX 3.0"],
                record_row,
                ["Apevia", "Premier", "", "ATX 3.0"],
                list(record_row),
            ],
        }
    )
    adapter = SplPsuTierListAdapter()
    captures = [
        c
        for c in adapter.parse_raw(payload, fetched_at=FETCHED_AT)
        if not c.metadata.get("parse_error")
    ]

    assert len(captures) == 2
    assert captures[0].metadata["series"] == "Galaxy"
    assert captures[1].metadata["series"] == "Premier"
    assert captures[0].source_listing_id != captures[1].source_listing_id
    assert captures[0].metadata["stable_key"] != captures[1].metadata["stable_key"]


def test_spl_payload_without_sheet_markers_is_flagged() -> None:
    adapter = SplPsuTierListAdapter()
    captures = list(adapter.parse_raw("brand,tier\nCorsair,A\n", fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_sheets_found"


def test_spl_registry_and_corpus_fixture() -> None:
    assert "spl_psu_tier_list" in list_sources()
    adapter = get_adapter("spl_psu_tier_list")
    assert isinstance(adapter, SplPsuTierListAdapter)
    if adapter.fixture_path is None or not adapter.fixture_path.exists():
        pytest.skip("legacy fixture corpus not available")

    captures = list(adapter.load_fixtures())
    records = [c for c in captures if not c.metadata.get("parse_error")]
    assert len(records) > 2000
    first = records[0]
    assert first.metadata["source_sheet"] == SPL_MAIN
    assert first.metadata["brand"] == "1st Player"
    assert first.metadata["wattage_values"] == [550, 650, 750]
    for capture in captures:
        assert capture.metadata["fixture_file"].endswith("SPL_PSU_Tier_List_All_Sheets.csv")


# ---------------------------------------------------------------------------
# ssd_pricing_run1
# ---------------------------------------------------------------------------

SSD_HEADER = (
    "brand,model_name,capacity_gb,interface,form_factor,nand_type,seq_read_mbps,"
    "seq_write_mbps,has_dram,retailer,price_usd,original_price_usd,discount_pct,"
    "coupon_code,condition,in_stock,source_type,source_name,scraped_at,retailer_url,source_url"
)

SSD_ROW = (
    "Samsung,T7,2000,USB 3.2,External,,1050,1000,,BestBuy,237.99,,,,new,1,"
    "serp_result,BestBuy SERP,2026-07-31T07:42:08Z,"
    "https://www.bestbuy.com/product/samsung-t7-2tb,"
    "https://www.bestbuy.com/product/samsung-t7-2tb"
)

SSD_CSV = f"{SSD_HEADER}\n{SSD_ROW}\n"


def test_ssd_pricing_row_becomes_capture() -> None:
    adapter = SsdPricingRun1Adapter()
    captures = list(adapter.parse_raw(SSD_CSV, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    meta = capture.metadata
    assert capture.source == "ssd_pricing_run1"
    assert capture.payload_format == "json"
    assert capture.url == "https://www.bestbuy.com/product/samsung-t7-2tb"
    assert capture.source_listing_id.startswith("ssd-url-")
    assert meta["brand"] == "Samsung"
    assert meta["model_name"] == "T7"
    assert meta["title"] == "T7"
    assert meta["capacity_gb"] == 2000
    assert meta["retailer"] == "BestBuy"
    assert meta["price_usd"] == 237.99
    assert meta["price"] == 237.99
    assert meta["in_stock"] is True
    assert meta["scraped_at"] == "2026-07-31T07:42:08+00:00"
    assert meta["source_type"] == "serp_result"
    assert meta["source_name"] == "BestBuy SERP"
    assert meta["row_number"] == 2
    RawCapture.model_validate(capture.model_dump())


def test_ssd_pricing_shared_url_gets_distinct_listing_ids() -> None:
    def _row(model: str, condition: str) -> str:
        return (
            f"Crucial,{model},2000,PCIe 5.0,M.2 2280,TLC,14500,12400,1,Newegg,299.99,"
            f",,,{condition},1,serp_result,Newegg SERP,2026-07-31T07:42:08Z,"
            "https://www.newegg.com/crucial-2tb-t705-nvme/p/N82E16820156398,"
            "https://www.newegg.com/crucial-2tb-t705-nvme/p/N82E16820156398"
        )

    payload = f"{SSD_HEADER}\n{_row('T500', 'new')}\n{_row('T705', 'new')}\n{_row('T705', 'used')}\n"
    adapter = SsdPricingRun1Adapter()
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    ids = [c.source_listing_id for c in captures]
    assert len(captures) == 3
    assert all(i.startswith("ssd-url-") for i in ids)
    assert len(ids) == len(set(ids))


def test_ssd_pricing_missing_required_columns_is_flagged() -> None:
    adapter = SsdPricingRun1Adapter()
    captures = list(adapter.parse_raw("brand,model_name\nSamsung,T7\n", fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert "missing_required_columns" in captures[0].metadata["parse_error"]
    assert "price_usd" in captures[0].metadata["parse_error"]
    RawCapture.model_validate(captures[0].model_dump())


def test_ssd_pricing_bad_row_is_flagged_and_parsing_continues() -> None:
    bad_row = (
        "Samsung,T7,2000,USB 3.2,External,,1050,1000,,BestBuy,not-a-price,,,,new,1,"
        "serp_result,BestBuy SERP,2026-07-31T07:42:08Z,https://example.com/a,https://example.com/a"
    )
    payload = f"{SSD_HEADER}\n{bad_row}\n{SSD_ROW}\n"
    adapter = SsdPricingRun1Adapter()
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert len(captures) == 2
    failed, good = captures
    assert "price_usd is not numeric" in failed.metadata["parse_error"]
    assert "Samsung" in failed.raw_payload
    assert good.metadata["model_name"] == "T7"
    RawCapture.model_validate(failed.model_dump())


def test_ssd_pricing_in_stock_must_be_flag() -> None:
    row = SSD_ROW.replace(",new,1,", ",new,yes,")
    adapter = SsdPricingRun1Adapter()
    captures = list(adapter.parse_raw(f"{SSD_HEADER}\n{row}\n", fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert "in_stock must be 0 or 1" in captures[0].metadata["parse_error"]


def test_ssd_pricing_empty_export_is_flagged() -> None:
    adapter = SsdPricingRun1Adapter()
    captures = list(adapter.parse_raw(f"{SSD_HEADER}\n", fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_items_found"


def test_ssd_pricing_registry_and_corpus_fixture() -> None:
    assert "ssd_pricing_run1" in list_sources()
    adapter = get_adapter("ssd_pricing_run1")
    assert isinstance(adapter, SsdPricingRun1Adapter)
    if adapter.fixture_path is None or not adapter.fixture_path.exists():
        pytest.skip("legacy fixture corpus not available")

    expected_rows = sum(1 for _ in csv.DictReader(SSD_CORPUS.open()))
    captures = list(adapter.load_fixtures())
    assert len(captures) == expected_rows
    assert expected_rows == 25
    for capture in captures:
        assert capture.metadata["fixture_file"].endswith("ssd_prices_export.csv")
        assert capture.metadata["price_usd"] > 0
        RawCapture.model_validate(capture.model_dump())


# ---------------------------------------------------------------------------
# atlas_gen5_ssd
# ---------------------------------------------------------------------------

ATLAS_SAMPLE = {
    "metadata": {
        "snapshot_date": "2026-07-16",
        "currency": "USD",
        "product_count": 2,
        "client_product_count": 1,
        "enterprise_product_count": 1,
    },
    "products": [
        {
            "id": "wd-sn8100",
            "class": "client",
            "brand": "WD_BLACK / SanDisk",
            "name": "SN8100",
            "capacities": [1, 2, 4, 8],
            "formFactors": ["M.2 2280"],
            "interface": "PCIe 5.0 x4 NVMe",
            "nand": "SanDisk 3D CBA TLC",
            "dram": "Dedicated DRAM",
            "read": 14900,
            "write": 14000,
            "tbw": {"1": 600, "2": 1200},
            "warranty": "5 years",
            "prices": {
                "2": {
                    "amount": 399.5,
                    "retailer": "Amazon",
                    "status": "observed",
                    "observed": "2026-07-10",
                    "confidence": "high",
                    "active": True,
                    "source": "https://www.amazon.com/dp/EXAMPLE",
                },
                "4": None,
            },
        },
        {
            "id": "samsung-pm9d3a",
            "class": "enterprise",
            "brand": "Samsung",
            "name": "PM9D3a",
            "capacities": [3.84, 7.68],
            "interface": "PCIe 5.0 NVMe",
            "procurement": {"lowPerTb": 120.0, "highPerTb": 165.0, "basis": "modeled_rfq_band"},
            "prices": {},
        },
    ],
    "source_ledger": [],
}


def test_atlas_snapshot_yields_one_capture_per_product() -> None:
    adapter = AtlasGen5SsdAdapter()
    payload = json.dumps(ATLAS_SAMPLE)
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert [c.source_listing_id for c in captures] == ["wd-sn8100", "samsung-pm9d3a"]
    assert all(c.payload_format == "json" for c in captures)
    assert all(c.url.startswith("urn:techdeals:atlas_gen5_ssd:") for c in captures)
    assert all(c.checksum == hashlib.sha256(c.raw_payload.encode()).hexdigest() for c in captures)


def test_atlas_product_metadata_includes_quotes_and_specs() -> None:
    adapter = AtlasGen5SsdAdapter()
    capture = list(adapter.parse_raw(json.dumps(ATLAS_SAMPLE), fetched_at=FETCHED_AT))[0]
    meta = capture.metadata

    assert meta["snapshot_date"] == "2026-07-16"
    assert meta["product_class"] == "client"
    assert meta["brand"] == "WD_BLACK / SanDisk"
    assert meta["name"] == "SN8100"
    assert meta["title"] == "SN8100"
    assert meta["price"] == 399.5
    assert meta["read_mbps"] == 14900.0
    assert meta["capacities"] == [1, 2, 4, 8]
    assert meta["tbw_by_capacity"] == {"1": 600, "2": 1200}
    quotes = meta["client_quotes"]
    assert len(quotes) == 1
    assert quotes[0]["capacity_key"] == "2"
    assert quotes[0]["capacity_tb"] == 2.0
    assert quotes[0]["amount"] == 399.5
    assert quotes[0]["retailer"] == "Amazon"
    assert quotes[0]["source"] == "https://www.amazon.com/dp/EXAMPLE"
    assert json.loads(capture.raw_payload)["id"] == "wd-sn8100"
    RawCapture.model_validate(capture.model_dump())


def test_atlas_enterprise_product_has_no_client_quotes() -> None:
    adapter = AtlasGen5SsdAdapter()
    captures = list(adapter.parse_raw(json.dumps(ATLAS_SAMPLE), fetched_at=FETCHED_AT))
    enterprise = captures[1]

    assert enterprise.metadata["product_class"] == "enterprise"
    assert enterprise.metadata["client_quotes"] == []
    assert enterprise.metadata["title"] == "PM9D3a"
    assert enterprise.metadata["price"] is None
    assert json.loads(enterprise.raw_payload)["procurement"]["lowPerTb"] == 120.0


def test_atlas_invalid_json_is_flagged_not_raised() -> None:
    adapter = AtlasGen5SsdAdapter()
    captures = list(adapter.parse_raw('{"products": [', fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert "invalid_json" in captures[0].metadata["parse_error"]
    RawCapture.model_validate(captures[0].model_dump())


def test_atlas_product_without_id_is_flagged_not_dropped() -> None:
    payload = json.dumps({"products": [{"name": "nameless"}, {"id": "ok-one", "class": "client"}]})
    adapter = AtlasGen5SsdAdapter()
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert len(captures) == 2
    assert captures[0].metadata["parse_error"] == "invalid_item"
    assert captures[1].source_listing_id == "ok-one"


def test_atlas_empty_products_is_flagged() -> None:
    adapter = AtlasGen5SsdAdapter()
    captures = list(adapter.parse_raw('{"products": []}', fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_items_found"


def test_atlas_registry_and_corpus_fixture() -> None:
    assert "atlas_gen5_ssd" in list_sources()
    adapter = get_adapter("atlas_gen5_ssd")
    assert isinstance(adapter, AtlasGen5SsdAdapter)
    if adapter.fixture_path is None or not adapter.fixture_path.exists():
        pytest.skip("legacy fixture corpus not available")

    captures = list(adapter.load_fixtures())
    assert len(captures) == 24
    assert captures[0].source_listing_id == "wd-sn8100"
    assert captures[0].metadata["snapshot_date"] == "2026-07-16"
    for capture in captures:
        assert capture.metadata["fixture_file"].endswith("complete-snapshot.json")
        RawCapture.model_validate(capture.model_dump())


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_registry_discovers_all_rss_csv_sources() -> None:
    sources = list_sources()
    for name in (
        "slickdeals",
        "google_shopping",
        "spl_psu_tier_list",
        "ssd_pricing_run1",
        "atlas_gen5_ssd",
    ):
        assert name in sources

    assert isinstance(get_adapter("slickdeals"), SlickdealsAdapter)
    assert isinstance(get_adapter("google_shopping"), GoogleShoppingAdapter)
    assert isinstance(get_adapter("spl_psu_tier_list"), SplPsuTierListAdapter)
    assert isinstance(get_adapter("ssd_pricing_run1"), SsdPricingRun1Adapter)
    assert isinstance(get_adapter("atlas_gen5_ssd"), AtlasGen5SsdAdapter)
