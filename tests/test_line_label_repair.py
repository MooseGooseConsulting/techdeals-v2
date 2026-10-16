"""Focused checks for seller-label provenance during extraction repair."""

import pytest
from engine.extract import _repair_lines


def _line(label: str, *, children=None, attributes=None):
    return {
        "label": label,
        "quantity": None,
        "separately_purchasable": False,
        "attributes": attributes or {},
        "children": children or [],
    }


def test_blank_component_in_multi_component_listing_fails_as_a_whole():
    lines = [_line("clearly stated component"), _line("   ")]
    with pytest.raises(ValueError, match="ambiguous"):
        _repair_lines(lines, "group heading", "capture title")


def test_blank_child_is_not_silently_dropped():
    lines = [_line("server", children=[{"label": "  "}])]
    with pytest.raises(ValueError, match="child line has no seller label"):
        _repair_lines(lines, None, "capture title")


@pytest.mark.parametrize("fallback", [None, ""])
def test_single_blank_line_cannot_borrow_group_or_attributes(fallback):
    lines = [_line("", attributes={"storage_capacity_gb": 1000})]
    with pytest.raises(ValueError, match="no capture title"):
        _repair_lines(lines, "group heading", fallback)


def test_single_product_can_use_actual_capture_title_with_provenance():
    repaired = _repair_lines([_line("")], "unrelated group heading", "Actual Capture Title")
    assert len(repaired) == 1
    assert repaired[0]["label"] == "Actual Capture Title"
    assert repaired[0]["attributes"]["label_filled_from"] == "capture_title"


def test_blank_parent_with_children_cannot_borrow_child_or_title():
    lines = [_line("", children=[{"label": "actual child"}])]
    with pytest.raises(ValueError, match="ambiguous"):
        _repair_lines(lines, "group heading", "capture title")
