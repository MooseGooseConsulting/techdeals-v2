"""GovDeals maestro JSON adapter.

Parses the public maestro JSON the GovDeals lot page calls: an ``asset``
document plus its ``bidbox`` tape document. One RawCapture is emitted per
asset; when a bidbox is present its raw dict rides along in
``metadata["bidbox"]`` and normalized tape fields land beside the claim
fields.

Fixture corpora keep asset and bidbox in separate files, so ``load_fixtures``
pairs them by lot before parsing. A bidbox that arrives without its asset is
still captured (tape-only, ``metadata["bidbox_only"]``) — nothing is dropped.

Field mapping follows ``TechdealsHandoff/scripts/ingest/govdeals/parse.py``:
native lot id is ``{accountId}-{assetId}`` and lot URLs are
``https://www.govdeals.com/en/asset/{assetId}/{accountId}``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Iterator

from bs4 import BeautifulSoup

from techdeals.adapters.base import SourceAdapter, register_adapter
from techdeals.ingestion.contract import RawCapture

LEGACY_FIXTURE_ROOT = Path(
    os.environ.get("LEGACY_FIXTURE_ROOT", "/home/coldaine/TechdealsHandoff/scripts/ingest")
)

LOT_URL = "https://www.govdeals.com/en/asset/{asset_id}/{account_id}"

_STATUS = {
    "STA": "open",
    "RFA": "open",
    "ACT": "open",
    "OPN": "open",
    "RFR": "seller_approval_pending",
    "HFR": "seller_approval_pending",
    "PEN": "seller_approval_pending",
    "WTH": "withdrawn",
    "WDR": "withdrawn",
    "CLO": "closed",
    "CLS": "closed",
    "SLD": "closed",
    "SOL": "closed",
    "EXP": "closed",
}

_ASSET_DOC_KEYS = (
    "assetShortDesc",
    "assetShortDescription",
    "assetLongDesc",
    "assetAttributeGroups",
    "assetPhotos",
    "companyName",
    "catDesc",
    "removalInstructions",
    "assetConditionCd",
)
_BIDBOX_DOC_KEYS = (
    "currentBid",
    "bidCount",
    "watcherCount",
    "premiumPercent",
    "assetAuctionEndDateUTC",
    "assetAuctionEndDateUtc",
    "hasReservePrice",
    "isReserveNotMet",
)
_FIXTURE_KIND_PREFIXES = ("asset", "bidbox")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _html_text(value: Any) -> str | None:
    text = _text(value)
    if text is None or "<" not in text:
        return text
    return BeautifulSoup(text, "html.parser").get_text("\n", strip=True) or None


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _currency_code(*payloads: dict[str, Any]) -> str | None:
    for payload in payloads:
        raw = payload.get("currencyCode") or payload.get("currency")
        if raw:
            return str(raw).strip().upper()
    return None


def _usd_bid(raw: Any, *currency_payloads: dict[str, Any]) -> float | None:
    currency = _currency_code(*currency_payloads)
    if currency is not None and currency != "USD":
        return None
    return _float(raw)


def _parse_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _listing_status(code: Any, closes_at: datetime | None) -> str:
    mapped = _STATUS.get(str(code or "").upper())
    if mapped and mapped != "open":
        return mapped
    if closes_at is not None and closes_at < datetime.now(timezone.utc):
        return "closed"
    return mapped or "open"


def _reserve_met(payload: dict[str, Any]) -> bool | None:
    if payload.get("hasReservePrice") is False:
        return None
    if "isReserveNotMet" not in payload and "hasReservePrice" not in payload:
        return None
    if payload.get("isReserveNotMet") is True:
        return False
    if payload.get("isReserveNotMet") is False:
        return True
    return None


def _photo_urls(photos: Any) -> list[str]:
    if not photos:
        return []
    urls: list[str] = []
    for item in photos:
        if isinstance(item, str):
            raw = item
        elif isinstance(item, dict):
            raw = item.get("url") or item.get("photo") or ""
        else:
            continue
        raw = str(raw).strip()
        if not raw:
            continue
        if raw.startswith("/"):
            raw = "https://www.govdeals.com" + raw
        urls.append(raw)
    return urls


def _condition_text(asset: dict[str, Any]) -> str | None:
    for group in asset.get("assetAttributeGroups") or []:
        for attr in group.get("assetAttributes") or []:
            if str(attr.get("label") or "").lower() == "condition":
                return _text(attr.get("value"))
    code = asset.get("assetConditionCd")
    if code == "SD":
        return "See description"
    return _text(code)


def _location_line(city: Any, state: Any, postal: Any) -> str | None:
    parts = (str(city).strip() if city else "", str(state).strip() if state else "")
    place = ", ".join(part for part in parts if part)
    if postal:
        place = f"{place} {postal}".strip()
    return place or None


def _ship_mode(asset: dict[str, Any]) -> str | None:
    will_ship = asset.get("willShip")
    if will_ship is False:
        return "pickup"
    if will_ship is True:
        if asset.get("uship"):
            return "platform_arranges"
        return "buyer_arranges"
    return None


def _premium_pct(box: dict[str, Any], asset: dict[str, Any]) -> float | None:
    return _float(box.get("premiumPercent")) or _float(asset.get("premiumPercent"))


def _split_doc(doc: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return ``(asset, bidbox)`` for one maestro document."""
    asset = doc.get("asset") if isinstance(doc.get("asset"), dict) else None
    bidbox = doc.get("bidbox") if isinstance(doc.get("bidbox"), dict) else None
    if asset is not None or bidbox is not None:
        return asset, bidbox
    if any(key in doc for key in _ASSET_DOC_KEYS):
        return doc, None
    if any(key in doc for key in _BIDBOX_DOC_KEYS):
        return None, doc
    return doc, None


def _lot_id_parts(asset: dict[str, Any] | None, box: dict[str, Any] | None) -> tuple[Any, Any]:
    src = asset or {}
    tape = box or {}
    account_id = src.get("accountId") if src.get("accountId") is not None else tape.get("accountId")
    asset_id = src.get("assetId") if src.get("assetId") is not None else tape.get("assetId")
    return account_id, asset_id


def _fixture_lot_key(data: dict[str, Any], fixture_file: Path) -> str:
    account_id, asset_id = _lot_id_parts(*_split_doc(data))
    if account_id is not None and asset_id is not None:
        return f"{account_id}-{asset_id}"
    stem = fixture_file.stem
    for prefix in _FIXTURE_KIND_PREFIXES:
        if stem.startswith(prefix + "_"):
            return stem[len(prefix) + 1 :]
    return stem


@register_adapter
class GovDealsAdapter(SourceAdapter):
    """Adapter for GovDeals maestro JSON (asset + bidbox).

    One RawCapture per asset. ``metadata["bidbox"]`` carries the raw bidbox
    document when one was fetched, alongside normalized claim and tape fields.
    """

    source_name: ClassVar[str] = "govdeals"
    fixture_path: ClassVar[Path | None] = LEGACY_FIXTURE_ROOT / "govdeals" / "fixtures"

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

        if isinstance(data, dict) and isinstance(data.get("assetSearchResults"), list):
            data = data["assetSearchResults"]
        if isinstance(data, list):
            if not data:
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
            for item in data:
                if not isinstance(item, dict):
                    raw_text = item if isinstance(item, str) else json.dumps(item)
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
                asset, bidbox = _split_doc(item)
                yield self._capture(asset, bidbox, json.dumps(item), fetched_at, extra)
            return

        if not isinstance(data, dict):
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

        asset, bidbox = _split_doc(data)
        yield self._capture(asset, bidbox, payload, fetched_at, extra)

    def _capture(
        self,
        asset: dict[str, Any] | None,
        bidbox: dict[str, Any] | None,
        raw_payload: str,
        fetched_at: datetime | None,
        extra: dict[str, Any],
    ) -> RawCapture:
        src = asset or {}
        box = bidbox or {}
        account_id, asset_id = _lot_id_parts(asset, bidbox)
        if account_id is None or asset_id is None:
            return self._make_capture(
                source=self.source_name,
                source_listing_id="",
                url="",
                raw_payload=raw_payload,
                payload_format="json",
                fetched_at=fetched_at,
                metadata={**extra, "parse_error": "missing_ids"},
            )

        listing_id = f"{account_id}-{asset_id}"
        url = LOT_URL.format(asset_id=asset_id, account_id=account_id)
        closes = _parse_time(
            box.get("assetAuctionEndDateUTC")
            or box.get("assetAuctionEndDateUtc")
            or src.get("assetAuctionEndDate")
        )
        status = _listing_status(box.get("assetStatusCd") or src.get("assetStatusCd"), closes)
        reserve = _reserve_met(box if box else src)
        bid_source = box if box else src

        fields: dict[str, Any] = {
            "native_lot_id": listing_id,
            "asset_id": _int(asset_id),
            "account_id": _int(account_id),
            "auction_id": _int(src.get("auctionId") or box.get("auctionId")),
            "status": status,
            "closes_at": closes.isoformat() if closes is not None else None,
            "current_bid": _usd_bid(bid_source.get("currentBid"), box, src),
            "bid_count": _int(bid_source.get("bidCount")),
            "watcher_count": _int(bid_source.get("watcherCount")),
            "buyers_premium_pct": _premium_pct(box, src),
            "reserve_met": reserve,
            "bidbox": box or None,
        }

        if asset is None:
            fields["bidbox_only"] = True
        else:
            city = src.get("city") or src.get("locationCity")
            state = src.get("state") or src.get("locationState")
            postal = src.get("zipCode") or src.get("locationZip")
            fields.update(
                {
                    "title": _text(src.get("assetShortDesc") or src.get("assetShortDescription")),
                    "description_html": _text(src.get("assetLongDesc")),
                    "seller_name": _text(src.get("companyName")),
                    "seller_type_id": _int(src.get("sellerTypeId")),
                    "location": _location_line(city, state, postal),
                    "city": _text(city),
                    "state": _text(state),
                    "zip": _text(postal),
                    "category": _text(src.get("catDesc") or src.get("categoryDescription")),
                    "currency": _currency_code(src),
                    "ship_mode": _ship_mode(src),
                    "ship_notes": _html_text(src.get("removalInstructions")),
                    "condition": _condition_text(src),
                    "photo_urls": _photo_urls(src.get("assetPhotos")),
                }
            )

        return self._make_capture(
            source=self.source_name,
            source_listing_id=listing_id,
            url=url,
            raw_payload=raw_payload,
            payload_format="json",
            fetched_at=fetched_at,
            metadata={**extra, **fields},
        )

    def load_fixtures(self, max_count: int | None = None) -> Iterator[RawCapture]:
        """Load fixtures, pairing ``asset_*.json`` with ``bidbox_*.json`` by lot."""
        if self.fixture_path is None:
            raise FileNotFoundError(f"No fixture path configured for {self.source_name}")
        if not self.fixture_path.exists():
            raise FileNotFoundError(f"Fixture directory not found: {self.fixture_path}")

        groups: dict[str, dict[str, Any]] = {}
        for fixture_file in sorted(self._iter_fixture_files()):
            raw_data = ""
            fetched_at: datetime | None = None
            try:
                mtime = fixture_file.stat().st_mtime
                fetched_at = datetime.fromtimestamp(mtime, tz=timezone.utc)
                raw_data = fixture_file.read_text()
                data = json.loads(raw_data)
                if not isinstance(data, dict):
                    raise ValueError(f"expected a JSON object, got {type(data).__name__}")
            except Exception as exc:
                yield self._failure_capture(
                    raw_payload=raw_data,
                    error=f"{type(exc).__name__}: {exc}",
                    fixture_file=fixture_file,
                    fetched_at=fetched_at,
                )
                continue

            asset, bidbox = _split_doc(data)
            key = _fixture_lot_key(data, fixture_file)
            group = groups.setdefault(key, {"asset": None, "bidbox": None, "files": [], "at": []})
            if asset is not None:
                group["asset"] = asset
            if bidbox is not None:
                group["bidbox"] = bidbox
            group["files"].append(fixture_file)
            if fetched_at is not None:
                group["at"].append(fetched_at)

        count = 0
        for group in groups.values():
            if max_count is not None and count >= max_count:
                break
            combined = {
                key: value
                for key, value in (("asset", group["asset"]), ("bidbox", group["bidbox"]))
                if value is not None
            }
            files: list[Path] = group["files"]
            fetched_at = max(group["at"]) if group["at"] else None
            yield from self.parse_raw(
                raw_data=json.dumps(combined),
                source_url=f"fixture://{files[0].name}" if files else "",
                fetched_at=fetched_at,
                metadata={
                    "fixture_file": str(files[0]) if files else "",
                    "fixture_files": [str(f) for f in files],
                },
            )
            count += 1
