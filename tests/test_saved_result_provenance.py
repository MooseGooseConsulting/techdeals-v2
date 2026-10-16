"""Saved-result replay must be bound to the exact capture that produced it."""

import json

import pytest
from engine import extract, load_results  # noqa: E402


def _capture(tmp_path, *, price="100", item_id="42", filename="42.json"):
    payload = {
        "item_id": item_id,
        "url": "https://example.test/listing/42",
        "domain": "example.test",
        "capture_metadata": {"fetched_at": "2026-10-15T12:00:00Z"},
        "price": price,
        "title": "Example item",
    }
    path = tmp_path / filename
    path.write_text(json.dumps(payload))
    return payload, path


def _result(listing, **capture_overrides):
    return {
        "id": listing["client_id"],
        "outcome": "extracted",
        "sale_groups": [],
        "capture": {
            "checksum": listing["checksum"],
            "offer_key": listing["offer_key"],
            **capture_overrides,
        },
    }


def _validate(row, listings, dropped=None, *, format=load_results.RESULTS_FORMAT):
    return load_results.validated_replay_batch(
        {"format": format, "results": [row]}, listings, dropped or []
    )


def test_matching_capture_is_verified_and_unwrapped(tmp_path):
    _, path = _capture(tmp_path)
    listings, dropped = extract.load_listings([str(path)])
    batch, results = _validate(_result(listings[0]), listings, dropped)
    assert [listing["client_id"] for listing in batch] == ["42"]
    assert results["42"]["outcome"] == "extracted"
    assert "capture" not in results["42"]


def test_changed_capture_is_rejected_before_replay(tmp_path):
    _, old_path = _capture(tmp_path, price="100")
    old_listing = extract.load_listings([str(old_path)])[0][0]
    _, new_path = _capture(tmp_path, price="80")
    new_listings, dropped = extract.load_listings([str(new_path)])
    with pytest.raises(ValueError, match="checksum mismatch"):
        _validate(_result(old_listing), new_listings, dropped)


def test_offer_key_mismatch_is_rejected_even_if_content_checksum_matches(tmp_path):
    _, path = _capture(tmp_path)
    listings, dropped = extract.load_listings([str(path)])
    row = _result(listings[0], offer_key="wrong-key")
    with pytest.raises(ValueError, match="offer key mismatch"):
        _validate(row, listings, dropped)


def test_duplicate_current_capture_id_is_rejected(tmp_path):
    _, first = _capture(tmp_path, filename="first.json")
    _, second = _capture(tmp_path, filename="second.json")
    listings, dropped = extract.load_listings([str(first), str(second)])
    with pytest.raises(ValueError, match="duplicate listing id 42"):
        _validate(_result(listings[0]), listings, dropped)


@pytest.mark.parametrize("capture", [None, {}, {"checksum": "present"}, {"offer_key": "present"}])
def test_missing_capture_metadata_is_rejected(capture, tmp_path):
    _, path = _capture(tmp_path)
    listings, _ = extract.load_listings([str(path)])
    row = {"id": "42", "outcome": "extracted", "sale_groups": [], "capture": capture}
    with pytest.raises(ValueError, match="lacks capture checksum or offer key"):
        _validate(row, listings)


def test_legacy_results_are_evidence_only(tmp_path):
    _, path = _capture(tmp_path)
    listings, _ = extract.load_listings([str(path)])
    row = {"id": "42", "outcome": "extracted", "sale_groups": []}
    with pytest.raises(ValueError, match="unsupported results format"):
        _validate(row, listings, format="")
    with pytest.raises(ValueError, match="lacks capture checksum or offer key"):
        _validate(row, listings)


def test_main_refuses_provenance_mismatch_before_database_calls(tmp_path, monkeypatch, capsys):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _, raw_path = _capture(raw_dir)
    listings, _ = extract.load_listings([str(raw_path)])
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps({
        "format": load_results.RESULTS_FORMAT,
        "results": [_result(listings[0], checksum="old-checksum")],
    }))
    monkeypatch.setenv("TDV2_DSN", "offline-test-dsn")
    called = []
    monkeypatch.setattr(extract, "db_upsert_postings", lambda *args: called.append("upsert"))
    assert load_results.main([
        "--results", str(results_path), "--raw-dir", str(raw_dir),
        "--parser-version", "test",
    ]) == 2
    assert called == []
    assert "refusing replay: capture checksum mismatch" in capsys.readouterr().err


def test_nonpositive_chunk_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("TDV2_DSN", "offline-test-dsn")
    with pytest.raises(SystemExit) as exc:
        load_results.main([
            "--results", "unused", "--raw-dir", str(tmp_path),
            "--parser-version", "test", "--chunk", "0",
        ])
    assert exc.value.code == 2
