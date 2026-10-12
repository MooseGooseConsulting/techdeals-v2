from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from techdeals.adapters import base as adapter_base
from techdeals.adapters import get_adapter, list_sources
from techdeals.adapters.base import SourceAdapter, load_all
from techdeals.adapters.rackrat import RackRatAdapter
from techdeals.adapters.reddit import (
    RedditAtomAdapter,
    RedditHardwareswapAdapter,
    RedditHomelabsalesAdapter,
    classify_listing_type,
)
from techdeals.adapters.shopify import (
    FusionwwAdapter,
    ServerPartDealsAdapter,
    ShopifyAdapter,
    WaterpantherAdapter,
)
from techdeals.ingestion.contract import IngestionStatus, RawCapture

FETCHED_AT = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)

SAMPLE_SHOPIFY_PRODUCT = {
    "id": 5160409890949,
    "title": "Refurbished: 1200GB 10K SAS 12G SFF HDD PE Gen14",
    "handle": "1200gb-10k-sas-12g-sff-hdd-pe-gen14",
    "body_html": "<p>description</p>",
    "vendor": "Water Panther",
    "product_type": "Hard Drive",
    "tags": ["HDD", "SAS"],
    "variants": [
        {
            "id": 5160409890950,
            "title": "Default Title",
            "price": "349.00",
            "sku": "SWP_1.2TB10KSAS",
            "position": 1,
            "compare_at_price": "399.00",
            "option1": "Default Title",
            "available": True,
        }
    ],
    "options": [{"name": "Title", "position": 1, "values": ["Default Title"]}],
    "images": [],
}

SAMPLE_FUSION_PAYLOAD = {
    "total": 1,
    "page": 1,
    "perPage": 100,
    "products": [
        {
            "productId": "fww-prod-001",
            "mpn": "MZ-77E1T0B/AM",
            "name": "Samsung 870 EVO 1TB SATA III 2.5-Inch Internal SSD",
            "manufacturer": {"id": 102, "name": "Samsung Electronics"},
            "category": "Solid State Drives (SSD)",
            "taxonomy": ["Storage", "Internal SSD"],
            "quantity": 250,
            "leadTimeDays": 2,
            "price": 89.99,
            "listPrice": 109.99,
            "productStatus": "Active",
            "isActive": True,
            "attributes": [
                {"name": "Capacity", "value": "1TB", "isFilter": True},
                {"name": "Interface", "value": "SATA III 6Gb/s", "isFilter": True},
            ],
        }
    ],
}


def test_shopify_adapter_parses_sample_product() -> None:
    adapter = WaterpantherAdapter()
    payload = json.dumps({"products": [SAMPLE_SHOPIFY_PRODUCT]})
    captures = list(
        adapter.parse_raw(
            payload,
            source_url="https://www.waterpanther.com/collections/all/products.json",
            fetched_at=FETCHED_AT,
        )
    )

    assert len(captures) == 1
    capture = captures[0]
    assert capture.source == "waterpanther"
    assert capture.source_listing_id == "5160409890949"
    assert capture.url == "https://www.waterpanther.com/products/1200gb-10k-sas-12g-sff-hdd-pe-gen14"
    assert capture.fetched_at == FETCHED_AT

    meta = capture.metadata
    assert meta["title"] == "1200GB 10K SAS 12G SFF HDD PE Gen14"
    assert meta["condition_raw"] == "Refurbished"
    assert meta["sku"] == "SWP_1.2TB10KSAS"
    assert meta["price"] == 349.0
    assert meta["listed_price"] == 399.0
    assert meta["availability"] == "InStock"
    assert meta["vendor"] == "Water Panther"
    assert meta["product_type"] == "Hard Drive"
    assert meta["variant_count"] == 1
    assert meta["source_url"] == "https://www.waterpanther.com/collections/all/products.json"


def test_adapter_produces_valid_raw_capture_objects() -> None:
    adapter = WaterpantherAdapter()
    payload = json.dumps({"products": [SAMPLE_SHOPIFY_PRODUCT]})
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    for capture in captures:
        assert isinstance(capture, RawCapture)
        assert capture.payload_format == "json"
        assert capture.status == IngestionStatus.raw
        assert capture.checksum == hashlib.sha256(capture.raw_payload.encode()).hexdigest()
        expected_checksum = hashlib.sha256(json.dumps(SAMPLE_SHOPIFY_PRODUCT).encode()).hexdigest()
        assert capture.checksum == expected_checksum
        assert json.loads(capture.raw_payload) == SAMPLE_SHOPIFY_PRODUCT
        RawCapture.model_validate(capture.model_dump())


def test_registry_discovers_all_three_shopify_sources() -> None:
    sources = list_sources()
    for name in ("waterpanther", "serverpartdeals", "fusionww"):
        assert name in sources
        adapter = get_adapter(name)
        assert isinstance(adapter, ShopifyAdapter)
        assert adapter.source_name == name
        assert adapter.fixture_path is not None


def test_fusionww_flat_item_format_parses() -> None:
    adapter = FusionwwAdapter()
    captures = list(adapter.parse_raw(json.dumps(SAMPLE_FUSION_PAYLOAD), fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert capture.source == "fusionww"
    assert capture.source_listing_id == "fww-prod-001"
    assert capture.url == "https://www.fusionww.com/product/MZ-77E1T0B/AM"

    meta = capture.metadata
    assert meta["mpn"] == "MZ-77E1T0B/AM"
    assert meta["title"] == "Samsung 870 EVO 1TB SATA III 2.5-Inch Internal SSD"
    assert meta["manufacturer"] == "Samsung Electronics"
    assert meta["category"] == "Solid State Drives (SSD)"
    assert meta["price"] == 89.99
    assert meta["listed_price"] == 109.99
    assert meta["quantity"] == 250
    assert meta["lead_time_days"] == 2
    assert meta["status"] == "Active"
    assert meta["attributes"] == {"Capacity": "1TB", "Interface": "SATA III 6Gb/s"}


def test_fusionww_item_falls_back_to_mpn_id_and_taxonomy() -> None:
    adapter = FusionwwAdapter()
    payload = json.dumps(
        {
            "data": [
                {
                    "mpn": "ST18000NM000J",
                    "name": "Seagate Exos X18 18TB Enterprise SATA HDD",
                    "taxonomy": ["Storage", "Enterprise HDD"],
                    "unitPrice": "219.00",
                    "msrp": 219.00,
                    "totalAvailableQuantity": "85",
                    "isActive": True,
                }
            ]
        }
    )
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert capture.source_listing_id == "ST18000NM000J"
    assert capture.url == "https://www.fusionww.com/product/ST18000NM000J"
    meta = capture.metadata
    assert meta["category"] == "Storage > Enterprise HDD"
    assert meta["price"] == 219.0
    assert meta["listed_price"] is None
    assert meta["quantity"] == 85
    assert meta["status"] == "Active"


def test_multi_variant_product_joins_variant_titles() -> None:
    adapter = ServerPartDealsAdapter()
    product = {
        "id": 101,
        "title": "Used: 256GB DDR4 RDIMM",
        "handle": "256gb-ddr4-rdimm",
        "vendor": "ServerPartDeals",
        "product_type": "Memory",
        "variants": [
            {
                "id": 201,
                "title": "2933MHz",
                "price": "120.00",
                "sku": "SPD-2933",
                "available": False,
            },
            {
                "id": 202,
                "title": "3200MHz",
                "price": "135.00",
                "compare_at_price": "135.00",
                "sku": "SPD-3200",
                "available": True,
            },
        ],
    }
    captures = list(adapter.parse_raw(json.dumps({"products": [product]}), fetched_at=FETCHED_AT))

    assert len(captures) == 1
    meta = captures[0].metadata
    assert meta["variant_count"] == 2
    assert meta["title"] == "256GB DDR4 RDIMM — 2933MHz"
    assert meta["condition_raw"] == "Used"
    assert meta["price"] == 120.0
    assert meta["availability"] == "OutOfStock"

    variants = meta["variants"]
    assert variants[0]["variant_id"] == "201"
    assert variants[1]["title"] == "256GB DDR4 RDIMM — 3200MHz"
    assert variants[1]["availability"] == "InStock"
    assert variants[1]["listed_price"] is None


def test_product_without_variants_still_yields_capture() -> None:
    adapter = WaterpantherAdapter()
    product = {"id": 303, "title": "New: HBA Card", "handle": "hba-card"}
    captures = list(adapter.parse_raw(json.dumps({"products": [product]}), fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert capture.source_listing_id == "303"
    assert capture.url == "https://www.waterpanther.com/products/hba-card"
    assert capture.metadata["title"] == "HBA Card"
    assert capture.metadata["condition_raw"] == "New"
    assert capture.metadata["price"] is None
    assert capture.metadata["variant_count"] == 1


def test_default_title_variant_does_not_append_to_title() -> None:
    adapter = WaterpantherAdapter()
    product = {
        "id": 404,
        "title": "1.2TB SAS HDD",
        "handle": "1-2tb-sas-hdd",
        "variants": [{"id": 405, "title": "Default Title", "price": "576.00"}],
    }
    captures = list(adapter.parse_raw(json.dumps({"products": [product]}), fetched_at=FETCHED_AT))

    assert captures[0].metadata["title"] == "1.2TB SAS HDD"


def test_invalid_items_are_captured_with_parse_error() -> None:
    adapter = WaterpantherAdapter()
    payload = json.dumps({"products": ["garbage-string", 42, SAMPLE_SHOPIFY_PRODUCT]})
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert len(captures) == 3
    flagged = [c for c in captures if c.metadata.get("parse_error")]
    assert len(flagged) == 2
    assert all(c.metadata["parse_error"] == "invalid_item" for c in flagged)
    assert "garbage-string" in flagged[0].raw_payload
    assert "42" in flagged[1].raw_payload
    for capture in flagged:
        assert capture.source_listing_id
        assert capture.url
        RawCapture.model_validate(capture.model_dump())

    good = [c for c in captures if not c.metadata.get("parse_error")]
    assert good[0].source_listing_id == "5160409890949"


def test_scalar_root_payload_yields_no_items_found_capture() -> None:
    adapter = WaterpantherAdapter()
    payload = json.dumps("just a scalar")
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert capture.metadata["parse_error"] == "no_items_found"
    assert capture.raw_payload == payload
    assert capture.source_listing_id
    RawCapture.model_validate(capture.model_dump())


def test_empty_product_list_yields_no_items_found_capture() -> None:
    adapter = ServerPartDealsAdapter()
    captures = list(adapter.parse_raw(json.dumps({"products": []}), fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].metadata["parse_error"] == "no_items_found"


def test_load_fixtures_from_corpus() -> None:
    adapter = WaterpantherAdapter()
    if adapter.fixture_path is None or not adapter.fixture_path.exists():
        pytest.skip("legacy fixture corpus not available")

    captures = list(adapter.load_fixtures(max_count=1))
    assert len(captures) == 250
    for capture in captures:
        assert capture.source == "waterpanther"
        assert capture.payload_format == "json"
        assert capture.metadata["fixture_file"].endswith("collections_all_p1.json")
        assert capture.source_listing_id



REDDIT_FIXTURE_ROOT = Path("/home/coldaine/TechdealsHandoff/scripts/ingest/reddit_homelabsales")
HLS_ATOM = REDDIT_FIXTURE_ROOT / "fixtures" / "sample_atom.xml"
HWS_ATOM = REDDIT_FIXTURE_ROOT / "fixtures" / "sample_hws_atom.xml"


def _atom_entry(
    entry_id: str,
    title: str,
    url: str,
    content_html: str = "",
    author: str | None = None,
    updated: str = "2026-08-15T20:00:00+00:00",
) -> str:
    lines = ["  <entry>"]
    if author is not None:
        lines.append(f"    <author><name>{author}</name></author>")
    lines.append(f'    <content type="html">{content_html}</content>')
    lines.append(f"    <id>{entry_id}</id>")
    lines.append(f'    <link href="{url}" />')
    lines.append(f"    <title>{title}</title>")
    lines.append(f"    <updated>{updated}</updated>")
    lines.append("  </entry>")
    return "\n".join(lines)


def _atom_feed(*entries: str, atom_ns: str = "http://www.w3.org/2005/Atom") -> str:
    xmlns = f' xmlns="{atom_ns}"' if atom_ns else ""
    header = f'<?xml version="1.0" encoding="UTF-8"?>\n<feed{xmlns}>\n'
    return header + "\n".join(entries) + "\n</feed>"


HLS_SALE_ENTRY = _atom_entry(
    entry_id="t3_abc123",
    title="[FS][US-MI] Seagate Exos HDDs and SSD",
    url="https://www.reddit.com/r/homelabsales/comments/abc123/fsusmi_drives/",
    content_html="&lt;p&gt;4x 8TB Seagate Exos SATA HDDs $280&lt;/p&gt;",
    author="/u/testseller",
)
HLS_WANT_ENTRY = _atom_entry(
    entry_id="t3_wanted1",
    title="[W][US-E] 18TB drives",
    url="https://www.reddit.com/r/homelabsales/comments/wanted1/wuse_wtb/",
    content_html="&lt;p&gt;Looking for 4x 18TB Exos $100 each&lt;/p&gt;",
    author="/u/buyer",
    updated="2026-08-15T20:10:00+00:00",
)
HWS_SALE_ENTRY = _atom_entry(
    entry_id="t3_hwssale1",
    title="[USA-TN] [H] RTX 3090 FE 24GB [W] $575 PayPal",
    url="https://www.reddit.com/r/hardwareswap/comments/hwssale1/h_rtx_3090_w_paypal/",
    content_html="&lt;p&gt;Lightly used, includes original box.&lt;/p&gt;",
    author="/u/gpuseller",
)
HWS_WTB_ENTRY = _atom_entry(
    entry_id="t3_hwswtb1",
    title="[USA-TN] [H] PayPal [W] RTX 3090 FE",
    url="https://www.reddit.com/r/hardwareswap/comments/hwswtb1/h_paypal_w_rtx_3090/",
    content_html="&lt;p&gt;Budget around $600 depending on condition.&lt;/p&gt;",
    author="/u/gpubuyer",
    updated="2026-08-15T20:05:00+00:00",
)
HWS_TRADE_ENTRY = _atom_entry(
    entry_id="t3_hwstrade1",
    title="[USA-TN] [H] RTX 3090 FE [W] RTX 4070 Ti",
    url="https://www.reddit.com/r/hardwareswap/comments/hwstrade1/h_rtx_3090_w_4070ti/",
    content_html="&lt;p&gt;Looking to trade locally.&lt;/p&gt;",
    author="/u/trader",
    updated="2026-08-15T20:10:00+00:00",
)
NSLESS_ENTRY = _atom_entry(
    entry_id="t3_nsless1",
    title="[FS][US-CA] 8TB SAS",
    url="https://www.reddit.com/r/homelabsales/comments/nsless1/fsusca_sas/",
    content_html="&lt;p&gt;8TB SAS $80&lt;/p&gt;",
    author="/u/nsless",
    updated="2026-08-15T21:00:00+00:00",
)

SAMPLE_HLS_ATOM = _atom_feed(HLS_SALE_ENTRY, HLS_WANT_ENTRY)
SAMPLE_HWS_ATOM = _atom_feed(HWS_SALE_ENTRY, HWS_WTB_ENTRY, HWS_TRADE_ENTRY)
NO_NAMESPACE_ATOM = _atom_feed(NSLESS_ENTRY, atom_ns="")


def test_reddit_atom_feed_yields_one_capture_per_entry() -> None:
    adapter = RedditHomelabsalesAdapter()
    captures = list(adapter.parse_raw(SAMPLE_HLS_ATOM, fetched_at=FETCHED_AT))

    assert len(captures) == 2
    assert [c.source_listing_id for c in captures] == ["t3_abc123", "t3_wanted1"]
    for capture in captures:
        assert capture.source == "reddit_homelabsales"
        assert capture.payload_format == "atom"
        assert capture.url.startswith("https://www.reddit.com/r/homelabsales/comments/")


def test_reddit_extracts_title_author_link_content_updated() -> None:
    adapter = RedditHomelabsalesAdapter()
    capture = next(adapter.parse_raw(SAMPLE_HLS_ATOM, fetched_at=FETCHED_AT))

    expected_url = "https://www.reddit.com/r/homelabsales/comments/abc123/fsusmi_drives/"
    assert capture.url == expected_url
    meta = capture.metadata
    assert meta["title"] == "[FS][US-MI] Seagate Exos HDDs and SSD"
    assert meta["author"] == "testseller"
    assert meta["content_html"] == "<p>4x 8TB Seagate Exos SATA HDDs $280</p>"
    assert meta["updated"] == "2026-08-15T20:00:00+00:00"
    assert meta["post_id"] == "abc123"
    assert meta["community"] == "homelabsales"
    assert meta["location"] == "US-MI"
    assert capture.fetched_at == FETCHED_AT


def test_reddit_capture_is_valid_raw_capture() -> None:
    adapter = RedditHomelabsalesAdapter()
    capture = next(adapter.parse_raw(SAMPLE_HLS_ATOM, fetched_at=FETCHED_AT))

    assert isinstance(capture, RawCapture)
    assert capture.status == IngestionStatus.raw
    assert capture.checksum == hashlib.sha256(capture.raw_payload.encode()).hexdigest()
    assert "t3_abc123" in capture.raw_payload
    assert "Seagate Exos" in capture.raw_payload
    RawCapture.model_validate(capture.model_dump())


def test_homelabsales_listing_types_mark_want_posts() -> None:
    adapter = RedditHomelabsalesAdapter()
    captures = list(adapter.parse_raw(SAMPLE_HLS_ATOM, fetched_at=FETCHED_AT))

    assert [c.metadata["listing_type"] for c in captures] == ["sale", "want"]
    assert classify_listing_type("homelabsales", "[FS][US-MI] HDDs") == "sale"
    assert classify_listing_type("homelabsales", "[WTS][US-MI] HDDs") == "sale"
    assert classify_listing_type("homelabsales", "[WTB][US-E] 18TB drives") == "want"
    assert classify_listing_type("homelabsales", "[FREE][US-CA] old RAM") == "free"


def test_want_posts_flagged_for_later_quarantine() -> None:
    adapter = RedditHomelabsalesAdapter()
    parsed = adapter.parse_raw(SAMPLE_HLS_ATOM, fetched_at=FETCHED_AT)
    captures = {c.source_listing_id: c for c in parsed}

    assert captures["t3_wanted1"].metadata["listing_type"] == "want"
    assert captures["t3_abc123"].metadata["listing_type"] == "sale"


def test_hardwareswap_hw_w_title_semantics() -> None:
    adapter = RedditHardwareswapAdapter()
    parsed = adapter.parse_raw(SAMPLE_HWS_ATOM, fetched_at=FETCHED_AT)
    captures = {c.source_listing_id: c for c in parsed}

    sale = captures["t3_hwssale1"]
    assert sale.metadata["listing_type"] == "sale"
    assert sale.metadata["have"] == "RTX 3090 FE 24GB"
    assert sale.metadata["want"] == "$575 PayPal"
    assert sale.metadata["location"] == "US-TN"
    assert sale.metadata["author"] == "gpuseller"

    assert captures["t3_hwswtb1"].metadata["listing_type"] == "want"
    assert captures["t3_hwstrade1"].metadata["listing_type"] == "trade"
    hws_want = "[USA-TN] [H] PayPal [W] RTX 3090 FE"
    hws_bundle = "[USA-VA] [H] RTX 3090 FE + 5800X3D [W] $700"
    assert classify_listing_type("hardwareswap", hws_want) == "want"
    assert classify_listing_type("hardwareswap", hws_bundle) == "sale"


def test_duplicate_atom_entry_is_parsed_once() -> None:
    adapter = RedditHardwareswapAdapter()
    duplicated = _atom_feed(HWS_SALE_ENTRY, HWS_WTB_ENTRY, HWS_TRADE_ENTRY, HWS_SALE_ENTRY)
    captures = list(adapter.parse_raw(duplicated, fetched_at=FETCHED_AT))

    assert len(captures) == 3
    ids = [c.source_listing_id for c in captures]
    assert ids == ["t3_hwssale1", "t3_hwswtb1", "t3_hwstrade1"]


def test_atom_namespace_is_handled_both_ways() -> None:
    adapter = RedditHomelabsalesAdapter()
    namespaced = list(adapter.parse_raw(SAMPLE_HLS_ATOM, fetched_at=FETCHED_AT))
    unnamespaced = list(adapter.parse_raw(NO_NAMESPACE_ATOM, fetched_at=FETCHED_AT))

    assert len(namespaced) == 2
    assert len(unnamespaced) == 1
    assert unnamespaced[0].metadata["title"] == "[FS][US-CA] 8TB SAS"
    assert unnamespaced[0].metadata["author"] == "nsless"


def test_entry_without_title_is_flagged_not_dropped() -> None:
    adapter = RedditHomelabsalesAdapter()
    xml = _atom_feed(
        "  <entry>\n"
        "    <id>t3_notitle</id>\n"
        '    <link href="https://www.reddit.com/r/homelabsales/comments/notitle/x/" />\n'
        "    <updated>2026-08-15T20:00:00+00:00</updated>\n"
        "  </entry>"
    )
    captures = list(adapter.parse_raw(xml, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert capture.source_listing_id == "t3_notitle"
    assert capture.metadata["parse_error"] == "missing_title"
    assert capture.metadata["listing_type"] == "unknown"
    assert "t3_notitle" in capture.raw_payload


def test_entries_without_id_or_link_get_unique_fallback_ids() -> None:
    adapter = RedditHomelabsalesAdapter()
    xml = _atom_feed(
        "  <entry>\n"
        "    <title>[FS][US-CA] 8TB SAS</title>\n"
        "    <updated>2026-08-15T20:00:00+00:00</updated>\n"
        "  </entry>",
        "  <entry>\n"
        "    <title>[FS][US-NY] 16TB SATA</title>\n"
        "    <updated>2026-08-15T20:05:00+00:00</updated>\n"
        "  </entry>",
    )
    captures = list(adapter.parse_raw(xml, fetched_at=FETCHED_AT))

    assert len(captures) == 2
    ids = [c.source_listing_id for c in captures]
    assert ids[0] != ids[1]
    for capture in captures:
        assert capture.source_listing_id
        assert capture.url.startswith("urn:techdeals:reddit_homelabsales:")
        RawCapture.model_validate(capture.model_dump())


def test_missing_id_falls_back_to_url_and_author_is_optional() -> None:
    adapter = RedditHomelabsalesAdapter()
    xml = _atom_feed(
        "  <entry>\n"
        '    <content type="html">&lt;p&gt;text&lt;/p&gt;</content>\n'
        '    <link href="https://www.reddit.com/r/homelabsales/comments/fbck12/x/" />\n'
        "    <title>[FS][US-E] DDR4 RAM</title>\n"
        "    <updated>2026-08-15T20:00:00+00:00</updated>\n"
        "  </entry>"
    )
    capture = next(adapter.parse_raw(xml, fetched_at=FETCHED_AT))

    assert capture.source_listing_id == "fbck12"
    assert capture.metadata["author"] is None
    assert capture.metadata["created_at"] is None


def test_reddit_passthrough_source_url_and_metadata() -> None:
    adapter = RedditHomelabsalesAdapter()
    feed_url = "https://www.reddit.com/r/homelabsales/new.rss?limit=100"
    capture = next(
        adapter.parse_raw(
            SAMPLE_HLS_ATOM,
            source_url=feed_url,
            fetched_at=FETCHED_AT,
            metadata={"status_code": 200},
        )
    )

    assert capture.metadata["source_url"] == feed_url
    assert capture.metadata["status_code"] == 200


def test_registry_discovers_both_reddit_sources() -> None:
    sources = list_sources()
    assert "reddit_homelabsales" in sources
    assert "reddit_hardwareswap" in sources

    hls = get_adapter("reddit_homelabsales")
    hws = get_adapter("reddit_hardwareswap")
    assert isinstance(hls, RedditHomelabsalesAdapter)
    assert isinstance(hws, RedditHardwareswapAdapter)
    assert isinstance(hls, RedditAtomAdapter)
    assert hls.source_name == "reddit_homelabsales"
    assert hws.source_name == "reddit_hardwareswap"
    assert hls.fixture_path is not None and hws.fixture_path is not None
    assert hls.fixture_path != hws.fixture_path


def test_reddit_load_fixtures_from_corpus() -> None:
    if not HLS_ATOM.exists() or not HWS_ATOM.exists():
        pytest.skip("legacy fixture corpus not available")

    hls = RedditHomelabsalesAdapter()
    hls_captures = list(hls.load_fixtures())
    assert len(hls_captures) == 3
    assert [c.source_listing_id for c in hls_captures] == ["t3_abc123", "t3_def456", "t3_wanted1"]
    for capture in hls_captures:
        assert capture.source == "reddit_homelabsales"
        assert capture.payload_format == "atom"
        assert capture.metadata["fixture_file"].endswith("sample_atom.xml")

    hws = RedditHardwareswapAdapter()
    hws_captures = list(hws.load_fixtures())
    assert len(hws_captures) == 4
    assert [c.source_listing_id for c in hws_captures] == [
        "t3_hwssale1",
        "t3_hwswtb1",
        "t3_hwstrade1",
        "t3_hwsamb1",
    ]
    assert [c.metadata["listing_type"] for c in hws_captures] == ["sale", "want", "trade", "sale"]
    for capture in hws_captures:
        assert capture.source == "reddit_hardwareswap"
        assert capture.metadata["fixture_file"].endswith("sample_hws_atom.xml")


def _tmp_shopify_adapter(fixture_dir: Path) -> SourceAdapter:
    class TmpFixtureAdapter(ShopifyAdapter):
        source_name = "tmp_fixture_source"
        base_url = "https://tmp.example.com"

    adapter = TmpFixtureAdapter()
    adapter.fixture_path = fixture_dir
    return adapter


def test_load_fixtures_flags_bad_file_and_continues(tmp_path: Path) -> None:
    bad_content = '{"products": [ {"id": 1, '
    (tmp_path / "bad.json").write_text(bad_content)
    (tmp_path / "good.json").write_text(json.dumps({"products": [SAMPLE_SHOPIFY_PRODUCT]}))

    adapter = _tmp_shopify_adapter(tmp_path)
    captures = list(adapter.load_fixtures())

    good = [c for c in captures if not c.metadata.get("parse_error")]
    assert [c.source_listing_id for c in good] == ["5160409890949"]

    failures = [c for c in captures if c.metadata.get("parse_error")]
    assert len(failures) == 1
    failure = failures[0]
    assert failure.raw_payload == bad_content
    assert "JSONDecodeError" in failure.metadata["parse_error"]
    assert failure.metadata["fixture_file"].endswith("bad.json")
    assert failure.status == IngestionStatus.failed
    RawCapture.model_validate(failure.model_dump())


def test_fixture_fetched_at_is_deterministic_mtime(tmp_path: Path) -> None:
    (tmp_path / "good.json").write_text(json.dumps({"products": [SAMPLE_SHOPIFY_PRODUCT]}))
    fixture_file = tmp_path / "good.json"
    expected = datetime.fromtimestamp(fixture_file.stat().st_mtime, tz=timezone.utc)

    adapter = _tmp_shopify_adapter(tmp_path)
    first = list(adapter.load_fixtures())
    second = list(adapter.load_fixtures())

    assert [c.fetched_at for c in first] == [expected]
    assert [c.fetched_at for c in second] == [expected]


def test_load_all_yields_failure_capture_instead_of_printing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExplodingAdapter(SourceAdapter):
        source_name = "exploding_source"
        fixture_path = None

        def parse_raw(self, raw_data, source_url="", fetched_at=None, metadata=None):
            return iter(())

        def load_fixtures(self, max_count=None):
            raise RuntimeError("boom")

    monkeypatch.setitem(adapter_base._REGISTRY, "exploding_source", ExplodingAdapter)
    captures = [c for c in load_all(max_per_source=1) if c.source == "exploding_source"]

    assert len(captures) == 1
    assert "boom" in captures[0].metadata["parse_error"]
    assert captures[0].status == IngestionStatus.failed
    RawCapture.model_validate(captures[0].model_dump())


RACKRAT_FIXTURE_ROOT = Path("/home/coldaine/big-racks/pipeline/tests/fixtures")

SAMPLE_RACKRAT_HIT = {
    "id": "v1_800743032157_0",
    "ebay_item": "v1|800743032157|0",
    "title": "HPE ProLiant DL360 Gen10 Plus, 2 x Gold 6342, 64GB RAM",
    "price": 6648.0,
    "shipping_cost": 0.0,
    "total_cost": 6648.0,
    "price_usd": 8733.03,
    "shipping_cost_usd": 0.0,
    "total_cost_usd": 8733.03,
    "currency": "GBP",
    "url": "https://www.ebay.co.uk/itm/800743032157",
    "photo_url": "https://i.ebayimg.com/images/g/test/s-l225.jpg",
    "condition": "Excellent - Refurbished",
    "active": True,
    "first_found": 1790862775,
    "last_seen": 1791311652,
    "ram_gb": 64,
    "cpu_model": "Xeon Gold 6342",
    "cpu_count": 2,
    "brand": "HPE",
    "model": "ProLiant DL360",
    "form_factor": "Unknown",
    "generation": "Gen10",
    "bay_count": None,
    "psu_count": 2,
    "psu_watts": None,
    "rails_included": None,
    "storage_total_gb": 3276,
    "ssd_total_gb": None,
    "product_type": "SERVER",
    "marketplace_id": "EBAY_GB",
    "region": "Europe",
    "country_name": "United Kingdom",
    "location_country": "GB",
    "requires_shipping_arrangement": False,
}

SAMPLE_RACKRAT_HIT_2 = {
    "id": "v1_327366233574_0",
    "ebay_item": "v1|327366233574|0",
    "title": "Dell R7525 12-Bay SERVER w/ 2x AMD EPYC 7513",
    "price": 7000.0,
    "total_cost": 7000.0,
    "price_usd": 4580.21,
    "total_cost_usd": 4580.21,
    "currency": "AUD",
    "url": "https://www.ebay.com.au/itm/327366233574",
    "condition": "Used",
    "active": True,
    "ram_gb": 128,
    "cpu_model": "EPYC 7513",
    "cpu_count": 2,
    "brand": "Dell",
    "model": "PowerEdge R7525",
    "product_type": "SERVER",
    "marketplace_id": "EBAY_AU",
    "country_name": "Australia",
}

SAMPLE_RACKRAT_SNAPSHOT_LISTING = {
    "id": "v1_294843480501_0",
    "ebayItemId": 294843480501,
    "title": "Cisco UCS B200 M4 Blade Server barebone chassis",
    "brand": "Cisco",
    "model": "UCS B200 M4",
    "condition": "Gebraucht",
    "canonicalCondition": "used",
    "status": "active",
    "url": "https://www.ebay.at/itm/294843480501",
    "photoUrl": "https://i.ebayimg.com/images/g/test/s-l225.jpg",
    "pricing": {"priceUsd": 71.1, "shippingUsd": 10.36, "totalUsd": 81.46, "currency": "EUR"},
    "ram": {"capacityGb": 64, "type": "DDR4", "slotsTotal": 24},
    "cpu": {
        "model": "E5-2620 v3",
        "count": 1,
        "tier": 2,
        "platformClasses": [],
        "passmarkScore": 6000,
    },
    "storage": {
        "includedGb": None,
        "ssdGb": None,
        "bayCount": 2,
        "sffBays": 2,
        "lffBays": None,
        "driveBayTypes": [],
    },
    "psu": {"count": 2, "watts": 650},
    "rackUnits": None,
    "railsIncluded": False,
    "formFactor": "blade",
    "generation": None,
    "marketplaceId": "EBAY_AT",
    "region": "Europe",
    "country": "Austria",
    "firstFound": "2026-06-01T00:00:00+00:00",
    "lastSeen": "2026-06-15T00:00:00+00:00",
    "valueMetrics": {"usdPerGbRam": 1.27},
    "valueScore": 42,
}


def test_rackrat_parses_raw_meilisearch_hits_array() -> None:
    adapter = RackRatAdapter()
    payload = json.dumps([SAMPLE_RACKRAT_HIT, SAMPLE_RACKRAT_HIT_2])
    captures = list(
        adapter.parse_raw(payload, source_url="fixture://hits_sample.json", fetched_at=FETCHED_AT)
    )

    assert len(captures) == 2
    assert [c.source_listing_id for c in captures] == ["800743032157", "327366233574"]
    first = captures[0]
    assert first.source == "rackrat"
    assert first.url == "https://www.ebay.co.uk/itm/800743032157"
    assert first.payload_format == "json"
    assert first.fetched_at == FETCHED_AT

    meta = first.metadata
    assert meta["format"] == "rackrat_meilisearch_hit"
    assert meta["rackrat_id"] == "v1_800743032157_0"
    assert meta["ebay_item"] == "v1|800743032157|0"
    assert meta["ebay_item_id"] == "800743032157"
    assert meta["title"] == "HPE ProLiant DL360 Gen10 Plus, 2 x Gold 6342, 64GB RAM"
    assert meta["price"] == 6648.0
    assert meta["total_cost"] == 6648.0
    assert meta["total_cost_usd"] == 8733.03
    assert meta["currency"] == "GBP"
    assert meta["condition"] == "Excellent - Refurbished"
    assert meta["ram_gb"] == 64
    assert meta["cpu_model"] == "Xeon Gold 6342"
    assert meta["cpu_count"] == 2
    assert meta["product_type"] == "SERVER"
    assert meta["country"] == "United Kingdom"
    assert meta["first_found"] == datetime.fromtimestamp(1790862775, tz=timezone.utc).isoformat()
    assert meta["last_seen"] == datetime.fromtimestamp(1791311652, tz=timezone.utc).isoformat()
    assert meta["source_url"] == "fixture://hits_sample.json"


def test_rackrat_capture_is_valid_raw_capture() -> None:
    adapter = RackRatAdapter()
    capture = next(adapter.parse_raw(json.dumps([SAMPLE_RACKRAT_HIT]), fetched_at=FETCHED_AT))

    assert isinstance(capture, RawCapture)
    assert capture.status == IngestionStatus.raw
    assert capture.checksum == hashlib.sha256(capture.raw_payload.encode()).hexdigest()
    expected_checksum = hashlib.sha256(json.dumps(SAMPLE_RACKRAT_HIT).encode()).hexdigest()
    assert capture.checksum == expected_checksum
    assert json.loads(capture.raw_payload) == SAMPLE_RACKRAT_HIT
    RawCapture.model_validate(capture.model_dump())


def test_rackrat_parses_snapshot_listings_envelope() -> None:
    adapter = RackRatAdapter()
    snapshot = {
        "version": 1,
        "generatedAt": "2026-10-12T00:00:00+00:00",
        "source": "rackrat-meilisearch",
        "count": 2,
        "listings": [SAMPLE_RACKRAT_HIT, SAMPLE_RACKRAT_HIT_2],
    }
    captures = list(adapter.parse_raw(json.dumps(snapshot), fetched_at=FETCHED_AT))

    assert [c.source_listing_id for c in captures] == ["800743032157", "327366233574"]
    assert all(c.source == "rackrat" for c in captures)
    assert captures[0].metadata["title"] == SAMPLE_RACKRAT_HIT["title"]
    assert captures[1].metadata["title"] == SAMPLE_RACKRAT_HIT_2["title"]


def test_rackrat_parses_normalized_snapshot_listing() -> None:
    adapter = RackRatAdapter()
    snapshot = {"version": 1, "count": 1, "listings": [SAMPLE_RACKRAT_SNAPSHOT_LISTING]}
    capture = next(adapter.parse_raw(json.dumps(snapshot), fetched_at=FETCHED_AT))

    assert capture.source_listing_id == "294843480501"
    assert capture.url == "https://www.ebay.at/itm/294843480501"

    meta = capture.metadata
    assert meta["format"] == "rackrat_snapshot_listing"
    assert meta["title"] == "Cisco UCS B200 M4 Blade Server barebone chassis"
    assert meta["total_cost_usd"] == 81.46
    assert meta["price_usd"] == 71.1
    assert meta["currency"] == "EUR"
    assert meta["ram_gb"] == 64
    assert meta["cpu_model"] == "E5-2620 v3"
    assert meta["cpu_count"] == 1
    assert meta["condition"] == "Gebraucht"
    assert meta["active"] is True
    assert meta["first_found"] == "2026-06-01T00:00:00+00:00"


def test_rackrat_meilisearch_search_response_hits_envelope() -> None:
    adapter = RackRatAdapter()
    payload = json.dumps({"hits": [SAMPLE_RACKRAT_HIT], "estimatedTotalHits": 1})
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert len(captures) == 1
    assert captures[0].source_listing_id == "800743032157"


def test_rackrat_hit_without_ebay_item_falls_back_to_record_id() -> None:
    adapter = RackRatAdapter()
    hit = {
        "id": "v1_123456789012_0",
        "title": "Supermicro 1U",
        "url": "https://www.ebay.com/itm/123456789012",
    }
    capture = next(adapter.parse_raw(json.dumps([hit]), fetched_at=FETCHED_AT))

    assert capture.source_listing_id == "v1_123456789012_0"
    assert capture.metadata["ebay_item_id"] is None
    assert capture.metadata["rackrat_id"] == "v1_123456789012_0"


def test_rackrat_record_without_ids_gets_hash_and_urn_fallbacks() -> None:
    adapter = RackRatAdapter()
    capture = next(adapter.parse_raw(json.dumps({"title": "Mystery box"}), fetched_at=FETCHED_AT))

    assert capture.source_listing_id
    assert capture.url == f"urn:techdeals:rackrat:{capture.source_listing_id}"
    RawCapture.model_validate(capture.model_dump())


def test_rackrat_invalid_items_flagged_not_dropped() -> None:
    adapter = RackRatAdapter()
    payload = json.dumps([SAMPLE_RACKRAT_HIT, "garbage-string", 42])
    captures = list(adapter.parse_raw(payload, fetched_at=FETCHED_AT))

    assert len(captures) == 3
    flagged = [c for c in captures if c.metadata.get("parse_error")]
    assert len(flagged) == 2
    assert all(c.metadata["parse_error"] == "invalid_item" for c in flagged)
    assert flagged[0].raw_payload == "garbage-string"
    assert flagged[1].raw_payload == "42"
    for capture in flagged:
        assert capture.source_listing_id
        assert capture.url.startswith("urn:techdeals:rackrat:")
        RawCapture.model_validate(capture.model_dump())

    assert captures[0].source_listing_id == "800743032157"


def test_rackrat_empty_listings_yields_no_items_found() -> None:
    adapter = RackRatAdapter()
    captures = list(adapter.parse_raw(json.dumps({"listings": []}), fetched_at=FETCHED_AT))

    assert len(captures) == 1
    capture = captures[0]
    assert capture.metadata["parse_error"] == "no_items_found"
    assert capture.raw_payload == '{"listings": []}'
    RawCapture.model_validate(capture.model_dump())


def test_registry_discovers_rackrat() -> None:
    sources = list_sources()
    assert "rackrat" in sources

    adapter = get_adapter("rackrat")
    assert isinstance(adapter, RackRatAdapter)
    assert adapter.source_name == "rackrat"
    assert adapter.fixture_path == RACKRAT_FIXTURE_ROOT


def test_rackrat_load_fixtures_from_corpus() -> None:
    fixture_file = RACKRAT_FIXTURE_ROOT / "hits_sample.json"
    if not fixture_file.exists():
        pytest.skip("RackRat fixture corpus not available")

    expected = len(json.loads(fixture_file.read_text()))
    adapter = RackRatAdapter()
    captures = list(adapter.load_fixtures())

    assert len(captures) == expected
    assert captures[0].source_listing_id == "800743032157"
    for capture in captures:
        assert capture.source == "rackrat"
        assert capture.payload_format == "json"
        assert capture.source_listing_id
        assert capture.metadata["fixture_file"].endswith("hits_sample.json")
        RawCapture.model_validate(capture.model_dump())
