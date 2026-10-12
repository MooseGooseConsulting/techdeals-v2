"""RSS and CSV/JSON adapters for the remaining TechDeals corpus sources.

Ports the transport-layer parsing of the old handoff repo's ingest scripts
into RawCapture-producing adapters:

- ``slickdeals`` (``scripts/ingest/slickdeals/parse.py``) — RSS 2.0 feed of
  mini-PC deal threads. Every RSS item becomes a capture; items failing the
  mini-PC keyword filter are flagged (``metadata["is_mini_pc"] = False``)
  and quarantined rather than dropped.
- ``google_shopping`` (``scripts/ingest/google_shopping/parse.py``) — CSV
  import with two schemas (``legacy_url_export`` and ``reduced_manual``).
- ``spl_psu_tier_list`` (``scripts/ingest/spl_psu_tier_list/parse.py``) —
  multi-sheet CSV of PSU tier judgments. This is JUDGMENT data, never a
  posting: every capture carries ``metadata["data_type"] = "judgment"`` and
  ``metadata["quarantine_reason"] = "reference_data_not_posting"`` and is
  emitted with ``IngestionStatus.quarantined``.
- ``ssd_pricing_run1`` (``scripts/ingest/ssd_pricing_run1/parse.py``) — flat
  CSV of curated price observations (Run-1 export; Run-2 stays out of scope).
- ``atlas_gen5_ssd`` (``scripts/ingest/atlas_gen5_ssd/parse.py``) — Gen 5 SSD
  atlas JSON snapshot; one capture per product record.

Nothing is silently dropped: rows/items the adapter cannot parse become
captures whose metadata carries ``parse_error`` (see ``SourceAdapter``).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, ClassVar, Iterator, Mapping

from techdeals.adapters.base import (
    LEGACY_FIXTURE_ROOT,
    SourceAdapter,
    fallback_listing_id,
    register_adapter,
)
from techdeals.ingestion.contract import IngestionStatus, RawCapture

LEGACY_RESEARCH_ROOT = Path("/home/coldaine/TechdealsHandoff/research")

# In-repo sample fixtures (shipped with the pipeline) used when the legacy
# corpus directory for a source does not exist on disk.
REPO_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures"


# --------------------------------------------------------------------------
# slickdeals: RSS 2.0 mini-PC deal feed
# --------------------------------------------------------------------------

SLICKDEALS_MINIPC_RSS_URL = (
    "https://slickdeals.net/newsearch.php?q=mini+pc&searcharea=deals&searchin=first&firstonly=1&rss=1"
)

_POSITIVE_KEYWORDS = (
    r"\bmini[ -]?pc\b",
    r"\bmini[ -]?computer\b",
    r"\bsmall desktop\b",
    r"\bnucbox\b",
    r"\bminisforum\b",
    r"\bacemagic\b",
    r"\bacemagician\b",
    r"\bbeelink\b",
    r"\bgmktec\b",
    r"\bkamrui\b",
    r"\baoostar\b",
    r"\bfirebat\b",
    r"\bnipogi\b",
    r"\bintel nuc\b",
)

_FALSE_POSITIVE_PATTERNS = (
    r"\bearbuds?\b",
    r"\bearphones?\b",
    r"\bheadphones?\b",
    r"\bmouse\b",
    r"\bkeyboard\b",
    r"\bcontroller\b",
    r"\bsteam\b",
    r"\bdigital game\b",
    r"\bpc game\b",
    r"\bscrewdriver\b",
    r"\btool kit\b",
    r"\bflashlight\b",
    r"\bmini[- ]?itx case\b",
    r"\bpc case\b",
    r"\bchassis\b",
)

_SD_PRICE_RE = re.compile(r"\$([0-9,]+(?:\.[0-9]{2})?)")
_SD_MERCHANT_RE = re.compile(r"@\s*([A-Za-z0-9\.\s]+)$")


def is_mini_pc_deal(title: str, description: str = "") -> bool:
    text = f"{title} {description}".lower()
    for pattern in _FALSE_POSITIVE_PATTERNS:
        if re.search(pattern, text, re.I):
            return False
    for pattern in _POSITIVE_KEYWORDS:
        if re.search(pattern, text, re.I):
            return True
    return False


def extract_price(text: str) -> float | None:
    if not text:
        return None
    match = _SD_PRICE_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def extract_thread_id(guid: str, link: str) -> str:
    if "thread:" in guid:
        return guid.split("thread:")[-1].strip()
    match = re.search(r"/f/(\d+)", link) or re.search(r"[?&]t=(\d+)", link)
    if match:
        return match.group(1)
    return hashlib.md5((guid or link).encode("utf-8")).hexdigest()[:12]


def extract_merchant(title: str) -> str | None:
    match = _SD_MERCHANT_RE.search(title)
    if match:
        return match.group(1).strip()
    return None


@register_adapter
class SlickdealsAdapter(SourceAdapter):
    """Adapter for the slickdeals mini-PC RSS feed.

    One RawCapture per RSS ``<item>``. The mini-PC keyword filter from the
    old parser decides ``metadata["is_mini_pc"]``; items that fail it are
    quarantined (``quarantine_reason="not_mini_pc_deal"``) instead of being
    dropped. Repeated thread IDs within one payload are parsed once.
    """

    source_name: ClassVar[str] = "slickdeals"
    fixture_path: ClassVar[Path | None] = LEGACY_FIXTURE_ROOT / "slickdeals" / "fixtures"

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        payload = self._decode(raw_data)
        extra = self._merge_extra(metadata, source_url)

        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            yield self._error_capture(
                error=f"invalid_rss_xml: {exc}",
                raw_payload=payload,
                payload_format="xml",
                source=self.source_name,
                source_listing_id="",
                url="",
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        channel = root.find("channel")
        if channel is None:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=payload,
                payload_format="xml",
                source=self.source_name,
                source_listing_id="",
                url="",
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        seen_threads: set[str] = set()
        yielded = 0
        for item in channel.findall("item"):
            item_xml = ET.tostring(item, encoding="unicode")
            title = _child_text(item, "title")
            if not title:
                yielded += 1
                yield self._error_capture(
                    error="missing_title",
                    raw_payload=item_xml,
                    payload_format="xml",
                    source=self.source_name,
                    source_listing_id="",
                    url="",
                    extra=extra,
                    fetched_at=fetched_at,
                )
                continue

            link = _child_text(item, "link") or ""
            guid = _child_text(item, "guid") or link
            description = _child_text(item, "description") or ""
            thread_id = extract_thread_id(guid, link)
            if thread_id in seen_threads:
                continue
            seen_threads.add(thread_id)

            valid = is_mini_pc_deal(title, description)
            meta: dict[str, Any] = {
                **extra,
                "title": title,
                "price": extract_price(title) or extract_price(description),
                "merchant": extract_merchant(title),
                "pub_date": _child_text(item, "pubDate"),
                "description": description or None,
                "guid": guid,
                "thread_id": thread_id,
                "is_mini_pc": valid,
            }
            if not valid:
                meta["quarantine_reason"] = "not_mini_pc_deal"

            capture = self._make_capture(
                source=self.source_name,
                source_listing_id=f"sd:thread:{thread_id}",
                url=link,
                raw_payload=item_xml,
                payload_format="xml",
                fetched_at=fetched_at,
                metadata=meta,
            )
            if not valid:
                capture.status = IngestionStatus.quarantined
            yielded += 1
            yield capture

        if not yielded:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=payload,
                payload_format="xml",
                source=self.source_name,
                source_listing_id="",
                url="",
                extra=extra,
                fetched_at=fetched_at,
            )


def _child_text(node: ET.Element, tag: str) -> str | None:
    child = node.find(tag)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


# --------------------------------------------------------------------------
# google_shopping: CSV import (two schemas)
# --------------------------------------------------------------------------

GS_LEGACY_SCHEMA = "legacy_url_export"
GS_REDUCED_SCHEMA = "reduced_manual"

GS_LEGACY_COLUMNS = {
    "product_name": "Product Name",
    "price": "Price",
    "merchant": "Merchant",
    "condition_notes": "Condition/Notes",
    "url": "Product URL",
}

GS_REDUCED_COLUMNS = {
    "product_name": "Product",
    "price": "Price",
    "merchant": "Store",
    "condition_notes": "Condition",
    "url": "Product URL",
}


def _gs_clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _gs_detect_schema(fieldnames: list[str]) -> tuple[dict[str, str], str]:
    names = set(fieldnames)
    legacy_required = {
        GS_LEGACY_COLUMNS["product_name"],
        GS_LEGACY_COLUMNS["price"],
        GS_LEGACY_COLUMNS["merchant"],
        GS_LEGACY_COLUMNS["condition_notes"],
    }
    reduced_required = {
        GS_REDUCED_COLUMNS["product_name"],
        GS_REDUCED_COLUMNS["price"],
        GS_REDUCED_COLUMNS["merchant"],
        GS_REDUCED_COLUMNS["condition_notes"],
    }
    if legacy_required.issubset(names):
        return GS_LEGACY_COLUMNS, GS_LEGACY_SCHEMA
    if reduced_required.issubset(names):
        return GS_REDUCED_COLUMNS, GS_REDUCED_SCHEMA
    expected = sorted(legacy_required | reduced_required | {"Product URL"})
    raise ValueError(
        "Unsupported Google Shopping columns: expected headers drawn from " f"{', '.join(expected)}"
    )


def _gs_extract_capacity(product_name: str, notes: str | None) -> tuple[str | None, float | None]:
    for text in (product_name, notes or ""):
        match = re.search(r"\b(\d+(?:\.\d+)?)\s*TB\b", text, flags=re.I)
        if match:
            tb = float(match.group(1))
            raw_value = match.group(1)
            raw = f"{raw_value.rstrip('0').rstrip('.') if '.' in raw_value else raw_value}TB"
            return raw, tb
    return None, None


def _gs_extract_form_factor(product_name: str, notes: str | None) -> str | None:
    blob = f"{product_name} {notes or ''}"
    if re.search(r"\b3\.5(?:[\s-]*inch|[\s-]*in|\")?\b", blob, flags=re.I):
        return "3.5-inch"
    if re.search(r"\b2\.5(?:[\s-]*inch|[\s-]*in|\")?\b", blob, flags=re.I):
        return "2.5-inch"
    if re.search(r"\bm\.2\b", blob, flags=re.I):
        return "M.2"
    if re.search(r"\bu\.2\b", blob, flags=re.I):
        return "U.2"
    return None


def _gs_extract_interface(product_name: str, notes: str | None) -> str | None:
    blob = f"{product_name} {notes or ''}"
    if re.search(r"\bnvme\b", blob, flags=re.I):
        return "NVMe"
    if re.search(r"\bSAS[-\s]*12\s*Gb/?s\b", blob, flags=re.I):
        return "SAS 12Gb/s"
    if re.search(r"\bSATA(?:\s*III)?(?:[-\s]*6(?:\.0)?\s*Gb/?s)?\b", blob, flags=re.I):
        return "SATA 6Gb/s" if re.search(r"6(?:\.0)?\s*Gb/?s", blob, flags=re.I) else "SATA"
    return None


def _gs_extract_technology(product_name: str, notes: str | None) -> str | None:
    blob = f"{product_name} {notes or ''}".lower()
    if re.search(r"\b(ssd|solid.state|nvme)\b", blob):
        return "SSD"
    if re.search(r"\b(hdd|hard\s*drive|ironwolf|skyhawk|purple|ultrastar|sata|sas)\b", blob):
        return "HDD"
    return None


def _gs_extract_brand(product_name: str) -> str | None:
    title = product_name.strip()
    lowered = title.lower()
    brand_aliases = [
        ("western digital", "Western Digital"),
        ("wd ", "Western Digital"),
        ("wd-", "Western Digital"),
        ("seagate", "Seagate"),
        ("toshiba", "Toshiba"),
        ("samsung", "Samsung"),
        ("solidigm", "Solidigm"),
        ("intel", "Intel"),
        ("micron", "Micron"),
        ("sk hynix", "SK hynix"),
        ("kioxia", "Kioxia"),
        ("invid", "InVid"),
        ("vivotek", "Vivotek"),
    ]
    for prefix, brand in brand_aliases:
        if lowered.startswith(prefix):
            return brand
    first = title.split(maxsplit=1)[0] if title else None
    return first.strip(" -|") if first else None


def _gs_extract_model(product_name: str) -> str | None:
    patterns = [
        r"\b(WD[A-Z0-9-]{2,})\b",
        r"\b(ST\d+[A-Z0-9-]*)\b",
        r"\b(HU[HS]\d+[A-Z0-9-]*)\b",
        r"\b(MG\d+[A-Z0-9-]*)\b",
        r"\b(PM\d+[A-Z0-9-]*)\b",
        r"\b(SN\d+[A-Z0-9-]*)\b",
        r"\b(MZ[0-9A-Z-]{4,})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, product_name, flags=re.I)
        if match:
            return match.group(1).upper()
    return None


def _gs_normalize_condition_class(notes: str | None) -> str | None:
    text = (notes or "").strip().lower()
    if not text:
        return "unspecified"
    if any(token in text for token in ("refurb", "renew", "recert", "reman")):
        return "refurbished"
    if "open box" in text or "open-box" in text:
        return "open_box"
    if any(token in text for token in ("used", "pre-owned", "preowned")):
        return "used"
    if any(token in text for token in ("new", "brand new", "sealed")):
        return "new"
    return "unspecified"


@register_adapter
class GoogleShoppingAdapter(SourceAdapter):
    """Adapter for Google Shopping CSV exports.

    Handles both the legacy URL export schema (``Product Name``...) and the
    reduced manual schema (``Product``/``Store``/``Condition``). One capture
    per data row; an unsupported header set or a header-only file becomes a
    flagged capture instead of an exception.
    """

    source_name: ClassVar[str] = "google_shopping"
    # The legacy corpus ships no google_shopping fixtures (its data is manually
    # maintained CSV exports), so fixture_path prefers the legacy fixtures
    # directory when one exists and falls back to the in-repo sample fixtures
    # so the source always has testable data.
    fixture_path: ClassVar[Path | None] = (
        LEGACY_FIXTURE_ROOT / "google_shopping" / "fixtures"
        if (LEGACY_FIXTURE_ROOT / "google_shopping" / "fixtures").is_dir()
        else REPO_FIXTURE_ROOT / "google_shopping"
    )

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        payload = self._decode(raw_data)
        extra = self._merge_extra(metadata, source_url)
        when = fetched_at or datetime.now(timezone.utc)
        observed_date = str(extra.get("observed_date") or when.date().isoformat())

        reader = csv.DictReader(io.StringIO(payload.lstrip("\ufeff")))
        if reader.fieldnames is None:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=payload,
                payload_format="json",
                source=self.source_name,
                source_listing_id="",
                url="",
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        try:
            columns, schema_mode = _gs_detect_schema(reader.fieldnames)
        except ValueError as exc:
            yield self._error_capture(
                error=str(exc),
                raw_payload=payload,
                payload_format="json",
                source=self.source_name,
                source_listing_id="",
                url="",
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        yielded = 0
        for row_index, row in enumerate(reader, start=1):
            cleaned = {key: _gs_clean(value) or "" for key, value in row.items() if key is not None}
            product_name = cleaned.get(columns["product_name"], "")
            merchant = cleaned.get(columns["merchant"], "")
            url = _gs_clean(cleaned.get(columns["url"])) if columns["url"] in cleaned else None
            if not (product_name or merchant or url):
                continue

            notes = _gs_clean(cleaned.get(columns["condition_notes"]))
            capacity_raw, tb_per_drive = _gs_extract_capacity(product_name, notes)
            raw_payload = json.dumps(cleaned, sort_keys=True)
            listing_id = fallback_listing_id(
                url or raw_payload, prefix="gs-url-" if url else "gs-row-"
            )
            capture = self._make_capture(
                source=self.source_name,
                source_listing_id=listing_id,
                url=url or "",
                raw_payload=raw_payload,
                payload_format="json",
                fetched_at=fetched_at,
                metadata={
                    **extra,
                    "schema_mode": schema_mode,
                    "source_row_number": row_index,
                    "observed_date": observed_date,
                    "product_name": product_name,
                    "title": product_name,
                    "price": SourceAdapter._num(cleaned.get(columns["price"])),
                    "merchant": merchant,
                    "condition_notes": notes,
                    "condition_class": _gs_normalize_condition_class(notes),
                    "missing_url": not bool(url),
                    "brand_name": _gs_extract_brand(product_name),
                    "model_name": _gs_extract_model(product_name),
                    "capacity_raw": capacity_raw,
                    "tb_per_drive": tb_per_drive,
                    "form_factor": _gs_extract_form_factor(product_name, notes),
                    "interface_raw": _gs_extract_interface(product_name, notes),
                    "technology": _gs_extract_technology(product_name, notes),
                },
            )
            yielded += 1
            yield capture

        if not yielded:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=payload,
                payload_format="json",
                source=self.source_name,
                source_listing_id="",
                url="",
                extra=extra,
                fetched_at=fetched_at,
            )


# --------------------------------------------------------------------------
# spl_psu_tier_list: multi-sheet CSV of PSU tier judgments (reference data)
# --------------------------------------------------------------------------

SPL_SHEET_PREFIX = "========== SHEET: "
SPL_SHEET_SUFFIX = " =========="
SPL_MAIN_SHEET = "Main List (Proper Ratings Only)"
SPL_FULL_SHEET = "Full List (With Limited Confidence Ratings)"


def _spl_normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _spl_split_sheets(
    rows: list[list[str]],
) -> "OrderedDict[str, list[tuple[int, list[str]]]]":
    """Split the all-sheets export into named sheets with 1-based CSV row numbers."""
    sections: "OrderedDict[str, list[tuple[int, list[str]]]]" = OrderedDict()
    current_name: str | None = None
    for row_number, row in enumerate(rows, start=1):
        if len(row) == 1 and row[0].startswith(SPL_SHEET_PREFIX) and row[0].endswith(
            SPL_SHEET_SUFFIX
        ):
            current_name = row[0][len(SPL_SHEET_PREFIX) : -len(SPL_SHEET_SUFFIX)]
            sections[current_name] = []
            continue
        if current_name is not None:
            sections[current_name].append((row_number, row))
    return sections


def _spl_parse_tier(value: str) -> tuple[str, str]:
    value = value.strip()
    match = re.fullmatch(r"([A-F])([+\-*]*)", value)
    if not match:
        return value, ""
    return match.group(1), match.group(2)


def _spl_parse_intro_year(value: str) -> int | None:
    match = re.search(r"(20\d{2}|19\d{2})", value.strip())
    return int(match.group(1)) if match else None


def _spl_parse_wattages(value: str) -> tuple[list[int], int | None, int | None]:
    numbers = [int(n) for n in re.findall(r"\d{3,4}", value)]
    if not numbers:
        return [], None, None
    return numbers, min(numbers), max(numbers)


def _spl_pad(row: list[str], width: int) -> list[str]:
    return row + [""] * max(0, width - len(row))


def _spl_stable_key(sheet_name: str, values: list[str]) -> str:
    payload = "\x1f".join([sheet_name, *[_spl_normalize_text(v).casefold() for v in values]])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _spl_apply_identity_state(
    row: list[str],
    brand: str,
    series: str,
    sub_series_1: str,
    sub_series_2: str,
) -> tuple[str, str, str, str]:
    if row[0].strip():
        brand = row[0].strip()
        series = ""
        sub_series_1 = ""
        sub_series_2 = ""
    if row[1].strip():
        series = row[1].strip()
        sub_series_1 = ""
        sub_series_2 = ""
    if row[2].strip():
        sub_series_1 = row[2].strip()
        sub_series_2 = ""
    if row[3].strip():
        sub_series_2 = row[3].strip()
    return brand, series, sub_series_1, sub_series_2


def _spl_parse_visible_rows(
    sheet_name: str,
    rows: list[tuple[int, list[str]]],
    has_row_id: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Port of the old ``parse_visible_rows`` with global CSV row numbers."""
    expected_width = 19 if has_row_id else 18
    records: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    brand = ""
    series = ""
    sub_series_1 = ""
    sub_series_2 = ""

    for source_row_number, raw in rows:
        if not any(cell.strip() for cell in raw):
            continue

        if not has_row_id and len(raw) == 4:
            brand, series, sub_series_1, sub_series_2 = _spl_apply_identity_state(
                raw, brand, series, sub_series_1, sub_series_2
            )
            continue

        if not has_row_id and len(raw) == 15:
            raw = ["", "", "", *raw]

        if len(raw) != expected_width:
            quarantine.append(
                {
                    "source_sheet": sheet_name,
                    "source_row_number": source_row_number,
                    "reason": f"unexpected_width:{len(raw)}",
                    "raw": raw,
                }
            )
            continue

        row = _spl_pad(raw, expected_width)
        brand, series, sub_series_1, sub_series_2 = _spl_apply_identity_state(
            row, brand, series, sub_series_1, sub_series_2
        )

        wattages_raw = row[4].strip()
        tier_raw = row[5].strip()
        if not wattages_raw and not tier_raw and not row[17].strip():
            quarantine.append(
                {
                    "source_sheet": sheet_name,
                    "source_row_number": source_row_number,
                    "reason": "no_wattage_tier_or_notes",
                    "raw": raw,
                }
            )
            continue

        wattage_values, watt_min, watt_max = _spl_parse_wattages(wattages_raw)
        tier, tier_mod = _spl_parse_tier(tier_raw)
        row_id = row[18].strip() if has_row_id else ""
        stable_key = row_id or _spl_stable_key(sheet_name, row[:18])
        title = _spl_normalize_text(
            " ".join(
                part
                for part in (brand, series, sub_series_1, sub_series_2)
                if part.strip()
            )
        )
        records.append(
            {
                "source_sheet": sheet_name,
                "source_row_number": source_row_number,
                "brand": brand,
                "brand_clean": _spl_normalize_text(brand),
                "series": series,
                "series_clean": _spl_normalize_text(series),
                "sub_series_1": sub_series_1,
                "sub_series_1_clean": _spl_normalize_text(sub_series_1),
                "sub_series_2": sub_series_2,
                "sub_series_2_clean": _spl_normalize_text(sub_series_2),
                "title": title or None,
                "wattages_raw": wattages_raw,
                "wattage_values": wattage_values,
                "watt_min": watt_min,
                "watt_max": watt_max,
                "tier_raw": tier_raw,
                "tier": tier,
                "tier_mod": tier_mod,
                "intro_year_raw": row[6].strip(),
                "intro_year": _spl_parse_intro_year(row[6]),
                "size": row[7].strip(),
                "atx_version_raw": row[8].strip(),
                "input_range_raw": row[9].strip(),
                "modularity_raw": row[10].strip(),
                "efficiency_raw": row[11].strip(),
                "topology_primary_conversion": row[12].strip(),
                "topology_secondary_rectifier": row[13].strip(),
                "topology_secondary_regulation": row[14].strip(),
                "odm": row[15].strip(),
                "platform_code": row[16].strip(),
                "notes": row[17].strip(),
                "row_id": row_id,
                "stable_key": stable_key,
                "needs_manual_id": has_row_id and not bool(row_id),
            }
        )

    return records, quarantine


@register_adapter
class SplPsuTierListAdapter(SourceAdapter):
    """Adapter for the SPL PSU tier list all-sheets CSV.

    The tier rows are JUDGMENT data, never a market posting: each record is
    emitted as a capture with ``metadata["data_type"] = "judgment"`` and
    ``metadata["quarantine_reason"] = "reference_data_not_posting"`` and
    status ``quarantined``. Only the two record-bearing sheets (the proper
    ratings list and the limited-confidence full list) are parsed, matching
    the old ``run.py``; prose/bookkeeping sheets hold no records.
    """

    source_name: ClassVar[str] = "spl_psu_tier_list"
    fixture_path: ClassVar[Path | None] = (
        LEGACY_RESEARCH_ROOT
        / "reference_data"
        / "spl_psu_tier_list"
        / "SPL_PSU_Tier_List_All_Sheets.csv"
    )

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        payload = self._decode(raw_data)
        extra = self._merge_extra(metadata, source_url)

        rows = list(csv.reader(io.StringIO(payload.lstrip("\ufeff"))))
        sheets = _spl_split_sheets(rows)
        if not sheets:
            yield self._error_capture(
                error="no_sheets_found",
                raw_payload=payload,
                payload_format="json",
                source=self.source_name,
                source_listing_id="",
                url="",
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        targets = (
            (SPL_MAIN_SHEET, True),
            (SPL_FULL_SHEET, False),
        )
        yielded = 0
        for sheet_name, has_row_id in targets:
            sheet_rows = sheets.get(sheet_name)
            if not sheet_rows:
                continue
            records, quarantine = _spl_parse_visible_rows(sheet_name, sheet_rows, has_row_id)
            for record in records:
                raw_payload = json.dumps(record, sort_keys=True)
                capture = self._make_capture(
                    source=self.source_name,
                    source_listing_id=str(record["stable_key"]),
                    url="",
                    raw_payload=raw_payload,
                    payload_format="json",
                    fetched_at=fetched_at,
                    metadata={
                        **extra,
                        "data_type": "judgment",
                        "quarantine_reason": "reference_data_not_posting",
                        **record,
                        "price": None,
                    },
                )
                capture.status = IngestionStatus.quarantined
                yielded += 1
                yield capture
            for bad in quarantine:
                yielded += 1
                yield self._error_capture(
                    error=bad["reason"],
                    raw_payload=json.dumps(bad, sort_keys=True),
                    payload_format="json",
                    source=self.source_name,
                    extra={
                        **extra,
                        "data_type": "judgment",
                        "source_sheet": bad["source_sheet"],
                        "source_row_number": bad["source_row_number"],
                    },
                    fetched_at=fetched_at,
                )

        if not yielded:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=payload,
                payload_format="json",
                source=self.source_name,
                source_listing_id="",
                url="",
                extra=extra,
                fetched_at=fetched_at,
            )


# --------------------------------------------------------------------------
# ssd_pricing_run1: flat CSV of curated price observations
# --------------------------------------------------------------------------

SSD_REQUIRED_COLUMNS = frozenset(
    {
        "brand",
        "model_name",
        "capacity_gb",
        "retailer",
        "price_usd",
        "source_type",
        "source_name",
        "scraped_at",
        "source_url",
    }
)


def _ssd_int(value: str | None, field: str, row_number: int) -> int:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"row {row_number}: {field} is required, got {value!r}")
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"row {row_number}: {field} is not an integer: {text!r}") from None


def _ssd_int_or_none(value: str | None, field: str, row_number: int) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"row {row_number}: {field} is not an integer: {text!r}") from None


def _ssd_decimal(value: str | None, field: str, row_number: int) -> Decimal:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"row {row_number}: {field} is required, got {value!r}")
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValueError(f"row {row_number}: {field} is not numeric: {text!r}") from None


def _ssd_decimal_or_none(value: str | None, field: str, row_number: int) -> Decimal | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValueError(f"row {row_number}: {field} is not numeric: {text!r}") from None


def _ssd_optional(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _ssd_parse_row(row: Mapping[str, str | None], row_number: int) -> dict[str, Any]:
    """Port of the old ``_parse_row``; raises ValueError on a bad row."""
    brand = (row.get("brand") or "").strip()
    model = (row.get("model_name") or "").strip()
    if not brand or not model:
        raise ValueError(f"row {row_number}: brand and model_name are required")
    capacity = _ssd_int(row.get("capacity_gb"), "capacity_gb", row_number)
    if capacity <= 0:
        raise ValueError(f"row {row_number}: capacity_gb must be positive, got {capacity}")
    price = _ssd_decimal(row.get("price_usd"), "price_usd", row_number)
    if price <= 0:
        raise ValueError(f"row {row_number}: price_usd must be positive, got {price}")

    scraped_at_raw = (row.get("scraped_at") or "").strip()
    try:
        scraped_at = datetime.fromisoformat(scraped_at_raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(
            f"row {row_number}: scraped_at is not ISO-8601: {scraped_at_raw!r}"
        ) from None
    if scraped_at.tzinfo is None:
        scraped_at = scraped_at.replace(tzinfo=timezone.utc)

    in_stock_raw = (row.get("in_stock") or "").strip().lower()
    if in_stock_raw not in {"0", "1"}:
        raise ValueError(f"row {row_number}: in_stock must be 0 or 1, got {in_stock_raw!r}")

    has_dram_raw = (row.get("has_dram") or "").strip().lower()
    has_dram: bool | None
    if not has_dram_raw:
        has_dram = None
    elif has_dram_raw in {"1", "true", "yes"}:
        has_dram = True
    elif has_dram_raw in {"0", "false", "no"}:
        has_dram = False
    else:
        raise ValueError(
            f"row {row_number}: has_dram must be a boolean flag, got {has_dram_raw!r}"
        )

    original_price = _ssd_decimal_or_none(
        row.get("original_price_usd"), "original_price_usd", row_number
    )
    discount_pct = _ssd_decimal_or_none(row.get("discount_pct"), "discount_pct", row_number)
    return {
        "row_number": row_number,
        "brand": brand,
        "model_name": model,
        "title": model,
        "capacity_gb": capacity,
        "interface": _ssd_optional(row.get("interface")),
        "form_factor": _ssd_optional(row.get("form_factor")),
        "nand_type": _ssd_optional(row.get("nand_type")),
        "seq_read_mbps": _ssd_int_or_none(row.get("seq_read_mbps"), "seq_read_mbps", row_number),
        "seq_write_mbps": _ssd_int_or_none(row.get("seq_write_mbps"), "seq_write_mbps", row_number),
        "has_dram": has_dram,
        "retailer": (row.get("retailer") or "").strip(),
        "price_usd": float(price),
        "price": float(price),
        "original_price_usd": float(original_price) if original_price is not None else None,
        "discount_pct": float(discount_pct) if discount_pct is not None else None,
        "coupon_code": _ssd_optional(row.get("coupon_code")),
        "condition": _ssd_optional(row.get("condition")),
        "in_stock": in_stock_raw == "1",
        "source_type": (row.get("source_type") or "").strip(),
        "source_name": (row.get("source_name") or "").strip(),
        "scraped_at": scraped_at.isoformat(),
        "retailer_url": _ssd_optional(row.get("retailer_url")),
        "source_url": (row.get("source_url") or "").strip(),
    }


@register_adapter
class SsdPricingRun1Adapter(SourceAdapter):
    """Adapter for the SSD pricing research corpus Run-1 flat CSV.

    One capture per curated price observation row. Rows the strict Run-1
    parser rejects become flagged captures (parsing continues); a missing
    required column set flags the whole payload. Run-2 (``*_v2.csv``) is
    deliberately not part of this corpus.
    """

    source_name: ClassVar[str] = "ssd_pricing_run1"
    fixture_path: ClassVar[Path | None] = (
        LEGACY_RESEARCH_ROOT / "ssd-pricing-brightdata" / "ssd_prices_export.csv"
    )

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        payload = self._decode(raw_data)
        extra = self._merge_extra(metadata, source_url)

        reader = csv.DictReader(io.StringIO(payload.lstrip("\ufeff")))
        header = set(reader.fieldnames or ())
        missing = sorted(SSD_REQUIRED_COLUMNS - header)
        if missing:
            yield self._error_capture(
                error=f"missing_required_columns: {', '.join(missing)}",
                raw_payload=payload,
                payload_format="json",
                source=self.source_name,
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        yielded = 0
        for row_number, row in enumerate(reader, start=2):
            raw_payload = json.dumps(dict(row), sort_keys=True)
            try:
                observation = _ssd_parse_row(row, row_number=row_number)
            except ValueError as exc:
                yielded += 1
                yield self._error_capture(
                    error=str(exc),
                    raw_payload=raw_payload,
                    payload_format="json",
                    source=self.source_name,
                    source_listing_id="",
                    url="",
                    extra=extra,
                    fetched_at=fetched_at,
                )
                continue
            listing_id = fallback_listing_id(
                observation["source_url"] or raw_payload,
                prefix="ssd-url-" if observation["source_url"] else "ssd-row-",
            )
            yielded += 1
            yield self._make_capture(
                source=self.source_name,
                source_listing_id=listing_id,
                url=observation["source_url"],
                raw_payload=raw_payload,
                payload_format="json",
                fetched_at=fetched_at,
                metadata={**extra, **observation},
            )

        if not yielded:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=payload,
                payload_format="json",
                source=self.source_name,
                source_listing_id="",
                url="",
                extra=extra,
                fetched_at=fetched_at,
            )


# --------------------------------------------------------------------------
# atlas_gen5_ssd: Gen 5 SSD atlas JSON snapshot
# --------------------------------------------------------------------------




def _atlas_client_quotes(entry: Mapping[str, Any], product_id: str) -> list[dict[str, Any]]:
    quotes: list[dict[str, Any]] = []
    for capacity_key, price in (entry.get("prices") or {}).items():
        if not isinstance(price, dict):
            continue
        amount = SourceAdapter._num(price.get("amount"))
        capacity_tb = SourceAdapter._num(capacity_key)
        if amount is None or capacity_tb is None:
            continue
        quotes.append(
            {
                "product_id": product_id,
                "capacity_key": str(capacity_key),
                "capacity_tb": capacity_tb,
                "amount": amount,
                "retailer": price.get("retailer"),
                "seller": price.get("seller"),
                "seller_class": price.get("sellerClass"),
                "status": price.get("status"),
                "observed": price.get("observed"),
                "confidence": price.get("confidence"),
                "active": bool(price.get("active")),
                "source": price.get("source"),
                "note": price.get("note"),
            }
        )
    return quotes


def _atlas_product_fields(entry: Mapping[str, Any]) -> dict[str, Any]:
    product_id = str(entry.get("id") or "")
    quotes = _atlas_client_quotes(entry, product_id)
    active_amounts = [q["amount"] for q in quotes if q["active"]]
    all_amounts = [q["amount"] for q in quotes]
    price = (
        min(active_amounts)
        if active_amounts
        else (min(all_amounts) if all_amounts else None)
    )
    return {
        "product_id": product_id,
        "product_class": str(entry.get("class") or ""),
        "brand": entry.get("brand"),
        "name": entry.get("name"),
        "title": entry.get("name") or product_id or None,
        "price": price,
        "aliases": entry.get("aliases"),
        "capacities": [
            c for c in (entry.get("capacities") or []) if SourceAdapter._num(c) is not None
        ],
        "form_factors": list(entry.get("formFactors") or []),
        "connector": entry.get("connector"),
        "interface": entry.get("interface"),
        "controller": entry.get("controller"),
        "nand": entry.get("nand"),
        "dram": entry.get("dram"),
        "read_mbps": SourceAdapter._num(entry.get("read")),
        "write_mbps": SourceAdapter._num(entry.get("write")),
        "random_read_iops": SourceAdapter._num(entry.get("randomRead")),
        "random_write_iops": SourceAdapter._num(entry.get("randomWrite")),
        "mixed_70_30_iops": SourceAdapter._num(entry.get("mixed7030")),
        "tbw_by_capacity": dict(entry.get("tbw") or {}),
        "dwpd": SourceAdapter._num(entry.get("dwpd")),
        "warranty_raw": entry.get("warranty"),
        "plp": entry.get("plp"),
        "hot_swap": entry.get("hotSwap"),
        "dual_port": entry.get("dualPort"),
        "end_to_end_protection": entry.get("e2e"),
        "telemetry": entry.get("telemetry"),
        "nvme_mi": entry.get("nvmeMi"),
        "ocp": entry.get("ocp"),
        "active_power_w": SourceAdapter._num(entry.get("activePowerW")),
        "idle_power_w": SourceAdapter._num(entry.get("idlePowerW")),
        "workload": entry.get("workload"),
        "client_quotes": quotes,
    }


@register_adapter
class AtlasGen5SsdAdapter(SourceAdapter):
    """Adapter for the Gen 5 SSD atlas JSON snapshot.

    One capture per product record; the raw payload preserves the complete
    product entry (including modeled enterprise procurement bands) and the
    metadata carries the observed per-capacity client price quotes.
    """

    source_name: ClassVar[str] = "atlas_gen5_ssd"
    fixture_path: ClassVar[Path | None] = LEGACY_FIXTURE_ROOT / "atlas_gen5_ssd" / "fixtures"

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        payload = self._decode(raw_data)
        extra = self._merge_extra(metadata, source_url)

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            yield self._error_capture(
                error=f"invalid_json: {exc}",
                raw_payload=payload,
                payload_format="json",
                source=self.source_name,
                source_listing_id="",
                url="",
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        products = data.get("products") if isinstance(data, dict) else None
        if not isinstance(products, list) or not products:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=payload,
                payload_format="json",
                source=self.source_name,
                source_listing_id="",
                url="",
                extra=extra,
                fetched_at=fetched_at,
            )
            return

        snapshot_date = str((data.get("metadata") or {}).get("snapshot_date") or "")
        yielded = 0
        for entry in products:
            if not isinstance(entry, dict) or not entry.get("id"):
                raw_text = entry if isinstance(entry, str) else json.dumps(entry)
                yielded += 1
                yield self._error_capture(
                    error="invalid_item",
                    raw_payload=raw_text,
                    payload_format="json",
                    source=self.source_name,
                    source_listing_id="",
                    url="",
                    extra=extra,
                    fetched_at=fetched_at,
                )
                continue
            fields = _atlas_product_fields(entry)
            yielded += 1
            yield self._make_capture(
                source=self.source_name,
                source_listing_id=fields["product_id"],
                url="",
                raw_payload=json.dumps(entry, sort_keys=True),
                payload_format="json",
                fetched_at=fetched_at,
                metadata={**extra, "snapshot_date": snapshot_date, **fields},
            )

        if not yielded:
            yield self._error_capture(
                error="no_items_found",
                raw_payload=payload,
                payload_format="json",
                source=self.source_name,
                source_listing_id="",
                url="",
                extra=extra,
                fetched_at=fetched_at,
            )
