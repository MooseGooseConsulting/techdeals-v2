from __future__ import annotations

import json
from pathlib import Path

from engine import resolve

ROOT = Path(__file__).resolve().parents[1]


def test_load_lines_includes_current_extraction_children_and_scopes_posting(
    monkeypatch,
) -> None:
    child = {
        "line_id": "00000000-0000-0000-0000-000000000002",
        "posting_id": "00000000-0000-0000-0000-000000000001",
        "label": "32GB DDR4 RDIMM",
        "attributes": {"ram_dimm_gb": 32, "ram_type": "DDR4 RDIMM", "ram_kind": "RDIMM"},
    }
    captured: dict[str, str] = {}

    def run_psql(_dsn: str, sql: str) -> list[str]:
        captured["sql"] = sql
        return [json.dumps([child])]

    monkeypatch.setattr(resolve.extract, "run_psql", run_psql)

    assert resolve._load_lines("unused") == [child]
    assert "c.posting_id = l.posting_id" in captured["sql"]
    assert "c.extraction_id = l.extraction_id" in captured["sql"]
    assert "l.parent_line_id IS NULL" not in captured["sql"]


def test_plan_resolves_stated_child_attributes_to_its_own_posting() -> None:
    parent_posting = "00000000-0000-0000-0000-000000000001"
    child_line = {
        "line_id": "00000000-0000-0000-0000-000000000002",
        "posting_id": parent_posting,
        "label": "32GB DDR4 RDIMM",
        "attributes": {"ram_dimm_gb": 32, "ram_type": "DDR4 RDIMM", "ram_kind": "RDIMM"},
    }

    inserts, supersede, counts = resolve.plan([child_line], {})

    assert len(inserts) == 1
    assert inserts[0]["line_id"] == child_line["line_id"]
    assert inserts[0]["posting_id"] == parent_posting
    assert inserts[0]["product_key"] == "mem:ddr4:rdimm:32gb"
    assert supersede == []
    assert counts == {"lines": 1, "resolved": 1, "unresolved": 0, "unchanged": 0}


def test_resolution_write_rejects_cross_posting_line_membership(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def run_psql(_dsn: str, sql: str) -> list[str]:
        captured["sql"] = sql
        return []

    monkeypatch.setattr(resolve.extract, "run_psql", run_psql)
    resolve._write(
        "unused",
        [
            {
                "id": "00000000-0000-0000-0000-000000000003",
                "posting_id": "00000000-0000-0000-0000-000000000001",
                "line_id": "00000000-0000-0000-0000-000000000002",
                "product_key": "mem:ddr4:rdimm:32gb",
                "product_name": "32GB DDR4 RDIMM",
                "confidence": 0.9,
                "method": resolve.METHOD,
            }
        ],
        [],
    )

    assert "l.id = (doc->>'line_id')::uuid" in captured["sql"]
    assert "l.posting_id = (doc->>'posting_id')::uuid" in captured["sql"]
    assert "RAISE EXCEPTION 'resolution line must belong to the stated posting'" in captured["sql"]


def test_cheapest_ram_query_includes_derived_units_and_requires_stated_rdimm() -> None:
    sql = (ROOT / "engine" / "query_cheapest.sql").read_text()
    ram_query = sql.split("SELECT '1000GB SSD'", maxsplit=1)[0]

    assert "price_basis IN ('explicit_unit', 'homogeneous_division')" in ram_query
    assert "(member_line_count IS NULL OR member_line_count = 1)" in ram_query
    assert "attributes @> '{\"ram_dimm_gb\": 32}'::jsonb" in ram_query
    assert "attributes->>'ram_type', '') ILIKE '%DDR4%'" in ram_query
    assert "attributes->>'ram_kind', '') ILIKE '%RDIMM%'" in ram_query
    assert "attributes->>'ram_type', '') ILIKE '%RDIMM%'" in ram_query
