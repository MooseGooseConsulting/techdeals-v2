"""RackRat adapter for server listings (big-racks Meilisearch corpus).

Parses RackRat's JSON listing exports in two envelope shapes:

- ``hits_sample.json`` style — a bare JSON array of raw Meilisearch hits
  (``id``, ``ebay_item``, ``title``, ``price``, ``total_cost_usd``,
  ``currency``, ``url``, ``condition``, ``ram_gb``, ``cpu_model``, ...)
- ``snapshot.json`` style — an object with a ``listings`` array, whose
  records are either raw hits or normalized snapshot listings (nested
  ``pricing``/``ram``/``cpu`` blocks, camelCase keys). A Meilisearch
  search response (``{"hits": [...]}``) is accepted as well.

One RawCapture is emitted per listing record. The capture's identity is the
canonical eBay item id parsed from ``ebay_item`` (``v1|<id>|<var>``), so
re-listings under new RackRat record ids stay one posting; the RackRat
record id is preserved in metadata alongside the other extracted fields.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Iterator

from techdeals.adapters.base import SourceAdapter, register_adapter
from techdeals.ingestion.contract import RawCapture

RACKRAT_FIXTURE_ROOT = Path(
    os.environ.get("RACKRAT_FIXTURE_ROOT", "/home/coldaine/big-racks/pipeline/tests/fixtures")
)

_EBAY_ITEM = re.compile(r"v1\|(\d+)\|")

_SNAPSHOT_MARKER_KEYS = ("ebayItemId", "valueMetrics", "canonicalCondition")

_UNIX_SECONDS_MIN = 0
_UNIX_SECONDS_MAX = 4102444800

_EBAY_DOMAIN_BY_MARKETPLACE = {
    "EBAY_US": "www.ebay.com",
    "EBAY_UK": "www.ebay.co.uk",
    "EBAY_GB": "www.ebay.co.uk",
    "EBAY_AU": "www.ebay.com.au",
    "EBAY_AT": "www.ebay.at",
    "EBAY_DE": "www.ebay.de",
    "EBAY_CA": "www.ebay.ca",
    "EBAY_FR": "www.ebay.fr",
    "EBAY_IT": "www.ebay.it",
    "EBAY_ES": "www.ebay.es",
    "EBAY_IE": "www.ebay.ie",
    "EBAY_NL": "www.ebay.nl",
}


def _ebay_item_id(hit: dict[str, Any]) -> str | None:
    match = _EBAY_ITEM.search(hit.get("ebay_item") or "")
    return match.group(1) if match else None


def _iso_ts(value: Any) -> Any:
    """Unix seconds -> ISO-8601; strings pass through, junk is preserved."""
    if value is None or isinstance(value, str):
        return value
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return value
    if not (_UNIX_SECONDS_MIN <= seconds <= _UNIX_SECONDS_MAX):
        return value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (OverflowError, TypeError, ValueError, OSError):
        return value


def _is_snapshot_listing(record: dict[str, Any]) -> bool:
    if any(key in record for key in _SNAPSHOT_MARKER_KEYS):
        return True
    return any(isinstance(record.get(key), dict) for key in ("pricing", "ram", "cpu", "storage"))


def _flatten_snapshot_listing(listing: dict[str, Any]) -> dict[str, Any]:
    """Map a normalized snapshot listing back onto the raw-hit key space."""
    pricing = listing.get("pricing") or {}
    ram = listing.get("ram") or {}
    cpu = listing.get("cpu") or {}
    storage = listing.get("storage") or {}
    psu = listing.get("psu") or {}
    status = listing.get("status")
    ebay_item_id = listing.get("ebayItemId")
    return {
        "ebay_item": None,
        "ebay_item_id": str(ebay_item_id) if ebay_item_id is not None else None,
        "rackrat_id": listing.get("rackratId") or listing.get("id"),
        "title": listing.get("title"),
        "price": None,
        "shipping_cost": None,
        "total_cost": None,
        "price_usd": pricing.get("priceUsd"),
        "shipping_cost_usd": pricing.get("shippingUsd"),
        "total_cost_usd": pricing.get("totalUsd"),
        "currency": pricing.get("currency"),
        "condition": listing.get("condition"),
        "ram_gb": ram.get("capacityGb"),
        "cpu_model": cpu.get("model"),
        "cpu_count": cpu.get("count"),
        "brand": listing.get("brand"),
        "model": listing.get("model"),
        "form_factor": listing.get("formFactor"),
        "generation": listing.get("generation"),
        "storage_total_gb": storage.get("includedGb"),
        "bay_count": storage.get("bayCount"),
        "psu_count": psu.get("count"),
        "psu_watts": psu.get("watts"),
        "rack_units": listing.get("rackUnits"),
        "rails_included": listing.get("railsIncluded"),
        "product_type": None,
        "active": {"active": True, "ended": False}.get(status) if status else None,
        "marketplace_id": listing.get("marketplaceId"),
        "region": listing.get("region"),
        "country": listing.get("country"),
        "first_found": _iso_ts(listing.get("firstFound")),
        "last_seen": _iso_ts(listing.get("lastSeen")),
    }


def _hit_fields(hit: dict[str, Any]) -> dict[str, Any]:
    """Extract metadata fields from a raw Meilisearch hit."""
    return {
        "ebay_item": hit.get("ebay_item"),
        "ebay_item_id": _ebay_item_id(hit),
        "rackrat_id": hit.get("id"),
        "title": hit.get("title"),
        "price": hit.get("price"),
        "shipping_cost": hit.get("shipping_cost"),
        "total_cost": hit.get("total_cost"),
        "price_usd": hit.get("price_usd"),
        "shipping_cost_usd": hit.get("shipping_cost_usd"),
        "total_cost_usd": hit.get("total_cost_usd"),
        "currency": hit.get("currency"),
        "condition": hit.get("condition"),
        "ram_gb": hit.get("ram_gb"),
        "cpu_model": hit.get("cpu_model"),
        "cpu_count": hit.get("cpu_count"),
        "brand": hit.get("brand"),
        "model": hit.get("model"),
        "form_factor": hit.get("form_factor"),
        "generation": hit.get("generation"),
        "storage_total_gb": hit.get("storage_total_gb"),
        "bay_count": hit.get("bay_count"),
        "psu_count": hit.get("psu_count"),
        "psu_watts": hit.get("psu_watts"),
        "rack_units": hit.get("rack_units"),
        "rails_included": hit.get("rails_included"),
        "product_type": hit.get("product_type"),
        "active": hit.get("active"),
        "marketplace_id": hit.get("marketplace_id"),
        "region": hit.get("region"),
        "country": hit.get("country_name") or hit.get("location_country"),
        "first_found": _iso_ts(hit.get("first_found")),
        "last_seen": _iso_ts(hit.get("last_seen")),
    }


def _record_fields(record: dict[str, Any]) -> dict[str, Any]:
    if _is_snapshot_listing(record):
        fields = _flatten_snapshot_listing(record)
        fields["format"] = "rackrat_snapshot_listing"
    else:
        fields = _hit_fields(record)
        fields["format"] = "rackrat_meilisearch_hit"
    return fields


def _extract_records(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("listings", "hits"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return [data]
    return []


def _fallback_url(fields: dict[str, Any]) -> str:
    """Best-effort listing URL when the record carries none."""
    ebay_item_id = fields.get("ebay_item_id")
    if ebay_item_id:
        marketplace = str(fields.get("marketplace_id") or "").upper()
        domain = _EBAY_DOMAIN_BY_MARKETPLACE.get(marketplace, "www.ebay.com")
        return f"https://{domain}/itm/{ebay_item_id}"
    return ""


@register_adapter
class RackRatAdapter(SourceAdapter):
    """Adapter for RackRat Meilisearch listing exports.

    Accepts bare hit arrays, ``{"listings": [...]}`` snapshots, and
    ``{"hits": [...]}`` search responses. One RawCapture is emitted per
    listing record; records that are not JSON objects are flagged with
    ``metadata["parse_error"]`` instead of being dropped.
    """

    source_name: ClassVar[str] = "rackrat"
    fixture_path: ClassVar[Path | None] = RACKRAT_FIXTURE_ROOT

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
        max_items: int | None = None,
    ) -> Iterator[RawCapture]:
        payload = raw_data.decode("utf-8") if isinstance(raw_data, bytes) else raw_data
        data = json.loads(payload)
        extra = dict(metadata or {})
        if source_url:
            extra.setdefault("source_url", source_url)

        records = _extract_records(data)
        if not records:
            yield self._make_capture(
                source=self.source_name,
                source_listing_id="",
                url="",
                raw_payload=payload,
                payload_format="json",
                fetched_at=fetched_at,
                metadata={**extra, "parse_error": "no_items_found"},
            )
            return

        if max_items is not None:
            records = records[: max(0, max_items)]

        for record in records:
            if not isinstance(record, dict):
                raw_text = record if isinstance(record, str) else json.dumps(record)
                yield self._make_capture(
                    source=self.source_name,
                    source_listing_id="",
                    url="",
                    raw_payload=raw_text,
                    payload_format="json",
                    fetched_at=fetched_at,
                    metadata={**extra, "parse_error": "invalid_item"},
                )
                continue
            yield self._capture_for_record(record, extra, fetched_at)

    def _capture_for_record(
        self,
        record: dict[str, Any],
        extra: dict[str, Any],
        fetched_at: datetime | None,
    ) -> RawCapture:
        fields = _record_fields(record)
        listing_id = str(fields.get("ebay_item_id") or record.get("id") or "")
        url = record.get("url") or _fallback_url(fields)
        return self._make_capture(
            source=self.source_name,
            source_listing_id=listing_id,
            url=str(url) if url else "",
            raw_payload=json.dumps(record),
            payload_format="json",
            fetched_at=fetched_at,
            metadata={**extra, **fields},
        )
