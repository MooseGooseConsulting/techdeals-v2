"""Extraction pipeline: raw_captures → LLM extraction → postings/lines/sale_groups/observations.

Reads unprocessed raw_captures from Neon, runs batched LLM extraction,
and writes structured results into the posting-first schema.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re

import psycopg

from techdeals.config import get_settings
from techdeals.db.connection import get_connection
from techdeals.parser.engine import extract_batches
from techdeals.parser.models import (
    BatchExtractionResponse,
    ExtractedLine,
    ExtractedObservation,
    ExtractedSaleGroup,
    ExtractionResult,
    RawListingForExtraction,
    compute_offer_key,
)

logger = logging.getLogger(__name__)


def run_extraction(
    batch_size: int | None = None,
    model: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Run the extraction pipeline on unprocessed raw_captures.

    1. Fetch raw_captures that have no posting yet
    2. Prepare them for LLM extraction
    3. Run batched LLM extraction
    4. Write results to postings/lines/sale_groups/observations

    Returns: summary dict with counts
    """
    settings = get_settings()
    batch_size = batch_size or settings.llm_batch_size
    model = model or settings.llm_model

    conn = get_connection()

    try:
        # 1. Fetch unprocessed captures
        captures = _fetch_unprocessed(conn, limit)
        logger.info("Found %d unprocessed captures", len(captures))

        if not captures:
            return {"status": "no_work", "captures": 0}

        if dry_run:
            return {"status": "dry_run", "captures": len(captures)}

        # 2. Prepare for LLM
        listings = _prepare_listings(captures)

        # 3. Run LLM extraction
        responses = _run_coroutine(
            extract_batches(listings, batch_size=batch_size, model=model)
        )

        # 4. Write results
        written = _write_results(conn, captures, responses)

        conn.commit()

        return {
            "status": "complete",
            "captures": len(captures),
            **written,
        }

    finally:
        conn.close()


def _run_coroutine(coro):
    """Run an async extraction coroutine from sync code.

    Works both standalone and when called from within a running event loop
    (the CLI wraps commands in asyncio.run).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _fetch_unprocessed(conn: psycopg.Connection, limit: int | None = None):
    """Fetch raw_captures that don't have a posting yet.

    Prioritizes captures containing price-bearing text and interleaves sources
    so a small limit still yields a mix of sources (the unprocessed queue head
    is dominated by unpriced spl_psu_tier_list spec rows).
    """
    query = """
        SELECT id, source, source_listing_id, url, raw_payload,
               payload_format, fetched_at, metadata
        FROM (
            SELECT rc.id, rc.source, rc.source_listing_id, rc.url, rc.raw_payload,
                   rc.payload_format, rc.fetched_at, rc.metadata,
                   ROW_NUMBER() OVER (
                       PARTITION BY rc.source ORDER BY md5(rc.id::text)
                   ) AS source_rank
            FROM raw_captures rc
            LEFT JOIN postings p ON p.capture_id = rc.id
            WHERE p.id IS NULL
              AND rc.raw_payload ~* '(\\$[0-9]|price)'
        ) t
        ORDER BY source_rank, md5(id::text)
    """
    if limit:
        query += f" LIMIT {int(limit)}"

    result = conn.execute(query)
    return result.fetchall()


def _prepare_listings(captures) -> list[RawListingForExtraction]:
    """Convert raw_captures rows into RawListingForExtraction objects."""
    listings = []
    for row in captures:
        (capture_id, source, source_listing_id, url, raw_payload,
         payload_format, fetched_at, metadata) = row

        # Extract text for LLM from the raw payload
        # For JSON: use the raw payload as-is
        # For HTML: strip tags (basic)
        # For XML/Atom: use the raw payload
        text = raw_payload
        if payload_format == "html":
            text = re.sub(r"<[^>]+>", " ", raw_payload)
            text = re.sub(r"\s+", " ", text).strip()

        listings.append(RawListingForExtraction(
            capture_id=str(capture_id),
            source=source,
            url=url,
            title=None,
            raw_text=text[:8000],  # Truncate for LLM
            payload_format=payload_format,
        ))

    return listings


def _write_results(
    conn: psycopg.Connection,
    captures,
    responses: list[BatchExtractionResponse],
) -> dict:
    """Write extraction results to the database."""
    counts = {"postings": 0, "lines": 0, "sale_groups": 0, "observations": 0}

    # Flatten responses to match captures order
    all_results = []
    for resp in responses:
        all_results.extend(resp.results)

    if len(all_results) != len(captures):
        logger.warning(
            "Result count mismatch: %d results for %d captures",
            len(all_results),
            len(captures),
        )

    for row, extraction in zip(captures, all_results):
        (capture_id, source, source_listing_id, url, raw_payload,
         payload_format, fetched_at, metadata) = row

        try:
            # Each capture writes inside a savepoint so one failure
            # never rolls back captures already written.
            with conn.transaction():
                # Insert posting
                posting_id = _insert_posting(
                    conn, capture_id, source, source_listing_id, url, extraction
                )
                counts["postings"] += 1

                # Insert lines
                line_ids = {}
                for line in extraction.lines:
                    line_id = _insert_line(conn, posting_id, line, line_ids)
                    line_ids[line.line_number] = line_id
                    counts["lines"] += 1

                # Insert sale groups
                for sg in extraction.sale_groups:
                    _insert_sale_group(conn, posting_id, sg, line_ids)
                    counts["sale_groups"] += 1

                # Insert observations
                for obs in extraction.observations:
                    _insert_observation(
                        conn, posting_id, obs, line_ids, source, source_listing_id, fetched_at
                    )
                    counts["observations"] += 1

        except Exception as e:
            logger.error("Failed to write extraction for capture %s: %s", capture_id, e)
            # Savepoint already rolled back this capture only;
            # still create a posting with failure status.
            _insert_failed_posting(conn, capture_id, source, source_listing_id, url, str(e))
            counts["postings"] += 1

    return counts


def _insert_posting(
    conn: psycopg.Connection,
    capture_id,
    source,
    source_listing_id,
    url,
    extraction: ExtractionResult,
):
    """Insert a posting and return its ID."""
    status = "quarantined" if extraction.quarantine_reason else "extracted"

    result = conn.execute(
        """INSERT INTO postings (
            capture_id, source, source_listing_id, url, title, description,
            seller, location, currency, listing_format,
            status, failure_mode, failure_details
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id""",
        (
            capture_id, source, source_listing_id, url,
            extraction.title, extraction.description,
            extraction.seller, extraction.location,
            extraction.currency,
            extraction.listing_format.value if extraction.listing_format else None,
            status,
            "quarantine" if extraction.quarantine_reason else None,
            extraction.quarantine_reason or extraction.notes or None,
        ),
    )
    return result.fetchone()[0]


def _insert_failed_posting(
    conn: psycopg.Connection,
    capture_id,
    source,
    source_listing_id,
    url,
    error,
):
    """Insert a posting with failure status."""
    conn.execute(
        """INSERT INTO postings (
            capture_id, source, source_listing_id, url,
            status, failure_mode, failure_details
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (capture_id, source, source_listing_id, url, "failed", "parse_failed", error),
    )


def _insert_line(
    conn: psycopg.Connection,
    posting_id,
    line: ExtractedLine,
    existing_line_ids: dict,
) -> str:
    """Insert a line and return its ID."""
    result = conn.execute(
        """INSERT INTO lines (
            posting_id, parent_line_id, line_number, label,
            category, quantity, separately_purchasable, raw_text
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id""",
        (
            posting_id,
            existing_line_ids.get(line.line_number - 1) if line.line_number > 1 else None,
            line.line_number,
            line.label,
            line.category,
            line.quantity,
            line.separately_purchasable,
            line.raw_text,
        ),
    )
    return result.fetchone()[0]


def _insert_sale_group(
    conn: psycopg.Connection,
    posting_id,
    sg: ExtractedSaleGroup,
    line_ids: dict,
):
    """Insert a sale group and its line memberships."""
    result = conn.execute(
        """INSERT INTO sale_groups (
            posting_id, label, price_basis, total_price_cents,
            total_currency, quantity_in_group, notes
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (posting_id, label) DO UPDATE
        SET notes = COALESCE(EXCLUDED.notes, sale_groups.notes)
        RETURNING id""",
        (
            posting_id,
            sg.label,
            sg.price_basis.value if sg.price_basis else "bound_only",
            sg.total_price_cents,
            sg.total_currency,
            sg.quantity_in_group,
            sg.notes,
        ),
    )
    sg_id = result.fetchone()[0]

    for line_num in sg.line_numbers:
        line_id = line_ids.get(line_num)
        if line_id:
            conn.execute(
                """INSERT INTO sale_group_lines (sale_group_id, line_id, quantity_in_group)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING""",
                (sg_id, line_id, 1),
            )


def _insert_observation(
    conn: psycopg.Connection,
    posting_id,
    obs: ExtractedObservation,
    line_ids: dict,
    source: str,
    source_listing_id: str,
    fetched_at,
):
    """Insert an observation."""
    line_id = line_ids.get(obs.line_number) if obs.line_number else None

    offer_key = compute_offer_key(
        source=source,
        source_listing_id=source_listing_id,
        line_number=obs.line_number or 0,
    )

    conn.execute(
        """INSERT INTO observations (
            posting_id, line_id, offer_key, observed_at,
            price_cents, price_kind, available, source
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            posting_id,
            line_id,
            offer_key,
            obs.observed_at or fetched_at,
            obs.price_cents,
            obs.price_kind.value if obs.price_kind else "ask",
            obs.available,
            source,
        ),
    )
