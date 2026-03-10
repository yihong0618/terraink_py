from __future__ import annotations

from terraink_py.cli import (
    DEFAULT_DISTANCE_M,
    RUNNING_PAGE_DISTANCE_M,
    build_parser,
    resolve_distance_m,
)


def test_resolve_distance_defaults_without_running_page() -> None:
    args = build_parser().parse_args(["大连"])
    assert args.distance_m is None
    assert resolve_distance_m(args) == DEFAULT_DISTANCE_M


def test_resolve_distance_defaults_to_running_page_distance() -> None:
    args = build_parser().parse_args(["大连", "--running_page", "yihong0618/run"])
    assert args.distance_m is None
    assert resolve_distance_m(args) == RUNNING_PAGE_DISTANCE_M


def test_resolve_distance_keeps_explicit_value() -> None:
    args = build_parser().parse_args(
        ["大连", "--running_page", "yihong0618/run", "--distance-m", "6000"]
    )
    assert resolve_distance_m(args) == 6000.0
