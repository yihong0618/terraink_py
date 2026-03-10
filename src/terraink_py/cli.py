from __future__ import annotations

import argparse
from pathlib import Path

from .api import generate_poster
from .data import load_layouts, load_themes
from .models import DEFAULT_OVERPASS_URL, PosterRequest

DEFAULT_DISTANCE_M = 8_000.0
RUNNING_PAGE_DISTANCE_M = 12_000.0


def build_parser() -> argparse.ArgumentParser:
    themes = ", ".join(load_themes().keys())
    layouts = ", ".join(load_layouts().keys())
    parser = argparse.ArgumentParser(
        prog="terraink",
        description="Generate styled OpenStreetMap posters as PNG and SVG.",
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Optional positional location query, equivalent to --location.",
    )
    parser.add_argument(
        "--output", default="outputs/output.png", help="Output file path or base path."
    )
    parser.add_argument("--format", nargs="+", default=["png"], choices=["png", "svg"])
    parser.add_argument("--location", help="Location query for Nominatim geocoding.")
    parser.add_argument(
        "--running_page",
        help=(
            "GitHub repo slug or parquet URL for running_page data, "
            'for example "yihong0618/run".'
        ),
    )
    parser.add_argument("--lat", type=float, help="Latitude.")
    parser.add_argument("--lon", type=float, help="Longitude.")
    parser.add_argument("--title", help="Override poster title.")
    parser.add_argument("--subtitle", help="Override poster subtitle.")
    parser.add_argument(
        "--theme", default="random", help=f"Theme id. Available: {themes}"
    )
    parser.add_argument("--layout", help=f"Layout id. Available: {layouts}")
    parser.add_argument(
        "--width-cm", type=float, default=21.0, help="Poster width in centimeters."
    )
    parser.add_argument(
        "--height-cm", type=float, default=29.7, help="Poster height in centimeters."
    )
    parser.add_argument(
        "--distance-m",
        type=float,
        default=None,
        help=(
            "Half-width map distance in meters. Defaults to 8000, "
            "or 12000 when --running_page is set."
        ),
    )
    parser.add_argument(
        "--dpi", type=int, default=300, help="Raster export DPI for PNG sizing."
    )
    parser.add_argument(
        "--font-file",
        type=Path,
        help="Optional TTF/OTF file used for PNG text rendering.",
    )
    parser.add_argument(
        "--font-family", help="Font family name written into SVG text nodes."
    )
    parser.add_argument("--cache-dir", type=Path, default=Path(".terraink-cache"))
    parser.add_argument("--overpass-url", default=DEFAULT_OVERPASS_URL)
    parser.add_argument(
        "--nominatim-url", default="https://nominatim.openstreetmap.org"
    )
    parser.add_argument("--user-agent", default="terraink/0.1")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument(
        "--hide-text",
        action="store_true",
        help="Do not draw poster title/subtitle/coords.",
    )
    parser.add_argument(
        "--hide-credits", action="store_true", help="Do not draw footer credits."
    )
    parser.add_argument(
        "--include-buildings", action=argparse.BooleanOptionalAction, default=False
    )
    parser.add_argument(
        "--include-water", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--include-parks", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--include-aeroway", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--include-rail", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--include-roads", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--include-road-path", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--include-road-minor-low", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--include-road-outline", action=argparse.BooleanOptionalAction, default=True
    )
    return parser


def resolve_distance_m(args: argparse.Namespace) -> float:
    if args.distance_m is not None:
        return args.distance_m
    if args.running_page:
        return RUNNING_PAGE_DISTANCE_M
    return DEFAULT_DISTANCE_M


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    request = PosterRequest(
        output=Path(args.output),
        formats=tuple(args.format),
        location=args.location or args.query,
        running_page=args.running_page,
        lat=args.lat,
        lon=args.lon,
        title=args.title,
        subtitle=args.subtitle,
        width_cm=args.width_cm,
        height_cm=args.height_cm,
        distance_m=resolve_distance_m(args),
        dpi=args.dpi,
        theme=args.theme,
        layout=args.layout,
        font_file=args.font_file,
        font_family=args.font_family,
        show_poster_text=not args.hide_text,
        include_credits=not args.hide_credits,
        include_buildings=args.include_buildings,
        include_water=args.include_water,
        include_parks=args.include_parks,
        include_aeroway=args.include_aeroway,
        include_rail=args.include_rail,
        include_roads=args.include_roads,
        include_road_path=args.include_road_path,
        include_road_minor_low=args.include_road_minor_low,
        include_road_outline=args.include_road_outline,
        cache_dir=args.cache_dir,
        overpass_url=args.overpass_url,
        nominatim_url=args.nominatim_url,
        user_agent=args.user_agent,
        timeout_seconds=args.timeout,
    )
    result = generate_poster(request)
    for path in result.files:
        print(path)
    return 0
