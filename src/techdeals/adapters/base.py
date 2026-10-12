"""Base adapter class for source-specific ingestion.

Each source (waterpanther, reddit, govdeals, etc.) has an adapter that
knows how to read raw data from that source's format and produce
RawCapture objects for the pipeline.

Adapters handle BOTH fixture files and live data — they are the bridge
between a source's output format and the pipeline's canonical RawCapture.

Nothing is silently dropped: any input an adapter cannot parse is emitted
as a RawCapture whose metadata carries ``parse_error`` and whose raw
payload preserves the offending content.
"""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Iterator

from techdeals.ingestion.contract import IngestionStatus, RawCapture

logger = logging.getLogger(__name__)

_PAYLOAD_FORMAT_BY_SUFFIX = {
    ".json": "json",
    ".xml": "atom",
    ".html": "html",
    ".htm": "html",
    ".csv": "html",
}


def _payload_format_for(fixture_file: Path | None) -> str:
    if fixture_file is not None:
        mapped = _PAYLOAD_FORMAT_BY_SUFFIX.get(fixture_file.suffix.lower())
        if mapped:
            return mapped
    return "html"


def fallback_listing_id(raw_payload: str, prefix: str = "") -> str:
    """Derive a stable non-empty listing ID from raw content."""
    digest = hashlib.sha256(raw_payload.encode()).hexdigest()[:12]
    return f"{prefix}{digest}" if prefix else digest


class SourceAdapter(ABC):
    """Base class for all source adapters.

    Subclasses must implement:
    - `source_name`: unique identifier for the source
    - `fixture_path`: Path to the fixture directory (or None if fixture-only)
    - `parse_raw()`: Convert raw data (str/bytes) into RawCapture objects
    """

    source_name: ClassVar[str]
    fixture_path: ClassVar[Path | None] = None

    @abstractmethod
    def parse_raw(
        self,
        raw_data: str | bytes,
        source_url: str = "",
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> Iterator[RawCapture]:
        """Parse raw data from this source into RawCapture objects.

        Args:
            raw_data: The raw payload (HTML, JSON, XML, etc.)
            source_url: The URL where the data was fetched from
            fetched_at: When the data was fetched (defaults to now)
            metadata: Additional source-specific metadata

        Yields:
            RawCapture objects ready for database insertion
        """
        ...

    def load_fixtures(self, max_count: int | None = None) -> Iterator[RawCapture]:
        """Load fixture files from the fixture directory.

        Reads all fixture files and feeds them through parse_raw(). A file
        that cannot be read or parsed yields a failure capture carrying the
        raw file content (``metadata["parse_error"]``) instead of aborting
        the remaining files.
        """
        if self.fixture_path is None:
            raise FileNotFoundError(f"No fixture path configured for {self.source_name}")
        if not self.fixture_path.exists():
            raise FileNotFoundError(f"Fixture directory not found: {self.fixture_path}")

        count = 0
        for fixture_file in sorted(self._iter_fixture_files()):
            if max_count is not None and count >= max_count:
                break
            yield from self._load_fixture_file(fixture_file)
            count += 1

    def _load_fixture_file(self, fixture_file: Path) -> Iterator[RawCapture]:
        """Parse one fixture file, yielding a failure capture on error."""
        fetched_at: datetime | None = None
        raw_data = ""
        try:
            mtime = fixture_file.stat().st_mtime
            fetched_at = datetime.fromtimestamp(mtime, tz=timezone.utc)
            raw_data = fixture_file.read_text()
            yield from self.parse_raw(
                raw_data=raw_data,
                source_url=f"fixture://{fixture_file.name}",
                fetched_at=fetched_at,
                metadata={"fixture_file": str(fixture_file)},
            )
        except Exception as exc:
            logger.error(
                "Failed to load fixture %s for %s: %s", fixture_file, self.source_name, exc
            )
            yield self._failure_capture(
                raw_payload=raw_data,
                error=f"{type(exc).__name__}: {exc}",
                fixture_file=fixture_file,
                fetched_at=fetched_at,
            )

    def _failure_capture(
        self,
        raw_payload: str,
        error: str,
        fixture_file: Path | None = None,
        fetched_at: datetime | None = None,
    ) -> RawCapture:
        """Build the flagged capture for input this adapter could not parse."""
        source_listing_id = fallback_listing_id(
            f"{self.source_name}:{fixture_file}:{raw_payload}", prefix="parse-error-"
        )
        label = fixture_file.name if fixture_file is not None else self.source_name
        metadata: dict = {"parse_error": error}
        if fixture_file is not None:
            metadata["fixture_file"] = str(fixture_file)
        return RawCapture(
            source=self.source_name,
            source_listing_id=source_listing_id,
            url=f"fixture://{label}",
            fetched_at=fetched_at or datetime.now(timezone.utc),
            checksum=hashlib.sha256(raw_payload.encode()).hexdigest(),
            raw_payload=raw_payload,
            payload_format=_payload_format_for(fixture_file),
            metadata=metadata,
            status=IngestionStatus.failed,
        )

    def _iter_fixture_files(self) -> Iterator[Path]:
        """Iterate fixture files. Override for custom file patterns."""
        if self.fixture_path is None:
            return
        for pattern in ["*.json", "*.xml", "*.html", "*.csv"]:
            yield from sorted(self.fixture_path.glob(pattern))

    @staticmethod
    def _make_capture(
        source: str,
        source_listing_id: str,
        url: str,
        raw_payload: str,
        payload_format: str,
        fetched_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> RawCapture:
        """Create a RawCapture with standard fields filled in.

        Empty listing IDs fall back to a hash of the raw payload and empty
        URLs fall back to a deterministic urn, so no capture is ever lost to
        contract validation.
        """
        if not source_listing_id:
            source_listing_id = fallback_listing_id(raw_payload)
        if not url:
            url = f"urn:techdeals:{source}:{source_listing_id}"
        return RawCapture(
            source=source,
            source_listing_id=source_listing_id,
            url=url,
            fetched_at=fetched_at or datetime.now(timezone.utc),
            checksum=hashlib.sha256(raw_payload.encode()).hexdigest(),
            raw_payload=raw_payload,
            payload_format=payload_format,
            metadata=metadata or {},
        )


# --- Registry ---

_REGISTRY: dict[str, type[SourceAdapter]] = {}


def register_adapter(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    """Class decorator to register an adapter by its source_name."""
    _REGISTRY[cls.source_name] = cls
    return cls


def get_adapter(source_name: str) -> SourceAdapter:
    """Get an instantiated adapter by source name."""
    if source_name not in _REGISTRY:
        raise KeyError(f"Unknown source: {source_name}. Registered: {list(_REGISTRY.keys())}")
    return _REGISTRY[source_name]()


def list_sources() -> list[str]:
    """List all registered source names."""
    return sorted(_REGISTRY.keys())


def load_all(max_per_source: int | None = None) -> Iterator[RawCapture]:
    """Load fixtures from all registered adapters.

    Missing fixture corpora are skipped; any other failure yields a flagged
    failure capture instead of being printed and dropped.
    """
    for source_name in list_sources():
        adapter = get_adapter(source_name)
        try:
            yield from adapter.load_fixtures(max_count=max_per_source)
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.error("Error loading %s: %s", source_name, exc)
            yield adapter._failure_capture(
                raw_payload="",
                error=f"{type(exc).__name__}: {exc}",
            )
