#!/usr/bin/env python3
"""Replay already-extracted results through the current writer.

No LLM call. The saved per-listing results are what the model returned;
build_batch_doc applies the current price-basis rules (lot total vs each)
before the rows hit the database. Requires TDV2_DSN.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract  # noqa: E402


RESULTS_FORMAT = "techdeals-saved-results/v2"


def validated_replay_batch(saved: dict, listings: list[dict], dropped: list[dict]):
    """Validate every saved result against its exact current capture.

    This gate is intentionally all-or-nothing and runs before any database
    operation. Legacy result files remain useful as evidence, but lack the
    provenance needed to replay safely.
    """
    if not isinstance(saved, dict) or saved.get("format") != RESULTS_FORMAT:
        raise ValueError(f"unsupported results format; replay requires {RESULTS_FORMAT}")
    rows = saved.get("results")
    if not isinstance(rows, list):
        raise ValueError("saved results is not an array")
    by_listing = {str(listing["client_id"]): listing for listing in listings}
    duplicated_captures = {str(row["client_id"]) for row in dropped}
    results_by_id = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            raise ValueError("saved result has no listing id")
        cid = str(row["id"])
        if cid in results_by_id:
            raise ValueError(f"duplicate saved result id {cid}")
        capture = row.get("capture")
        valid_capture = (
            isinstance(capture, dict)
            and isinstance(capture.get("checksum"), str)
            and bool(capture.get("checksum"))
            and isinstance(capture.get("offer_key"), str)
            and bool(capture.get("offer_key"))
        )
        if not valid_capture:
            raise ValueError(f"saved result {cid} lacks capture checksum or offer key")
        listing = by_listing.get(cid)
        if listing is None:
            raise ValueError(f"saved result {cid} has no matching current capture")
        if cid in duplicated_captures:
            raise ValueError(f"current captures contain duplicate listing id {cid}")
        if capture["checksum"] != listing["checksum"]:
            raise ValueError(f"capture checksum mismatch for listing {cid}")
        if capture["offer_key"] != listing["offer_key"]:
            raise ValueError(f"offer key mismatch for listing {cid}")
        results_by_id[cid] = {key: value for key, value in row.items() if key != "capture"}
    return [listing for listing in listings if listing["client_id"] in results_by_id], results_by_id


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Load saved extraction results")
    ap.add_argument("--results", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--parser-version", required=True)
    ap.add_argument("--chunk", type=int, default=40)
    args = ap.parse_args(argv)
    if args.chunk <= 0:
        ap.error("--chunk must be greater than zero")
    dsn = os.environ.get("TDV2_DSN")
    if not dsn:
        print("TDV2_DSN not set", file=sys.stderr)
        return 2
    with open(args.results) as handle:
        saved = json.load(handle)
    paths = sorted(glob.glob(os.path.join(args.raw_dir, "**", "*.json"), recursive=True))
    listings, dropped = extract.load_listings(paths)
    try:
        batch, by_id = validated_replay_batch(saved, listings, dropped)
    except ValueError as exc:
        print(f"refusing replay: {exc}", file=sys.stderr)
        return 2
    print(
        f"loading {len(batch)} provenance-verified saved results from {args.results}",
        file=sys.stderr,
    )
    if not batch:
        return 1
    wrote = {"extractions": 0, "prices": 0, "lines": 0}
    for start in range(0, len(batch), args.chunk):
        chunk = batch[start:start + args.chunk]
        posting_map = extract.db_upsert_postings(dsn, [extract.postset_payload(listing) for listing in chunk])
        for listing in chunk:
            listing["posting_id"] = posting_map[listing["offer_key"]]
        doc = extract.build_batch_doc(
            chunk, saved.get("model") or extract.DEFAULT_MODEL,
            f"llm_batch:{args.parser_version}", 0.0, by_id, {},
        )
        for note in doc.pop("ledger_notes", []):
            print(f"  engine note: {note}", file=sys.stderr)
        doc, dropped_prices, dropped_avail = extract.db_filter_replayed_observations(dsn, doc)
        if dropped_prices or dropped_avail:
            print(f"  replay dedupe: {len(dropped_prices)} price / {len(dropped_avail)} availability", file=sys.stderr)
        extract.db_write_batch(dsn, doc)
        wrote["extractions"] += len(doc["extractions"])
        wrote["prices"] += len(doc["prices"])
        wrote["lines"] += len(doc["lines"])
        print(f"  chunk {start}: {len(chunk)} listings", file=sys.stderr)
    print(f"wrote {wrote['extractions']} extractions, {wrote['prices']} prices, {wrote['lines']} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
