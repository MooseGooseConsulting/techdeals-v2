"""Shopify catalog adapter.

Parses Shopify ``/collections/all/products.json`` payloads (waterpanther,
serverpartdeals) and FusionWW's proprietary REST catalog items, which use a
flat record shape instead of Shopify's product/variant tree. Both shapes are
normalized into the same parsed fields before becoming RawCapture objects.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Iterator
from urllib.parse import urljoin

from techdeals.adapters.base import SourceAdapter, register_adapter
from techdeals.ingestion.contract import RawCapture

CONDITION_PREFIXES = ("Refurbished:", "New:", "Used:", "Open Box:")

LEGACY_FIXTURE_ROOT = Path("/home/coldaine/TechdealsHandoff/scripts/ingest")


def _num(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _split_condition_title(raw: str) -> tuple[str | None, str]:
    text = re.sub(r"\s+", " ", raw).strip()
    for prefix in CONDITION_PREFIXES:
        if text.lower().startswith(prefix.lower()):
            return prefix.rstrip(":"), text[len(prefix) :].strip()
    return None, text


def _availability_label(available: bool | None) -> str | None:
    if available is None:
        return None
    return "InStock" if available else "OutOfStock"


def _extract_items(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("products", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return [data]
    return []


def _is_fusion_item(item: dict[str, Any]) -> bool:
    if any(key in item for key in ("variants", "handle", "body_html")):
        return False
    return any(key in item for key in ("mpn", "productId", "manufacturer"))


class ShopifyAdapter(SourceAdapter):
    """Adapter for Shopify collection product JSON pages.

    One RawCapture is emitted per product (or per FusionWW catalog item). The
    capture's raw payload is that single product record; parsed fields land in
    metadata alongside any caller-supplied metadata.
    """

    source_name: ClassVar[str]
    base_url: ClassVar[str]

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        payload = raw_data.decode("utf-8") if isinstance(raw_data, bytes) else raw_data
        data = json.loads(payload)
        extra = dict(metadata or {})
        if source_url:
            extra.setdefault("source_url", source_url)

        items = _extract_items(data)
        if not items:
            yield self._make_capture(
                source=self.source_name,
                source_listing_id="",
                url=self.base_url,
                raw_payload=payload,
                payload_format="json",
                fetched_at=fetched_at,
                metadata={**extra, "parse_error": "no_items_found"},
            )
            return

        for item in items:
            if not isinstance(item, dict):
                raw_text = item if isinstance(item, str) else json.dumps(item)
                yield self._make_capture(
                    source=self.source_name,
                    source_listing_id="",
                    url=self.base_url,
                    raw_payload=raw_text,
                    payload_format="json",
                    fetched_at=fetched_at,
                    metadata={**extra, "parse_error": "invalid_item"},
                )
                continue
            if _is_fusion_item(item):
                listing_id, url, fields = self._parse_fusion_item(item)
            else:
                listing_id, url, fields = self._parse_shopify_product(item)
            yield self._make_capture(
                source=self.source_name,
                source_listing_id=listing_id,
                url=url,
                raw_payload=json.dumps(item),
                payload_format="json",
                fetched_at=fetched_at,
                metadata={**extra, **fields},
            )

    def _parse_shopify_product(self, product: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        product_id = str(product.get("id") or "") or str(product.get("handle") or "")
        handle = product.get("handle") or ""
        base_title = (product.get("title") or "").strip()
        url = urljoin(self.base_url + "/", f"products/{handle}") if handle else self.base_url

        variants = [v for v in (product.get("variants") or []) if isinstance(v, dict)]
        if variants:
            rows = [self._shopify_variant_row(base_title, variant) for variant in variants]
        else:
            condition_raw, title = _split_condition_title(base_title)
            rows = [
                {
                    "variant_id": product_id,
                    "sku": None,
                    "title": title,
                    "condition_raw": condition_raw,
                    "price": None,
                    "listed_price": None,
                    "availability": None,
                }
            ]

        first = rows[0]
        fields = {
            "product_id": product_id,
            "handle": handle,
            "title": first["title"],
            "condition_raw": first["condition_raw"],
            "sku": first["sku"],
            "price": first["price"],
            "listed_price": first["listed_price"],
            "availability": first["availability"],
            "vendor": product.get("vendor"),
            "product_type": product.get("product_type"),
            "tags": product.get("tags") or [],
            "variant_count": len(rows),
            "variants": rows,
        }
        return product_id, url, fields

    @staticmethod
    def _shopify_variant_row(base_title: str, variant: dict[str, Any]) -> dict[str, Any]:
        variant_id = str(variant.get("id") or "")
        sku = variant.get("sku") or None
        variant_title = (variant.get("title") or "").strip()
        if variant_title and variant_title.lower() != "default title":
            full_title = f"{base_title} — {variant_title}"
        else:
            full_title = base_title
        condition_raw, title = _split_condition_title(full_title)
        price = _num(variant.get("price"))
        listed = _num(variant.get("compare_at_price"))
        return {
            "variant_id": variant_id,
            "sku": str(sku) if sku else None,
            "title": title,
            "condition_raw": condition_raw,
            "price": price,
            "listed_price": listed if listed and listed != price else None,
            "availability": _availability_label(variant.get("available")),
        }

    def _parse_fusion_item(self, item: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        mpn = str(item.get("mpn") or item.get("sku") or "").strip()
        product_id = str(item.get("productId") or item.get("id") or "").strip()
        listing_id = product_id or mpn
        title = str(item.get("name") or item.get("title") or mpn).strip()

        manufacturer_raw = item.get("manufacturer")
        if isinstance(manufacturer_raw, dict):
            manufacturer = manufacturer_raw.get("name")
        elif isinstance(manufacturer_raw, str):
            manufacturer = manufacturer_raw
        else:
            manufacturer = None

        category = item.get("category")
        if not category and isinstance(item.get("taxonomy"), list):
            category = " > ".join(str(entry) for entry in item["taxonomy"])

        price = _num(item.get("price") or item.get("unitPrice"))
        listed = _num(item.get("listPrice") or item.get("msrp"))
        quantity = _int(item.get("quantity") or item.get("totalAvailableQuantity"))
        lead_time_days = _int(item.get("leadTimeDays"))
        status = item.get("productStatus") or ("Active" if item.get("isActive") else "Inactive")

        attributes_raw = item.get("attributes")
        attributes: dict[str, Any] = {}
        if isinstance(attributes_raw, list):
            for attr in attributes_raw:
                if isinstance(attr, dict) and "name" in attr:
                    attributes[str(attr["name"])] = attr.get("value")
        elif isinstance(attributes_raw, dict):
            attributes = attributes_raw

        if item.get("url"):
            url = item["url"]
        elif mpn:
            url = urljoin(self.base_url + "/", f"product/{mpn}")
        else:
            url = self.base_url

        fields = {
            "mpn": mpn or None,
            "product_id": product_id or None,
            "title": title,
            "manufacturer": manufacturer,
            "category": category,
            "price": price,
            "listed_price": listed if listed and listed != price else None,
            "quantity": quantity,
            "lead_time_days": lead_time_days,
            "status": status,
            "attributes": attributes,
        }
        return listing_id, url, fields


@register_adapter
class WaterpantherAdapter(ShopifyAdapter):
    source_name = "waterpanther"
    base_url = "https://www.waterpanther.com"
    fixture_path = LEGACY_FIXTURE_ROOT / "waterpanther" / "fixtures"


@register_adapter
class ServerPartDealsAdapter(ShopifyAdapter):
    source_name = "serverpartdeals"
    base_url = "https://serverpartdeals.com"
    fixture_path = LEGACY_FIXTURE_ROOT / "serverpartdeals" / "fixtures"


@register_adapter
class FusionwwAdapter(ShopifyAdapter):
    source_name = "fusionww"
    base_url = "https://www.fusionww.com"
    fixture_path = LEGACY_FIXTURE_ROOT / "fusionww" / "fixtures"
