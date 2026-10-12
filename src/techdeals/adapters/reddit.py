"""Reddit Atom feed adapters for r/homelabsales and r/hardwareswap.

Transport-layer parsing only: each Atom ``<entry>`` becomes one RawCapture
whose raw_payload is the serialized entry and whose metadata carries the
extracted fields (title, author, content HTML, updated timestamp). The title
grammar is ported from the old scraper
(``TechdealsHandoff/scripts/ingest/reddit_homelabsales/parse.py``) so
downstream stages can quarantine want-to-buy posts; item/price extraction
stays in the extraction engine.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import ClassVar, Iterator

from techdeals.adapters.base import LEGACY_FIXTURE_ROOT, SourceAdapter, register_adapter
from techdeals.ingestion.contract import IngestionStatus, RawCapture

ATOM_NS = "http://www.w3.org/2005/Atom"

_SALE_TAGS = {"FS", "WTS"}
_WANT_TAGS = {"WTB", "W"}
_FREE_TAGS = {"FREE"}
_LISTING_TYPE_RE = re.compile(r"\[(FS|WTS|WTB|W|PC|FREE)\]", re.I)
_LOCATION_RE = re.compile(r"\[((?:US|USA)(?:-[A-Z0-9]+)+|CAN|CA|EU|UK|AU)\]", re.I)
_PRICE_RE = re.compile(r"\$\s*(?P<price>[\d,]+(?:\.\d{1,2})?)")

_HWS_SIDES_RE = re.compile(r"\[H\]\s*(?P<have>.*?)(?:\[W\]\s*(?P<want>.*))?$", re.I | re.S)
_PAYMENT_WORD_RE = re.compile(r"\b(?:paypal|venmo|zelle|cash\s*app|cashapp|cash|g&s|f&f)\b", re.I)
_PAYMENT_FILLER_RE = re.compile(
    r"\b(?:only|preferred|local|or|and|plus|via|goods|services)\b", re.I
)
_HWS_BARE_AMOUNT_RE = re.compile(r"\b\d+(?:\.\d{1,2})?\b")
_HWS_ITEM_SPLIT_RE = re.compile(r"(?:\s*\+\s*|\s+&\s+|\s+\band\b\s+|\s*[,;/|]\s*)", re.I)
_HWS_NON_ITEM_PART_RE = re.compile(
    r"(?i)^(?:ship(?:ping|s)?|fees?|insurance|tax(?:es)?|paypal|venmo|zelle|cash\s*app|cashapp|cash"
    r"|g&s|f&f|obo|each|ea\.?|per\s+unit"
    r"|free\s+shipping|plus\s+(?:insurance|shipping|fees?)|local\s+(?:cash|pickup|only))$"
)


def _find(parent: ET.Element | None, tag: str) -> ET.Element | None:
    if parent is None:
        return None
    node = parent.find(f"{{{ATOM_NS}}}{tag}")
    return node if node is not None else parent.find(tag)


def _findall(parent: ET.Element, tag: str) -> list[ET.Element]:
    nodes = parent.findall(f"{{{ATOM_NS}}}{tag}")
    return nodes if nodes else parent.findall(tag)


def _child_text(entry: ET.Element, tag: str) -> str | None:
    node = _find(entry, tag)
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    return text or None


def _entry_link(entry: ET.Element) -> str:
    href = ""
    for link_node in _findall(entry, "link"):
        node_href = (link_node.attrib.get("href") or "").strip()
        rel = (link_node.attrib.get("rel") or "alternate").strip().lower()
        if node_href and rel in {"alternate", ""}:
            return node_href
        if node_href and not href:
            href = node_href
    return href


def _entry_content_html(entry: ET.Element) -> str:
    content = _find(entry, "content")
    if content is None:
        return ""
    return "".join(content.itertext()) if list(content) else (content.text or "")


def _author(entry: ET.Element) -> str | None:
    node = _find(_find(entry, "author"), "name")
    if node is None or node.text is None:
        return None
    value = re.sub(r"^/?u/", "", node.text.strip(), flags=re.I)
    return value or None


def _post_id(raw_id: str | None, url: str, entry_xml: str = "", index: int = 0) -> str:
    raw = (raw_id or "").strip()
    if raw.startswith("t3_"):
        return raw[3:]
    match = re.search(r"/comments/([a-z0-9]+)/", url, re.I)
    if match:
        return match.group(1)
    basis = raw or url
    if not basis:
        basis = f"{index}:{entry_xml}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]


def listing_tag(title: str) -> str | None:
    match = _LISTING_TYPE_RE.search(title)
    return match.group(1).upper() if match else None


def normalize_listing_type(tag: str | None) -> str:
    if not tag:
        return "unknown"
    value = tag.upper()
    if value in _SALE_TAGS:
        return "sale"
    if value in _WANT_TAGS:
        return "want"
    if value in _FREE_TAGS:
        return "free"
    return "unknown"


def location_code(title: str) -> str | None:
    match = _LOCATION_RE.search(title)
    if not match:
        return None
    value = match.group(1).upper()
    if value.startswith("USA-"):
        value = "US-" + value[4:]
    return value


def _shipping_hint(title: str) -> str | None:
    if re.search(r"\b(?:free\s+shipping|shipped)\b", title, re.I):
        return "shipping_included"
    return None


def _hws_item_parts(text: str) -> list[str]:
    parts = [part.strip(" ,;|") for part in _HWS_ITEM_SPLIT_RE.split(_PRICE_RE.sub(" ", text))]
    return [
        part
        for part in parts
        if re.search(r"[A-Za-z]", part) and not _HWS_NON_ITEM_PART_RE.match(part)
    ]


def _hws_side_is_cash(text: str) -> bool:
    value = text.strip()
    if not value:
        return False
    if _PRICE_RE.search(value):
        if not _hws_item_parts(value):
            return True
    residual = _PAYMENT_WORD_RE.sub(" ", value)
    residual = _PAYMENT_FILLER_RE.sub(" ", residual)
    residual = _HWS_BARE_AMOUNT_RE.sub(" ", residual)
    residual = re.sub(r"[\s,;/+.&-]+", "", residual)
    return not residual and bool(_PAYMENT_WORD_RE.search(value))


def parse_hardwareswap_title(title: str) -> dict[str, str | None] | None:
    """Parse "[USA-TN] [H] <have> [W] <want>" into its semantic deal shape.

    The [H]/[W] sides name what the poster has/wants; which side carries
    tracked hardware vs cash decides the listing type: H=hardware and W=cash
    is a sale, H=cash and W=hardware is a want-to-buy, hardware on both sides
    is a trade.
    """
    match = _HWS_SIDES_RE.search(title)
    if not match:
        return None
    have = re.sub(r"\s+", " ", match.group("have") or "").strip()
    want = re.sub(r"\s+", " ", match.group("want") or "").strip()
    have_cash = _hws_side_is_cash(have)
    want_cash = _hws_side_is_cash(want)
    if have_cash and not want_cash:
        listing_type = "want"
    elif not have_cash and want_cash:
        listing_type = "sale"
    elif not have_cash and want:
        listing_type = "trade"
    else:
        listing_type = "unknown"
    return {"listing_type": listing_type, "have": have, "want": want}


def classify_listing_type(community: str, title: str) -> str:
    if community == "hardwareswap":
        parsed = parse_hardwareswap_title(title)
        return parsed["listing_type"] if parsed is not None else "unknown"
    return normalize_listing_type(listing_tag(title))


class RedditAtomAdapter(SourceAdapter):
    """Shared Atom parsing for Reddit ``/new.rss`` feeds.

    Entries are deduplicated by ``post_id`` (feeds can repeat an entry across
    polls). ``on_duplicate`` controls what happens to later occurrences:

    - ``"first_wins"`` (default): the first occurrence owns the canonical
      ``source_listing_id``; later occurrences are emitted as quarantined
      duplicate-marker captures with a ``#dup-N``-suffixed listing id and
      ``metadata["duplicate_of"]`` pointing at the winning capture, so no two
      captures ever share a listing id.
    - ``"keep_all"``: every occurrence is emitted as a plain capture under its
      raw listing id (duplicates only carry ``metadata["duplicate_of"]``).
    """

    community: ClassVar[str] = "reddit"
    on_duplicate: ClassVar[str] = "first_wins"

    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        payload = self._decode(raw_data)
        base_metadata = self._merge_extra(metadata, source_url)
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            yield self._error_capture(
                error=f"invalid_atom_xml: {exc}",
                raw_payload=payload,
                payload_format="atom",
                source=self.source_name,
                extra=base_metadata,
                fetched_at=fetched_at,
            )
            return

        seen: dict[str, str] = {}
        duplicate_counts: dict[str, int] = {}
        for index, entry in enumerate(_findall(root, "entry")):
            entry_xml = ET.tostring(entry, encoding="unicode")
            title = _child_text(entry, "title") or ""
            link = _entry_link(entry)
            raw_id = _child_text(entry, "id")
            post_id = _post_id(raw_id, link, entry_xml, index)
            listing_id = (raw_id or "").strip() or post_id

            entry_metadata = {
                **base_metadata,
                "community": self.community,
                "post_id": post_id,
                "title": title,
                "author": _author(entry),
                "content_html": _entry_content_html(entry),
                "updated": _child_text(entry, "updated"),
                "created_at": _child_text(entry, "published"),
                "listing_type": classify_listing_type(self.community, title),
                "location": location_code(title),
                "shipping_hint": _shipping_hint(title),
            }

            is_duplicate = post_id in seen
            if is_duplicate:
                entry_metadata["duplicate_of"] = seen[post_id]
                entry_metadata["on_duplicate"] = self.on_duplicate
                if self.on_duplicate != "keep_all":
                    duplicate_counts[post_id] = duplicate_counts.get(post_id, 0) + 1
                    listing_id = f"{listing_id}#dup-{duplicate_counts[post_id]}"
            else:
                seen[post_id] = listing_id

            if not title:
                entry_metadata["parse_error"] = "missing_title"
            if self.community == "hardwareswap":
                sides = parse_hardwareswap_title(title)
                if sides is not None:
                    entry_metadata["have"] = sides["have"]
                    entry_metadata["want"] = sides["want"]

            capture = self._make_capture(
                source=self.source_name,
                source_listing_id=listing_id,
                url=link,
                raw_payload=entry_xml,
                payload_format="atom",
                fetched_at=fetched_at,
                metadata=entry_metadata,
            )
            if is_duplicate and self.on_duplicate != "keep_all":
                capture.status = IngestionStatus.quarantined
            yield capture


@register_adapter
class RedditHomelabsalesAdapter(RedditAtomAdapter):
    source_name = "reddit_homelabsales"
    community = "homelabsales"
    fixture_path = LEGACY_FIXTURE_ROOT / "reddit_homelabsales" / "fixtures" / "sample_atom.xml"


@register_adapter
class RedditHardwareswapAdapter(RedditAtomAdapter):
    source_name = "reddit_hardwareswap"
    community = "hardwareswap"
    fixture_path = LEGACY_FIXTURE_ROOT / "reddit_homelabsales" / "fixtures" / "sample_hws_atom.xml"
