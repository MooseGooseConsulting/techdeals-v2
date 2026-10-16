#!/usr/bin/env python3
"""Checks for empty-label repair, lot-vs-each basis, and identity keys.

Run directly with ``python3 engine/test_repairs.py`` or explicitly with
``pytest engine/test_repairs.py``. The project config limits default pytest
discovery to ``tests/``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract  # noqa: E402
import resolve  # noqa: E402


def expect(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(f"FAIL {message}")
    print(f"PASS {message}")


def test_empty_label() -> None:
    res = extract.validate_result({
        "id": "1",
        "outcome": "extracted",
        "sale_groups": [{
            "label": "group label is not the line label",
            "availability": "available",
            "price": {
                "amount": "89.99", "currency": "USD", "price_kind": "ask",
                "price_basis": "explicit_unit", "quantity_units": 1,
                "bound_low": None, "bound_high": None, "basis_note": None,
            },
            "lines": [{
                "label": "",
                "quantity": 1,
                "separately_purchasable": True,
                "attributes": {"storage_capacity_gb": 1000},
                "children": [],
            }],
        }],
    }, fallback_label="Capture title")
    line = res["sale_groups"][0]["lines"][0]
    expect(line["label"] == "Capture title", "single product label filled from capture title")
    expect(line["attributes"]["label_filled_from"] == "capture_title", "capture-title fill source recorded")

    for name, lines in (
        ("multi-component blank", [
            {"label": "kept", "quantity": 1, "separately_purchasable": True, "attributes": {}, "children": []},
            {"label": "  ", "quantity": None, "separately_purchasable": False, "attributes": {}, "children": []},
        ]),
        ("blank parent with child", [{
            "label": "", "quantity": None, "separately_purchasable": False,
            "attributes": {"storage_capacity_gb": 1000},
            "children": [{"label": "child label", "quantity": 1}],
        }]),
        ("blank child", [{
            "label": "parent", "quantity": None, "separately_purchasable": False,
            "attributes": {}, "children": [{"label": "  "}],
        }]),
    ):
        try:
            extract._repair_lines(lines, "group label", "Capture title")
        except ValueError:
            expect(True, f"{name} fails explicitly")
        else:
            expect(False, f"{name} fails explicitly")

    try:
        extract._repair_lines([{"label": "", "attributes": {"storage_capacity_gb": 1000}, "children": []}],
                              "group label", None)
    except ValueError:
        expect(True, "group label and generated attributes cannot fill a line label")
    else:
        expect(False, "group label and generated attributes cannot fill a line label")


def test_lot_versus_each() -> None:
    description = "4x 8TB Seagate Exos SATA HDDs $280\nSamsung 980 Pro 2TB NVMe SSD $110"
    po = {"price_basis": "explicit_unit", "amount": "280", "quantity": 1.0, "basis_note": None}
    note = extract.apply_source_price_basis(description, "Seagate Exos 8TB SATA HDD", 4, po)
    expect(note is not None and po["price_basis"] == "homogeneous_division", "lot total stays a lot total")
    expect(po["quantity"] == 4.0 and po["amount"] == "280", "lot amount is not divided")

    description = "2x 20TB WD Gold SATA $150 each\n6x 12TB HGST SAS HDD $360"
    each = {"price_basis": "explicit_unit", "amount": "150", "quantity": 1.0, "basis_note": None}
    note = extract.apply_source_price_basis(description, "WD Gold 20TB SATA HDD", 2, each)
    expect(note is not None and each["price_basis"] == "explicit_unit" and each["quantity"] == 1.0,
           "each-price stays per unit")
    lot = {"price_basis": "explicit_unit", "amount": "360", "quantity": 1.0, "basis_note": None}
    note = extract.apply_source_price_basis(description, "HGST 12TB SAS HDD", 6, lot)
    expect(lot["price_basis"] == "homogeneous_division" and lot["quantity"] == 6.0, "undecorated Nx $P is a lot")

    server = "8x 32GB DDR4 installed in a PowerEdge R6515 $2499"
    poisoned = {"price_basis": "explicit_unit", "amount": "2499", "quantity": 1.0, "basis_note": None}
    note = extract.apply_source_price_basis(server, "32GB DDR4 DIMM", 8, poisoned)
    expect(note is None and poisoned["price_basis"] == "explicit_unit", "a server sentence is not a lot of DIMMs")


def test_identity() -> None:
    drive = resolve.product_identity({
        "storage_capacity_gb": 1000, "storage_kind": "SSD", "storage_interface": "SATA III 6Gb/s",
    })
    expect(drive["product_key"] == "drive:ssd:sata:1000gb", "drive key from capacity, kind, interface")
    dimm = resolve.product_identity({
        "ram_dimm_gb": 32, "ram_type": "DDR4-3200 RDIMM", "ram_kind": "RDIMM", "ram_speed_mts": 3200,
    })
    expect(dimm["product_key"] == "mem:ddr4:rdimm:32gb:3200", "DIMM key from size, family, kind, speed")
    server = resolve.product_identity({"cpu_model": "EPYC 7542", "chassis_model": "PowerEdge R6515", "ram_dimm_gb": 32})
    expect(server["product_key"].startswith("server:"), "a line with a CPU and a chassis is a server, not a DIMM")
    expect(resolve.product_identity({"quantity_stated": True}) is None, "no price-determining facts stays unresolved")


if __name__ == "__main__":
    test_empty_label()
    test_lot_versus_each()
    test_identity()
    print("all repair checks passed")
