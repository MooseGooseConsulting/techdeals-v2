"""Liquidation.com adapter.

Parses the site's HTML: listing cards from category/search pages, auction
detail pages, and manifest tables. One RawCapture is emitted per lot; the raw
payload is the lot's combined HTML (listing card + auction detail + manifest)
and metadata carries the merged fields.

Fixture corpora split one lot across three files, so ``load_fixtures``
concatenates them by lot id before parsing. A document with several distinct
auction ids (a listing page) yields one capture per card.

Field mapping follows ``TechdealsHandoff/scripts/ingest/liquidation_com/``:
``parse_listings.py`` (cards), ``parse_auction.py`` (detail), and
``parse_manifest.py`` (manifest table).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from techdeals.adapters.base import SourceAdapter, fallback_listing_id, register_adapter
from techdeals.ingestion.contract import RawCapture

LEGACY_FIXTURE_ROOT = Path(
    os.environ.get("LEGACY_FIXTURE_ROOT", "/home/coldaine/TechdealsHandoff/scripts/ingest")
)
BASE_ORIGIN = "https://www.liquidation.com"

AUCTION_LINK_RE = re.compile(r"auction/view\?id=(\d+)")
MANIFEST_LINK_RE = re.compile(r"/aucimg/.*/m(\d+)\.html")
MONEY_RE = re.compile(r"\$([\d,]+\.\d{2})")
META_LINE_RE = re.compile(
    r"^\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\d+)\s*items?\s*$", re.I
)
COUNTS_RE = re.compile(r"(\d+)\s*bids?.*?(\d+)\s*watchers?.*?(\d+)\s*views?", re.I | re.S)


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_money(text: str) -> float | None:
    match = MONEY_RE.search(text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _manifest_money(text: str) -> float:
    text = text.strip()
    if not text or text in ("-", "N/A", "n/a"):
        return 0.0
    match = re.search(r"([\d,]+\.\d{2})", text)
    if match:
        return float(match.group(1).replace(",", ""))
    match = re.search(r"([\d,]+)", text)
    if match:
        return float(match.group(1).replace(",", ""))
    return 0.0


def _manifest_int(text: str) -> int:
    match = re.search(r"(\d+)", text.replace(",", ""))
    return int(match.group(1)) if match else 0


def _label_value(text: str, labels: list[str]) -> str | None:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*:\s*(.+?)(?:\n|$)", text, re.I)
        if match:
            return _norm_space(match.group(1))
    return None


def _join_base(page_url: str) -> str:
    return page_url if page_url.startswith("http") else BASE_ORIGIN


def parse_cards(soup: BeautifulSoup, page_url: str) -> list[dict[str, Any]]:
    """Extract listing cards from a listing page (or a combined lot document)."""
    anchors_by_id: dict[str, list] = {}
    for anchor in soup.find_all("a", href=True):
        match = AUCTION_LINK_RE.search(anchor["href"])
        if match:
            anchors_by_id.setdefault(match.group(1), []).append(anchor)

    cards: list[dict[str, Any]] = []
    for auction_id, anchors in anchors_by_id.items():
        title_anchor = max(anchors, key=lambda a: len(a.get_text(strip=True)))
        detail_url = urljoin(_join_base(page_url), title_anchor["href"])
        title = _norm_space(title_anchor.get_text(" ", strip=True))

        container = soup.find(attrs={"data-id": auction_id})
        if container is None:
            container = title_anchor.find_parent(["div", "li", "article", "tr", "td"])
            for _ in range(8):
                if container is None:
                    break
                text = container.get_text(" ", strip=True)
                if "Current Bid" in text or "Est. Retail" in text or "CLOSED" in text:
                    break
                container = container.parent

        block_text = container.get_text("\n", strip=True) if container else ""
        block_html = str(container) if container else str(title_anchor)

        current_bid = est_retail = None
        bid_el = container.find(class_=re.compile(r"current-bid", re.I)) if container else None
        retail_el = container.find(class_=re.compile(r"est-retail", re.I)) if container else None
        if bid_el:
            current_bid = _parse_money(bid_el.get_text(" ", strip=True))
        if retail_el:
            est_retail = _parse_money(retail_el.get_text(" ", strip=True))

        for line in block_text.splitlines():
            if current_bid is None:
                match = re.search(r"Current Bid\s*:?\s*\$?([\d,]+\.\d{2})", line, re.I)
                if match:
                    current_bid = float(match.group(1).replace(",", ""))
            if est_retail is None:
                match = re.search(r"Est\.?\s*Retail\s*:?\s*\$?([\d,]+\.\d{2})", line, re.I)
                if match:
                    est_retail = float(match.group(1).replace(",", ""))

        status = None
        if re.search(r"\bCLOSED\b", block_text, re.I):
            status = "closed"
        else:
            close_match = re.search(r"Closing:\s*(.+?)(?:\n|$)", block_text, re.I)
            if close_match:
                status = f"closing: {_norm_space(close_match.group(1))}"

        seller = None
        if container:
            seller_link = container.find("a", href=re.compile(r"seller", re.I))
            if seller_link:
                seller = _norm_space(seller_link.get_text(" ", strip=True))

        location = condition = packages = None
        item_count = None
        for line in block_text.splitlines():
            meta_match = META_LINE_RE.match(line)
            if meta_match:
                location = _norm_space(meta_match.group(1))
                condition = _norm_space(meta_match.group(2))
                packages = _norm_space(meta_match.group(3))
                item_count = int(meta_match.group(4))
                break

        bids = watchers = views = None
        counts_match = COUNTS_RE.search(block_text)
        if counts_match:
            bids = int(counts_match.group(1))
            watchers = int(counts_match.group(2))
            views = int(counts_match.group(3))

        cards.append(
            {
                "auction_id": auction_id,
                "title": title or None,
                "detail_url": detail_url,
                "current_bid": current_bid,
                "est_retail": est_retail,
                "seller": seller,
                "status": status,
                "location": location,
                "condition": condition,
                "packages": packages,
                "item_count": item_count,
                "bids": bids,
                "watchers": watchers,
                "views": views,
                "block_html": block_html,
            }
        )
    return cards


def parse_detail(soup: BeautifulSoup, page_url: str) -> dict[str, Any]:
    """Parse auction detail fields (pricing, terms, manifest link) from a document."""
    text = soup.get_text("\n", strip=True)

    current_bid = minimum_bid = est_retail = None
    for label, key in (
        ("Current Bid", "current_bid"),
        ("Minimum Bid", "minimum_bid"),
        ("Est. Retail", "est_retail"),
        ("Estimated Retail", "est_retail"),
    ):
        match = re.search(rf"{label}\s*:?\s*\$?([\d,]+\.\d{{2}})", text, re.I)
        if match:
            value = float(match.group(1).replace(",", ""))
            if key == "current_bid":
                current_bid = value
            elif key == "minimum_bid":
                minimum_bid = value
            elif est_retail is None:
                est_retail = value

    if est_retail is None:
        retail_el = soup.find(class_=re.compile(r"est-retail|retail-value", re.I))
        if retail_el:
            est_retail = _parse_money(retail_el.get_text(" ", strip=True))

    heading = soup.find("h1")
    title = _norm_space(heading.get_text(" ", strip=True)) if heading else None

    seller = _label_value(text, ["Seller"])
    if not seller:
        seller_link = soup.find("a", href=re.compile(r"seller", re.I))
        if seller_link:
            seller = _norm_space(seller_link.get_text(" ", strip=True))

    quantity_in_lot = None
    qty_match = re.search(r"(\d+)\s*(?:items?|qty|quantity)\s*(?:in\s*lot)?", text, re.I)
    if qty_match:
        quantity_in_lot = int(qty_match.group(1))

    manifest_url = None
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        link_text = anchor.get_text(strip=True)
        if "/aucimg/" in href or "view manifest" in link_text.lower():
            manifest_url = urljoin(_join_base(page_url), href)
            break

    download_url = None
    for anchor in soup.find_all("a", href=True):
        link_text = anchor.get_text(strip=True).lower()
        if "download" in link_text and (
            "/aucimg/" in anchor["href"] or ".xls" in anchor["href"].lower()
        ):
            download_url = urljoin(_join_base(page_url), anchor["href"])
            break

    return {
        "title": title,
        "current_bid": current_bid,
        "minimum_bid": minimum_bid,
        "est_retail": est_retail,
        "close_time": _label_value(text, ["Closes", "Close Time", "Closing"]),
        "location": _label_value(text, ["Location", "Item Location"]),
        "seller": seller,
        "buyers_premium": _label_value(text, ["Buyer's Premium", "Buyers Premium"]),
        "shipping_terms": _label_value(text, ["Shipping Terms", "Shipping"]),
        "quantity_in_lot": quantity_in_lot,
        "auction_type": _label_value(text, ["Auction Type", "Type"]),
        "manifest_url": manifest_url,
        "download_url": download_url,
    }


def parse_manifest(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Parse a manifest HTML table into items plus totals, or None if absent."""
    table = None
    for candidate in soup.find_all("table"):
        header_text = candidate.get_text(" ", strip=True).lower()
        if "description" in header_text and "retail" in header_text:
            table = candidate
            break
    if table is None:
        return None

    rows = table.find_all("tr")
    if not rows:
        return None

    header_cells = [
        cell.get_text(" ", strip=True).lower() for cell in rows[0].find_all(["th", "td"])
    ]
    items: list[dict[str, Any]] = []
    for row in rows[1:]:
        values = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if len(values) < 2:
            continue
        row_data = {
            header_cells[i]: values[i] for i in range(min(len(header_cells), len(values)))
        }
        if header_cells:
            description = row_data.get("description", values[0])
            quantity = _manifest_int(
                row_data.get("quantity", values[1] if len(values) > 1 else "0")
            )
            retail_price = _manifest_money(
                row_data.get("retail price", values[2] if len(values) > 2 else "0")
            )
            ext_retail = _manifest_money(
                row_data.get("ext retail price", values[3] if len(values) > 3 else "0")
            )
            make = row_data.get("make", values[4] if len(values) > 4 else "")
            model = row_data.get("model", values[5] if len(values) > 5 else "")
            category = row_data.get("product category", values[6] if len(values) > 6 else "")
        else:
            description = values[0]
            quantity = _manifest_int(values[1])
            retail_price = _manifest_money(values[2]) if len(values) > 2 else 0.0
            ext_retail = _manifest_money(values[3]) if len(values) > 3 else 0.0
            make = values[4] if len(values) > 4 else ""
            model = values[5] if len(values) > 5 else ""
            category = values[6] if len(values) > 6 else ""
        if not description:
            continue
        items.append(
            {
                "description": description,
                "quantity": quantity,
                "retail_price": retail_price,
                "ext_retail_price": ext_retail,
                "make": make,
                "model": model,
                "product_category": category,
            }
        )

    return {
        "items": items,
        "total_quantity": sum(item["quantity"] for item in items),
        "total_ext_retail": sum(item["ext_retail_price"] for item in items),
    }


def _lot_ids(soup: BeautifulSoup) -> list[str]:
    ids: list[str] = []
    for element in soup.find_all(attrs={"data-id": True}):
        value = str(element.get("data-id") or "").strip()
        if value and value not in ids:
            ids.append(value)
    for anchor in soup.find_all("a", href=True):
        match = AUCTION_LINK_RE.search(anchor["href"]) or MANIFEST_LINK_RE.search(anchor["href"])
        if match and match.group(1) not in ids:
            ids.append(match.group(1))
    return ids


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _merged_fields(
    lot_id: str | None,
    card: dict[str, Any] | None,
    detail: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    card = card or {}
    detail = detail or {}
    return {
        "lot_id": lot_id,
        "title": _first_not_none(detail.get("title"), card.get("title")),
        "current_bid": _first_not_none(detail.get("current_bid"), card.get("current_bid")),
        "minimum_bid": detail.get("minimum_bid"),
        "est_retail": _first_not_none(detail.get("est_retail"), card.get("est_retail")),
        "close_time": detail.get("close_time"),
        "status": card.get("status"),
        "seller": detail.get("seller") or card.get("seller"),
        "location": detail.get("location") or card.get("location"),
        "condition": card.get("condition"),
        "packages": card.get("packages"),
        "item_count": card.get("item_count"),
        "quantity_in_lot": detail.get("quantity_in_lot"),
        "bids": card.get("bids"),
        "watchers": card.get("watchers"),
        "views": card.get("views"),
        "buyers_premium": detail.get("buyers_premium"),
        "shipping_terms": detail.get("shipping_terms"),
        "auction_type": detail.get("auction_type"),
        "manifest_url": detail.get("manifest_url"),
        "download_url": detail.get("download_url"),
        "manifest": manifest,
    }


@register_adapter
class LiquidationComAdapter(SourceAdapter):
    """Adapter for Liquidation.com HTML (listing card + detail + manifest).

    One RawCapture per lot. The raw payload is the lot's combined HTML and
    metadata carries merged card, detail, and manifest fields.
    """

    source_name: ClassVar[str] = "liquidation_com"
    fixture_path: ClassVar[Path | None] = LEGACY_FIXTURE_ROOT / "liquidation_com" / "fixtures"

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        html = raw_data.decode("utf-8") if isinstance(raw_data, bytes) else raw_data
        extra = dict(metadata or {})
        if source_url:
            extra.setdefault("source_url", source_url)
        soup = BeautifulSoup(html, "html.parser")
        cards = parse_cards(soup, source_url)
        detail = parse_detail(soup, source_url)
        manifest = parse_manifest(soup)

        card_ids = [card["auction_id"] for card in cards]
        content_ids = _lot_ids(soup)
        if len(card_ids) > 1:
            for card in cards:
                lot_id = card["auction_id"]
                url = card["detail_url"] or f"{BASE_ORIGIN}/auction/view?id={lot_id}"
                fields = _merged_fields(lot_id, card, None, None)
                yield self._make_capture(
                    source=self.source_name,
                    source_listing_id=lot_id,
                    url=url,
                    raw_payload=card["block_html"],
                    payload_format="html",
                    fetched_at=fetched_at,
                    metadata={**extra, **fields},
                )
            return

        lot_id = (
            extra.get("lot_id")
            or (card_ids[0] if card_ids else None)
            or (content_ids[0] if content_ids else None)
        )
        detail_found = any(value is not None for value in detail.values())
        if not cards and not detail_found and manifest is None:
            listing_id = str(lot_id) if lot_id else fallback_listing_id(html, prefix="lot-")
            yield self._make_capture(
                source=self.source_name,
                source_listing_id=listing_id,
                url="",
                raw_payload=html,
                payload_format="html",
                fetched_at=fetched_at,
                metadata={**extra, "parse_error": "no_lot_found"},
            )
            return

        if lot_id is None:
            lot_id = fallback_listing_id(html, prefix="lot-")

        card = cards[0] if cards else None
        url = (card or {}).get("detail_url") or f"{BASE_ORIGIN}/auction/view?id={lot_id}"
        fields = _merged_fields(lot_id, card, detail, manifest)
        yield self._make_capture(
            source=self.source_name,
            source_listing_id=str(lot_id),
            url=url,
            raw_payload=html,
            payload_format="html",
            fetched_at=fetched_at,
            metadata={**extra, **fields},
        )

    def load_fixtures(self, max_count: int | None = None) -> Iterator[RawCapture]:
        """Load fixtures, concatenating each lot's card, detail, and manifest files."""
        if self.fixture_path is None:
            raise FileNotFoundError(f"No fixture path configured for {self.source_name}")
        if not self.fixture_path.exists():
            raise FileNotFoundError(f"Fixture directory not found: {self.fixture_path}")

        groups: dict[str, list[Path]] = {}
        for fixture_file in sorted(self._iter_fixture_files()):
            parts = fixture_file.stem.rsplit("_", 1)
            lot_id = parts[1] if len(parts) == 2 else fixture_file.stem
            groups.setdefault(lot_id, []).append(fixture_file)

        count = 0
        for lot_id, files in groups.items():
            if max_count is not None and count >= max_count:
                break
            ordered = sorted(files, key=_fixture_rank)
            chunks: list[str] = []
            fetched_at: datetime | None = None
            try:
                for fixture_file in ordered:
                    mtime = fixture_file.stat().st_mtime
                    stamp = datetime.fromtimestamp(mtime, tz=timezone.utc)
                    fetched_at = stamp if fetched_at is None or stamp > fetched_at else fetched_at
                    chunks.append(f"<!-- {fixture_file.name} -->\n{fixture_file.read_text()}")
            except Exception as exc:
                yield self._failure_capture(
                    raw_payload="\n".join(chunks),
                    error=f"{type(exc).__name__}: {exc}",
                    fixture_file=ordered[0] if ordered else None,
                )
                continue

            yield from self.parse_raw(
                raw_data="\n\n".join(chunks),
                source_url=f"fixture://{ordered[0].name}" if ordered else "",
                fetched_at=fetched_at,
                metadata={
                    "lot_id": lot_id,
                    "fixture_file": str(ordered[0]) if ordered else "",
                    "fixture_files": [str(f) for f in ordered],
                },
            )
            count += 1


def _fixture_rank(fixture_file: Path) -> int:
    name = fixture_file.name.lower()
    if "listing" in name or "card" in name:
        return 0
    if "detail" in name or "auction" in name:
        return 1
    if "manifest" in name:
        return 2
    return 3
