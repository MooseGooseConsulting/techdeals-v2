from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine import extract
from engine.adapters.govdeals import project as project_govdeals


def test_truncated_batch_does_not_recurse_below_floor(tmp_path: Path) -> None:
    class TruncatingClient:
        model = extract.DEFAULT_MODEL

        def __init__(self) -> None:
            self.call_sizes: list[int] = []

        def call(self, _system, payload, _schema, _tokens):
            self.call_sizes.append(len(payload["listings"]))
            return [], {
                "prompt_tokens": 1, "completion_tokens": 1, "cached_tokens": 0,
                "latency_s": 0.1, "truncated": True, "salvaged": False,
            }

    for count in (2, 3):
        client = TruncatingClient()
        batch = [{"client_id": str(i), "condensed": {}} for i in range(count)]
        results, failed, row = extract.run_batch_call(
            client, batch, 100, str(tmp_path / f"ledger-{count}.jsonl"), count
        )
        assert results == {}
        assert set(failed) == {str(i) for i in range(count)}
        assert client.call_sizes == [count]
        assert row["status"] == "truncated_below_split_floor"


def test_truncated_batch_of_four_splits_only_into_floor_sized_calls(tmp_path: Path) -> None:
    class Client:
        model = extract.DEFAULT_MODEL

        def __init__(self) -> None:
            self.call_sizes: list[int] = []

        def call(self, _system, payload, _schema, _tokens):
            items = payload["listings"]
            self.call_sizes.append(len(items))
            if len(items) == 4:
                return [], {
                    "prompt_tokens": 1, "completion_tokens": 1, "cached_tokens": 0,
                    "latency_s": 0.1, "truncated": True, "salvaged": False,
                }
            return ([{"id": item["id"], "outcome": "no_purchase_information", "sale_groups": []}
                     for item in items], {
                "prompt_tokens": 1, "completion_tokens": 1, "cached_tokens": 0,
                "latency_s": 0.1, "truncated": False, "salvaged": False,
            })

    client = Client()
    batch = [{"client_id": str(i), "condensed": {}} for i in range(4)]
    results, failed, _ = extract.run_batch_call(
        client, batch, 100, str(tmp_path / "ledger.jsonl"), "four"
    )
    assert client.call_sizes == [4, 2, 2]
    assert set(results) == {str(i) for i in range(4)}
    assert failed == {}


def test_money_comparison_is_decimal_exact() -> None:
    assert extract._amount_equal("9007199254740992.01", "9007199254740992.01")
    assert not extract._amount_equal("9007199254740992.01", "9007199254740992.02")


def test_lot_repair_rejects_price_prefix_and_unrelated_phrase() -> None:
    assert extract._lot_phrase("2x Generic item $2800", "Seagate Exos 8TB", 2, "280") is None
    assert extract._lot_phrase("2x Generic item $280", "Seagate Exos 8TB", 2, "280") is None


def test_source_description_skips_empty_primary_and_supports_aliases() -> None:
    assert extract.source_description({"description": "", "body_html": "seller lot text"}) == "seller lot text"
    assert extract.source_description({"description": "  ", "body_text": "body alias"}) == "body alias"
    assert extract.source_description({"description": 42, "body": "body alias"}) == "body alias"


def test_govdeals_source_event_time_and_file_mtime_do_not_set_fetch_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "govdeals.json"
    raw = json.dumps({
        "item_id": "g1", "domain": "govdeals",
        "timestamp": "2026-10-08T19:00:00Z",
        "fetched_at": "2026-10-02T00:00:00Z", "capture_time": "2026-10-03T00:00:00Z",
    })
    path.write_text(raw)
    monkeypatch.setattr(extract.os.path, "getmtime", lambda _path: 1790000000)
    assert extract.capture_fetched_at(json.loads(raw)) is None
    loaded, skipped = extract.load_listings([str(path)])
    assert loaded == []
    assert skipped == [{
        "client_id": "g1", "path": str(path),
        "reason": "missing_or_invalid_capture_metadata_fetched_at",
    }]
    assert path.read_text() == raw


def test_only_timezone_aware_capture_metadata_fetch_time_is_eligible(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    valid = {
        "item_id": "valid", "domain": "govdeals",
        "timestamp": "2026-10-08T19:00:00Z",
        "capture_metadata": {"fetched_at": "2026-10-01T12:30:00-05:00"},
    }
    path.write_text(json.dumps(valid))
    loaded, skipped = extract.load_listings([str(path)])
    assert not skipped
    assert loaded[0]["fetched_at"] == "2026-10-01T17:30:00+00:00"

    valid["capture_metadata"]["fetched_at"] = "2026-10-01T12:30:00"
    path.write_text(json.dumps(valid))
    assert extract.capture_fetched_at(valid) is None
    loaded, skipped = extract.load_listings([str(path)])
    assert loaded == []
    assert skipped[0]["reason"] == "missing_or_invalid_capture_metadata_fetched_at"


def test_all_unknown_fetch_times_return_truthful_cli_error(tmp_path: Path, capsys) -> None:
    path = tmp_path / "capture.json"
    raw = json.dumps({"item_id": "unknown", "timestamp": "2026-10-01T00:00:00Z"})
    path.write_text(raw)
    assert extract.main(["--files", str(path), "--skip-db"]) == 3
    assert "no eligible captures" in capsys.readouterr().err
    assert path.read_text() == raw


def test_govdeals_adapter_names_auction_event_date() -> None:
    capture = project_govdeals(
        {"accountId": 1, "assetId": 2},
        {"assetAuctionEndDateUTC": "2026-10-08T19:00:00Z"},
    )
    assert capture["auction_end_date"] == "2026-10-08T19:00:00Z"
    assert "timestamp" not in capture
