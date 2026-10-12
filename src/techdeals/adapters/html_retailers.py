"""HTML retailer adapters for storefronts scraped as raw HTML.

Six sources whose legacy parsers lived in
``TechdealsHandoff/scripts/ingest/<source>/parse.py``:

- ``central_computers`` — Magento catalog pages (JSON-LD OfferCatalog with a
  ``li.product-item`` CSS fallback).
- ``diskprices`` — price-comparison table with header-name column mapping.
- ``goharddrive`` — Volusion storefront: sitemap product URLs plus product
  pages (microdata).
- ``serversupply`` — listing pages of ``div.productbox`` cards.
- ``serverorbit`` — CS-Cart grid listings.
- ``disctech`` — NetSuite listing pages plus the ``SC.CATEGORIES`` environment
  payload carrying embedded category JSON.

One RawCapture is emitted per product (per sitemap entry for goharddrive
sitemaps, per leaf category for disctech environment payloads); the raw
payload is that record's own markup/JSON and metadata carries the parsed
fields. Input that yields no products is emitted as a single capture whose
metadata carries ``parse_error`` instead of being dropped.
"""
from __future__ import annotations

import json
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Iterator
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from techdeals.adapters.base import (
    LEGACY_FIXTURE_ROOT,
    SourceAdapter,
    fallback_listing_id,
    register_adapter,
)
from techdeals.ingestion.contract import RawCapture

ParseRow = tuple[dict[str, Any], str, str]


# --- central_computers ------------------------------------------------------

CC_BASE_URL = "https://www.centralcomputer.com"


def _cc_availability_label(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.rsplit("/", 1)[-1] if "/" in raw else raw


def _cc_product_id_from_url(url: str) -> str | None:
    m = re.search(r"/quickview/catalog_product/view/id/(\d+)", url)
    return m.group(1) if m else None


def _cc_was_prices_by_url(soup: BeautifulSoup) -> dict[str, float]:
    prices: dict[str, float] = {}
    for item in soup.select("li.product-item"):
        link = item.select_one("a.product-item-photo, a.product-item-link")
        old = item.select_one(".old-price [data-price-amount]")
        if not link or not old:
            continue
        url = urljoin(CC_BASE_URL, link.get("href") or "").rstrip("/")
        val = SourceAdapter._num(old.get("data-price-amount") or old.get_text())
        if val is not None:
            prices[url] = val
    return prices


def _cc_parse_jsonld(soup: BeautifulSoup, was_prices: dict[str, float]) -> list[ParseRow]:
    rows: list[ParseRow] = []
    for script in soup.select('script[type="application/ld+json"]'):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "WebPage":
            continue
        catalog = data.get("mainEntity") or {}
        if catalog.get("@type") != "OfferCatalog":
            continue
        for element in catalog.get("itemListElement") or []:
            if not isinstance(element, dict):
                continue
            offers = element.get("offers") or {}
            url = (offers.get("url") or "").rstrip("/")
            sku = element.get("sku") or element.get("productID")
            product_id = str(sku) if sku else (_cc_product_id_from_url(url) or "")
            if not product_id:
                continue
            fields = {
                "product_id": product_id,
                "sku": str(sku) if sku else None,
                "title": (element.get("name") or "").strip(),
                "price": SourceAdapter._num(offers.get("price")),
                "listed_price": was_prices.get(url),
                "url": url,
                "availability": _cc_availability_label(offers.get("availability")),
                "manufacturer": element.get("brand") or None,
                "category_path": element.get("category"),
                "condition_raw": None,
            }
            rows.append((fields, json.dumps(element), "json"))
    return rows


def _cc_parse_css(soup: BeautifulSoup) -> list[ParseRow]:
    rows: list[ParseRow] = []
    for item in soup.select("li.product-item"):
        link = item.select_one("a.product-item-link, a.product-item-photo")
        if not link:
            continue
        href = link.get("href") or ""
        url = urljoin(CC_BASE_URL, href)
        price_el = item.select_one("[data-price-amount]")
        old_el = item.select_one(".old-price [data-price-amount]")
        pid = None
        price_box = item.select_one("[data-product-id]")
        if price_box:
            pid = price_box.get("data-product-id")
        if not pid:
            m = re.search(r"product-item-info_(\d+)", item.get("id") or "")
            pid = m.group(1) if m else _cc_product_id_from_url(url)
        if not pid:
            continue
        title_el = item.select_one(".product-item-name")
        title = title_el.get_text(" ", strip=True) if title_el else link.get("title") or ""
        fields = {
            "product_id": str(pid),
            "sku": None,
            "title": title,
            "price": SourceAdapter._num(price_el.get("data-price-amount") if price_el else None),
            "listed_price": SourceAdapter._num(old_el.get("data-price-amount") if old_el else None),
            "url": url,
            "availability": None,
            "manufacturer": None,
            "category_path": None,
            "condition_raw": None,
        }
        rows.append((fields, str(item), "html"))
    return rows


def _cc_parse_listing_page(html: str) -> list[ParseRow]:
    soup = BeautifulSoup(html, "html.parser")
    was_prices = _cc_was_prices_by_url(soup)
    rows = _cc_parse_jsonld(soup, was_prices)
    return rows if rows else _cc_parse_css(soup)


@register_adapter
class CentralComputersAdapter(SourceAdapter):
    """Adapter for centralcomputer.com catalog pages.

    One RawCapture per product. JSON-LD ``OfferCatalog`` items take precedence;
    when absent the ``li.product-item`` grid is parsed. Struck-through
    ``.old-price`` amounts are joined onto JSON-LD rows by product URL.
    """

    source_name: ClassVar[str] = "central_computers"
    fixture_path: ClassVar[Path | None] = LEGACY_FIXTURE_ROOT / "central_computers" / "fixtures"

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        html = self._decode(raw_data)
        extra = self._merge_extra(metadata, source_url)

        rows = _cc_parse_listing_page(html)
        if not rows:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=html,
                payload_format="html",
                source=self.source_name,
                source_listing_id=fallback_listing_id(html, prefix="product-"),
                url=CC_BASE_URL,
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        for fields, raw, fmt in rows:
            yield self._make_capture(
                source=self.source_name,
                source_listing_id=str(fields.get("product_id") or ""),
                url=str(fields.get("url") or "") or CC_BASE_URL,
                raw_payload=raw,
                payload_format=fmt,
                fetched_at=fetched_at,
                metadata={**extra, **fields},
            )


# --- diskprices -------------------------------------------------------------

DP_URL = "https://diskprices.com/"

_DP_HDR_PRICE_PER_TB = "Price per TB"
_DP_HDR_PRICE = "Price"
_DP_HDR_CAPACITY = "Capacity"
_DP_HDR_WARRANTY = "Warranty"
_DP_HDR_FORM = "Form"
_DP_HDR_TYPE = "Type"
_DP_HDR_CONDITION = "Condition"
_DP_HDR_LINK = "Affiliate Link"

_DP_HDR_ALIASES: dict[str, tuple[str, ...]] = {
    _DP_HDR_FORM: (_DP_HDR_FORM, "Form Factor"),
    _DP_HDR_TYPE: (_DP_HDR_TYPE, "Technology"),
}

_DP_COL_FALLBACK: dict[str, int] = {
    _DP_HDR_PRICE_PER_TB: 1,
    _DP_HDR_PRICE: 2,
    _DP_HDR_CAPACITY: 3,
    _DP_HDR_WARRANTY: 4,
    _DP_HDR_FORM: 5,
    _DP_HDR_TYPE: 6,
    _DP_HDR_CONDITION: 7,
}

_DP_REQUIRED_HEADERS = (_DP_HDR_PRICE_PER_TB, _DP_HDR_PRICE, _DP_HDR_CAPACITY)



def _dp_parse_capacity(cap_raw: str) -> tuple[float | None, int, float | None]:
    cap_match = re.search(r"([\d.]+)\s*TB(?:\s*x\s*(\d+))?", cap_raw, flags=re.I)
    if not cap_match:
        return None, 1, None
    tb = float(cap_match.group(1))
    packs = int(cap_match.group(2)) if cap_match.group(2) else 1
    return tb, packs, tb * packs


def _dp_norm_header(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ")).strip()


def _dp_build_col_map(table: Any) -> dict[str, int]:
    thead = table.find("thead")
    header_row = thead.find("tr") if thead else None
    if header_row is None:
        return {}
    headers = header_row.find_all(["th", "td"])
    return {_dp_norm_header(h.get_text()): i for i, h in enumerate(headers)}


def _dp_find_listing_table(soup: BeautifulSoup) -> tuple[Any, dict[str, int]]:
    tables = soup.find_all("table")
    for table in tables:
        col_map = _dp_build_col_map(table)
        if all(_dp_norm_header(h) in col_map for h in _DP_REQUIRED_HEADERS):
            return table, col_map
    saw_header_row = False
    for table in tables:
        if _dp_build_col_map(table):
            saw_header_row = True
            continue
        if table.find("tr", recursive=True) is not None:
            return table, {}
    if saw_header_row:
        raise ValueError(
            "diskprices: found a table with a header row but it is missing the "
            f"expected headers {list(_DP_REQUIRED_HEADERS)}; refusing positional "
            "fallback to avoid silent column mis-mapping (issue #39). A header "
            "may have been renamed on the source page."
        )
    return soup, {}


def _dp_col(name: str, col_map: dict[str, int]) -> int:
    for candidate in _DP_HDR_ALIASES.get(name, (name,)):
        if candidate in col_map:
            return col_map[candidate]
    if col_map:
        raise ValueError(
            f"diskprices: header row present but missing expected column '{name}'; "
            f"refusing positional fallback to avoid silent mis-mapping. "
            f"headers={sorted(col_map)}"
        )
    return _DP_COL_FALLBACK[name]


def _dp_parse_row(cells: list[Any], col_map: dict[str, int]) -> tuple[dict[str, Any], str] | None:
    if len(cells) < 9:
        return None

    def cell(i: int) -> str:
        return cells[i].get_text(strip=True) if 0 <= i < len(cells) else ""

    price_per_tb_i = _dp_col(_DP_HDR_PRICE_PER_TB, col_map)
    price_i = _dp_col(_DP_HDR_PRICE, col_map)
    cap_i = _dp_col(_DP_HDR_CAPACITY, col_map)
    warranty_i = _dp_col(_DP_HDR_WARRANTY, col_map)
    form_i = _dp_col(_DP_HDR_FORM, col_map)
    tech_i = _dp_col(_DP_HDR_TYPE, col_map)
    cond_i = _dp_col(_DP_HDR_CONDITION, col_map)

    link_i = col_map.get(_DP_HDR_LINK)
    link_cell = cells[link_i] if link_i is not None and 0 <= link_i < len(cells) else cells[-1]
    link_el = link_cell.find("a")
    cap_raw = cell(cap_i)
    tb, packs, total_tb = _dp_parse_capacity(cap_raw)

    fields = {
        "price_per_tb": SourceAdapter._num(cell(price_per_tb_i)),
        "price": SourceAdapter._num(cell(price_i)),
        "capacity_raw": cap_raw,
        "tb_per_drive": tb,
        "pack_count": packs,
        "total_tb": total_tb,
        "warranty": cell(warranty_i),
        "form_factor": cell(form_i),
        "technology": cell(tech_i),
        "condition": cell(cond_i),
        "title": link_el.get_text(strip=True) if link_el else link_cell.get_text(strip=True),
        "url": link_el.get("href") if link_el else None,
    }
    row_html = "".join(str(c) for c in cells)
    return fields, row_html


def _dp_parse_html(html: str) -> list[ParseRow]:
    soup = BeautifulSoup(html, "html.parser")
    table, col_map = _dp_find_listing_table(soup)
    rows: list[ParseRow] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 9:
            continue
        parsed = _dp_parse_row(cells, col_map)
        if parsed is None:
            continue
        fields, row_html = parsed
        rows.append((fields, row_html, "html"))
    return rows


@register_adapter
class DiskpricesAdapter(SourceAdapter):
    """Adapter for diskprices.com comparison tables.

    One RawCapture per table row. Columns are resolved by header name (with
    aliases for renamed headers); a header row whose names are unrecognized is
    refused via ``parse_error`` rather than silently positionally mapped.
    """

    source_name: ClassVar[str] = "diskprices"
    fixture_path: ClassVar[Path | None] = LEGACY_FIXTURE_ROOT / "diskprices" / "fixtures"

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        html = self._decode(raw_data)
        extra = self._merge_extra(metadata, source_url)

        try:
            rows = _dp_parse_html(html)
        except ValueError as exc:
            yield self._error_capture(
                error=str(exc),
                raw_payload=html,
                payload_format="html",
                source=self.source_name,
                source_listing_id=fallback_listing_id(html, prefix="disk-"),
                url=DP_URL,
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        if not rows:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=html,
                payload_format="html",
                source=self.source_name,
                source_listing_id=fallback_listing_id(html, prefix="disk-"),
                url=DP_URL,
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        for fields, raw, fmt in rows:
            key = "|".join(
                [
                    str(fields.get("url") or ""),
                    str(fields.get("title") or ""),
                    str(fields.get("capacity_raw") or ""),
                    str(fields.get("condition") or ""),
                ]
            )
            yield self._make_capture(
                source=self.source_name,
                source_listing_id=fallback_listing_id(key, prefix="disk-"),
                url=str(fields.get("url") or ""),
                raw_payload=raw,
                payload_format=fmt,
                fetched_at=fetched_at,
                metadata={**extra, **fields},
            )


# --- goharddrive ------------------------------------------------------------

GHD_BASE_URL = "https://www.goharddrive.com"
GHD_PRODUCT_PATH_RE = re.compile(r"-p/[a-z0-9-]+\.htm$", re.IGNORECASE)


def _ghd_sku_from_url(url: str) -> str | None:
    if not GHD_PRODUCT_PATH_RE.search(url):
        return None
    code = url.rsplit("/", 1)[-1]
    code = code[: -len(".htm")]
    return code.upper() or None



def _ghd_availability(soup: BeautifulSoup) -> str | None:
    meta = soup.find("meta", attrs={"itemprop": "availability"})
    if meta and meta.get("content") in {"InStock", "OutOfStock"}:
        return str(meta["content"])
    out_of_stock = soup.find(class_=re.compile(r"StockQuantity_OutOfStock"))
    if out_of_stock or "(Out of Stock)" in soup.get_text():
        return "OutOfStock"
    return None


def _ghd_is_sitemap(payload: str) -> bool:
    return "urlset" in payload or "<loc>" in payload or "<loc " in payload


def _ghd_sitemap_entries(payload: str) -> list[dict[str, Any]]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(payload, "html.parser")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for loc in soup.find_all("loc"):
        url = (loc.get_text() or "").strip()
        if not GHD_PRODUCT_PATH_RE.search(url):
            continue
        normalized = urljoin(GHD_BASE_URL + "/", url)
        if normalized in seen:
            continue
        seen.add(normalized)
        container = loc.parent
        lastmod = ""
        if container is not None:
            lastmod_node = container.find("lastmod")
            if lastmod_node is not None:
                lastmod = (lastmod_node.get_text() or "").strip()
        entries.append(
            {
                "url": normalized,
                "sku": _ghd_sku_from_url(normalized),
                "lastmod": lastmod or None,
                "raw": str(container) if container is not None else str(loc),
            }
        )
    return entries


def _ghd_parse_product_page(payload: str, *, url: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(payload, "html.parser")

    name_node = soup.find("span", attrs={"itemprop": "name"})
    title = name_node.get_text(" ", strip=True) if name_node else ""
    if not title:
        return None

    price_node = soup.find("span", attrs={"itemprop": "price"})
    price = SourceAdapter._num(str(price_node.get("content", "")) if price_node else None)

    manufacturer_node = soup.find("meta", attrs={"itemprop": "manufacturer"})
    manufacturer = (
        str(manufacturer_node["content"]).strip()
        if manufacturer_node and manufacturer_node.get("content")
        else None
    )

    condition_node = soup.find("meta", attrs={"itemprop": "itemCondition"})
    condition_raw = (
        str(condition_node["content"]).strip()
        if condition_node and condition_node.get("content")
        else None
    )

    return {
        "sku": _ghd_sku_from_url(url),
        "title": title,
        "price": price,
        "url": url,
        "availability": _ghd_availability(soup),
        "manufacturer": manufacturer,
        "condition_raw": condition_raw,
    }


@register_adapter
class GoHarddriveAdapter(SourceAdapter):
    """Adapter for goharddrive.com (Volusion) sitemaps and product pages.

    A sitemap yields one RawCapture per product URL (``record_kind`` =
    ``sitemap_entry``); a product page yields one capture for the page
    (``record_kind`` = ``product``). A page without a product name is flagged
    with ``parse_error`` instead of being skipped.
    """

    source_name: ClassVar[str] = "goharddrive"
    fixture_path: ClassVar[Path | None] = LEGACY_FIXTURE_ROOT / "goharddrive" / "fixtures"

    def _iter_fixture_files(self) -> Iterator[Path]:
        if self.fixture_path is None:
            return
        yield from super()._iter_fixture_files()
        if self.fixture_path.is_dir():
            yield from sorted(self.fixture_path.glob("products/*.html"))

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        html = self._decode(raw_data)
        extra = self._merge_extra(metadata, source_url)

        if _ghd_is_sitemap(html):
            entries = _ghd_sitemap_entries(html)
            if not entries:
                yield self._error_capture(
                    error="no_items_found",
                    raw_payload=html,
                    payload_format="xml",
                    source=self.source_name,
                    source_listing_id=fallback_listing_id(html, prefix="sitemap-"),
                    url=source_url or f"{GHD_BASE_URL}/sitemap.xml",
                    extra=extra,
                    fetched_at=fetched_at,
                )
                return
            for entry in entries:
                fields = {
                    "record_kind": "sitemap_entry",
                    "sku": entry["sku"],
                    "product_url": entry["url"],
                    "lastmod": entry["lastmod"],
                }
                yield self._make_capture(
                    source=self.source_name,
                    source_listing_id=str(entry["sku"] or ""),
                    url=entry["url"],
                    raw_payload=entry["raw"],
                    payload_format="xml",
                    fetched_at=fetched_at,
                    metadata={**extra, **fields},
                )
            return

        url = source_url or ""
        fields = _ghd_parse_product_page(html, url=url)
        if fields is None:
            yield self._error_capture(
                error="no_product_name",
                raw_payload=html,
                payload_format="html",
                source=self.source_name,
                source_listing_id=fallback_listing_id(html, prefix="product-"),
                url=url,
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        yield self._make_capture(
            source=self.source_name,
            source_listing_id=str(fields.get("sku") or ""),
            url=url or str(fields.get("url") or ""),
            raw_payload=html,
            payload_format="html",
            fetched_at=fetched_at,
            metadata={**extra, "record_kind": "product", **fields},
        )

    def load_fixtures(self, max_files: int | None = None) -> Iterator[RawCapture]:
        """Load fixtures, resolving each product page's URL via the sitemap.

        Fixture product files carry no live URL, so their product URL (and
        therefore SKU) comes from the sitemap entries — the same entrypoint the
        old crawl used. ``max_files`` caps the number of fixture files read.
        """
        self._require_fixture_path()

        url_by_sku: dict[str, str] = {}
        sitemap_file = self.fixture_path / "sitemap.xml"
        if sitemap_file.exists():
            for entry in _ghd_sitemap_entries(sitemap_file.read_text()):
                if entry["sku"]:
                    url_by_sku[entry["sku"]] = entry["url"]

        count = 0
        for fixture_file in sorted(self._iter_fixture_files()):
            if max_files is not None and count >= max_files:
                break
            fetched_at: datetime | None = None
            raw_data = ""
            try:
                mtime = fixture_file.stat().st_mtime
                fetched_at = datetime.fromtimestamp(mtime, tz=timezone.utc)
                raw_data = fixture_file.read_text()
                source_url = (
                    url_by_sku.get(fixture_file.stem.upper())
                    or f"fixture://{fixture_file.name}"
                )
                yield from self.parse_raw(
                    raw_data=raw_data,
                    source_url=source_url,
                    fetched_at=fetched_at,
                    metadata={"fixture_file": str(fixture_file)},
                )
            except Exception as exc:
                yield self._failure_capture(
                    raw_payload=raw_data,
                    error=f"{type(exc).__name__}: {exc}",
                    fixture_file=fixture_file,
                    fetched_at=fetched_at,
                )
            count += 1


# --- serversupply -----------------------------------------------------------

SS_BASE_URL = "https://www.serversupply.com"
SS_CONDITION_PREFIXES = ("New", "Refurbished", "OEM", "Spare")



def _ss_product_id_from_url(url: str) -> str:
    path = urlparse(url).path
    m = re.search(r"_(\d+)\.htm", path, flags=re.I)
    if m:
        return m.group(1)
    return path.strip("/").replace(" ", "_")


def _ss_split_condition_title(raw: str) -> tuple[str | None, str]:
    text = re.sub(r"\s+", " ", raw).strip()
    for prefix in SS_CONDITION_PREFIXES:
        needle = f"{prefix} |"
        if text.lower().startswith(needle.lower()):
            return prefix, text[len(needle) :].strip()
    return None, text


def _ss_model_from_title(title: str) -> str | None:
    tokens = re.findall(r"\b[A-Z]{1,4}\d{3,}[A-Z0-9.-]*\b", title)
    return tokens[0] if tokens else None


def _ss_parse_listing_page(html: str, *, category_path: str | None = None) -> list[ParseRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[ParseRow] = []
    for box in soup.select("div.productbox"):
        link = box.select_one(".ptitle a.pdes") or box.select_one(".ptitle a")
        if not link:
            continue
        href = link.get("href") or ""
        url = urljoin(SS_BASE_URL, href)
        title_raw = link.get_text(" ", strip=True)
        condition_raw, title = _ss_split_condition_title(title_raw)
        price_el = box.select_one(".pcost")
        current = None
        listed = None
        if price_el:
            was = price_el.select_one(".wpcost")
            if was:
                listed = SourceAdapter._num(was.get_text())
            full = price_el.get_text(" ", strip=True)
            current = SourceAdapter._num(full.replace(was.get_text(), "") if was else full)
        fields = {
            "product_id": _ss_product_id_from_url(url),
            "title": title,
            "price": current,
            "listed_price": listed,
            "url": url,
            "condition_raw": condition_raw,
            "category_path": category_path,
            "model_number": _ss_model_from_title(title),
            "availability": None,
        }
        rows.append((fields, str(box), "html"))
    return rows


@register_adapter
class ServerSupplyAdapter(SourceAdapter):
    """Adapter for serversupply.com listing pages.

    One RawCapture per ``div.productbox`` card. The ``New |``/``Refurbished |``
    title prefix is split into ``condition_raw`` and the product id comes from
    the ``_<id>.htm`` URL tail.
    """

    source_name: ClassVar[str] = "serversupply"
    fixture_path: ClassVar[Path | None] = LEGACY_FIXTURE_ROOT / "serversupply" / "fixtures"

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        html = self._decode(raw_data)
        extra = self._merge_extra(metadata, source_url)

        rows = _ss_parse_listing_page(html, category_path=extra.get("category_path"))
        if not rows:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=html,
                payload_format="html",
                source=self.source_name,
                source_listing_id=fallback_listing_id(html, prefix="product-"),
                url=SS_BASE_URL,
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        for fields, raw, fmt in rows:
            yield self._make_capture(
                source=self.source_name,
                source_listing_id=str(fields.get("product_id") or ""),
                url=str(fields.get("url") or ""),
                raw_payload=raw,
                payload_format=fmt,
                fetched_at=fetched_at,
                metadata={**extra, **fields},
            )


# --- serverorbit ------------------------------------------------------------

SO_BASE_URL = "https://serverorbit.com/"



def _so_labeled_field(item: Any, keywords: tuple[str, ...]) -> str | None:
    el = item.find(lambda tag: tag.name == "span" and any(k in tag.text for k in keywords))
    if el is not None:
        sibling = el.find_next_sibling("span")
        if sibling is not None:
            return sibling.get_text(strip=True)
    for feat in item.select(".ty-product-feature"):
        feat_text = feat.get_text()
        if any(k in feat_text for k in keywords):
            parts = feat_text.split(":")
            if len(parts) > 1:
                return parts[1].strip()
    return None


def _so_parse_html(html: str) -> list[ParseRow]:
    """Parse grid cards into rows.

    A card that cannot be parsed becomes a row whose fields carry
    ``parse_error`` (``missing_title``/``missing_price``) instead of being
    silently skipped.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[ParseRow] = []

    discount_notice = None
    disc_el = soup.select_one(".ty-discount-notice, .ty-discount-banner")
    if disc_el:
        discount_notice = disc_el.get_text(strip=True)

    items = soup.select(".ty-grid-list__item, .ut2-gl__body, .ty-column4, .product-cell")
    seen_ids: set[str] = set()

    for item in items:
        pid = item.get("id", "")
        if pid and pid in seen_ids:
            continue

        title_el = item.select_one(".product-title, .ty-grid-list__item-name a, a.product-title")
        if not title_el:
            rows.append(({"parse_error": "missing_title"}, str(item), "html"))
            continue
        title = title_el.get_text(strip=True)
        url = title_el.get("href")

        sku_el = item.select_one(".ty-sku .ty-control-group__item, [id^=sku_], .product-sku")
        sku = sku_el.get_text(strip=True) if sku_el else ""
        if not sku:
            sku_match = re.search(r"\(([\w\-/\.]{5,})\)", title)
            if sku_match:
                sku = sku_match.group(1)

        price_el = item.select_one(".ty-price-num, .ty-price, .price-num")
        price = SourceAdapter._num(price_el.get_text(strip=True) if price_el else None)
        if price is None:
            rows.append(({"parse_error": "missing_price"}, str(item), "html"))
            continue

        list_price_el = item.select_one(".ty-list-price, .strike-price")
        list_price_text = list_price_el.get_text(strip=True) if list_price_el else None
        listed_price = SourceAdapter._num(list_price_text)

        manufacturer = _so_labeled_field(item, ("Manufacturer", "Brand"))
        condition_raw = _so_labeled_field(item, ("Condition",))

        avail_el = item.select_one(".ty-qty-in-stock, .availability")
        availability = avail_el.get_text(" ", strip=True) if avail_el else "In Stock"

        if pid:
            seen_ids.add(pid)

        fields = {
            "sku": sku,
            "title": title,
            "price": price,
            "listed_price": listed_price,
            "manufacturer": manufacturer,
            "condition_raw": condition_raw,
            "availability": availability,
            "url": url,
            "product_id": pid,
            "category_path": None,
            "discount_text": discount_notice,
        }
        rows.append((fields, str(item), "html"))
    return rows


@register_adapter
class ServerorbitAdapter(SourceAdapter):
    """Adapter for serverorbit.com CS-Cart grid listings.

    One RawCapture per grid card. SKU falls back to the parenthesized MPN in
    the title; manufacturer/condition come from the labeled feature rows. A
    card with no title or no price is emitted as a ``parse_error`` capture
    instead of being dropped.
    """

    source_name: ClassVar[str] = "serverorbit"
    fixture_path: ClassVar[Path | None] = LEGACY_FIXTURE_ROOT / "serverorbit" / "fixtures"

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        html = self._decode(raw_data)
        extra = self._merge_extra(metadata, source_url)

        rows = _so_parse_html(html)
        if not rows:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=html,
                payload_format="html",
                source=self.source_name,
                source_listing_id=fallback_listing_id(html, prefix="item-"),
                url=SO_BASE_URL,
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        for fields, raw, fmt in rows:
            if "parse_error" in fields:
                yield self._error_capture(
                    error=str(fields["parse_error"]),
                    raw_payload=raw,
                    payload_format=fmt,
                    source=self.source_name,
                    extra=extra,
                    fetched_at=fetched_at,
                )
                continue
            listing_id = str(fields.get("sku") or fields.get("product_id") or "")
            if not listing_id:
                listing_id = fallback_listing_id(raw, prefix="item-")
            yield self._make_capture(
                source=self.source_name,
                source_listing_id=listing_id,
                url=str(fields.get("url") or ""),
                raw_payload=raw,
                payload_format=fmt,
                fetched_at=fetched_at,
                metadata={**extra, **fields},
            )


# --- disctech ---------------------------------------------------------------

DT_BASE_URL = "https://www.disctech.com"

DT_CONDITION_SUFFIXES = {
    "BN-OE": "Brand New OEM",
    "BN": "Brand New",
    "RF-OE": "Refurbished OEM",
    "RF": "Refurbished",
    "US-OE": "Used OEM",
    "US": "Used",
}



def _dt_category_path_from_url(url: str) -> str:
    path = url.replace(DT_BASE_URL, "").split("?")[0].strip("/")
    return path


def _dt_department_from_path(category_path: str | None) -> str:
    if not category_path:
        return "unknown"
    return category_path.split("/")[0]


def _dt_condition_from_sku(sku: str | None) -> str | None:
    if not sku:
        return None
    upper = sku.upper()
    for suffix, label in sorted(DT_CONDITION_SUFFIXES.items(), key=lambda x: -len(x[0])):
        if upper.endswith(f"-{suffix}") or upper.endswith(suffix):
            return label
    return None


def _dt_title_from_item(item: Any) -> str:
    title_el = item.select_one(".facets-item-cell-list-name, .facets-item-cell-title a")
    if title_el:
        title = (title_el.get("title") or title_el.get_text(" ", strip=True) or "").strip()
        if title:
            return title
    link = item.select_one("a[href]")
    if link:
        return (link.get("title") or link.get_text(" ", strip=True) or "").strip()
    return ""


def extract_categories_json(env_text: str) -> list[dict[str, Any]]:
    match = re.search(r"SC\.CATEGORIES\s*=\s*(\[.*?\]);", env_text, re.S)
    if not match:
        raise ValueError("SC.CATEGORIES not found in environment response")
    return json.loads(match.group(1))


def _dt_leaf_category_nodes(roots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    leaves: list[dict[str, Any]] = []

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            url = (node.get("fullurl") or "").strip()
            children = node.get("categories") or []
            if children:
                walk(children)
            elif url:
                leaves.append(node)

    walk(roots)
    return leaves


def _dt_parse_listing_page(html: str, *, category_path: str | None = None) -> list[ParseRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[ParseRow] = []
    for item in soup.select(".facets-item-cell-grid, .facets-item-cell-list"):
        item_id = (item.get("data-item-id") or "").strip()
        sku = (item.get("data-sku") or "").strip() or None
        title = _dt_title_from_item(item)
        link = item.select_one(".facets-item-cell-list-name, .facets-item-cell-title a, a[href]")
        href = link.get("href") if link else ""
        url = urljoin(DT_BASE_URL, href) if href else ""
        price_el = item.select_one(".product-views-price-lead")
        old_el = item.select_one(".product-views-price-old")
        current = SourceAdapter._num(price_el.get_text() if price_el else None)
        listed = SourceAdapter._num(old_el.get_text() if old_el else None)
        stock_el = item.select_one(".product-line-stock")
        stock_text = stock_el.get_text(" ", strip=True) if stock_el else ""
        availability = stock_text or None
        if not item_id and sku:
            item_id = sku
        if not item_id:
            continue
        path = category_path
        if not path:
            track = (item.get("data-track-productlist-category") or "").strip()
            path = track.strip("/") or None
        fields = {
            "item_id": item_id,
            "sku": sku,
            "title": title,
            "price": current,
            "listed_price": listed,
            "url": url,
            "category_path": path,
            "condition_raw": _dt_condition_from_sku(sku),
            "availability": availability,
        }
        rows.append((fields, str(item), "html"))
    return rows


@register_adapter
class DisctechAdapter(SourceAdapter):
    """Adapter for disctech.com listing pages and category environment payloads.

    Listing pages yield one RawCapture per ``.facets-item-cell-*`` card; the
    ``SC.CATEGORIES`` environment payload yields one capture per leaf category
    (``record_kind`` = ``category``). Condition is decoded from the SKU suffix
    (``-BN``, ``-RF-OE``, ...).
    """

    source_name: ClassVar[str] = "disctech"
    fixture_path: ClassVar[Path | None] = LEGACY_FIXTURE_ROOT / "disctech" / "fixtures"

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        html = self._decode(raw_data)
        extra = self._merge_extra(metadata, source_url)

        if "SC.CATEGORIES" in html:
            yield from self._parse_categories(html, fetched_at, extra)
            return

        rows = _dt_parse_listing_page(html, category_path=extra.get("category_path"))
        if not rows:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=html,
                payload_format="html",
                source=self.source_name,
                source_listing_id=fallback_listing_id(html, prefix="item-"),
                url=DT_BASE_URL,
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        for fields, raw, fmt in rows:
            listing_id = str(fields.get("item_id") or "")
            if not listing_id:
                listing_id = fallback_listing_id(raw, prefix="item-")
            yield self._make_capture(
                source=self.source_name,
                source_listing_id=listing_id,
                url=str(fields.get("url") or ""),
                raw_payload=raw,
                payload_format=fmt,
                fetched_at=fetched_at,
                metadata={**extra, "record_kind": "product", **fields},
            )

    def _parse_categories(
        self,
        html: str,
        fetched_at: datetime | None,
        extra: dict[str, Any],
    ) -> Iterator[RawCapture]:
        try:
            roots = extract_categories_json(html)
        except (ValueError, json.JSONDecodeError) as exc:
            yield self._error_capture(
                error=str(exc),
                raw_payload=html,
                payload_format="html",
                source=self.source_name,
                source_listing_id=fallback_listing_id(html, prefix="category-"),
                url=DT_BASE_URL,
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        leaves = _dt_leaf_category_nodes(roots)
        if not leaves:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=html,
                payload_format="html",
                source=self.source_name,
                source_listing_id=fallback_listing_id(html, prefix="category-"),
                url=DT_BASE_URL,
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        for node in leaves:
            node_url = (node.get("fullurl") or "").strip()
            name = (node.get("name") or "").strip()
            path = _dt_category_path_from_url(node_url)
            internal_id = str(node.get("internalid") or "").strip() or None
            fields = {
                "record_kind": "category",
                "category_internal_id": internal_id,
                "category_name": name,
                "category_url": node_url,
                "category_path": path,
                "department": _dt_department_from_path(path),
            }
            yield self._make_capture(
                source=self.source_name,
                source_listing_id=internal_id or path,
                url=urljoin(DT_BASE_URL, node_url) if node_url else DT_BASE_URL,
                raw_payload=json.dumps(node),
                payload_format="json",
                fetched_at=fetched_at,
                metadata={**extra, **fields},
            )
