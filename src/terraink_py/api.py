from __future__ import annotations

from pathlib import Path

from .data import get_layout, get_theme
from .geo import (
    CM_PER_INCH,
    MercatorProjector,
    compute_poster_and_fetch_bounds,
    resolve_canvas_size,
)
from .http import CachedHttpClient
from .models import Coordinate, PosterRequest, PosterResult
from .osm import fetch_osm_layers, resolve_location
from .render import build_scene, render_png, render_svg
from .running_page import RUNNING_ROUTE_LAYER, load_running_page_routes


class PosterGenerator:
    def generate(self, request: PosterRequest) -> PosterResult:
        prepared = prepare_request(request)
        prepared.validate()

        client = CachedHttpClient(
            cache_dir=prepared.cache_dir,
            user_agent=prepared.user_agent,
            timeout_seconds=prepared.timeout_seconds,
        )
        location = resolve_location(prepared, client)
        center = Coordinate(lat=location.lat, lon=location.lon)
        size = resolve_canvas_size(
            prepared.width_cm / CM_PER_INCH,
            prepared.height_cm / CM_PER_INCH,
            dpi=prepared.dpi,
            max_pixels=prepared.max_pixels,
            max_side=prepared.max_side,
        )
        bounds = compute_poster_and_fetch_bounds(
            center=center,
            distance_meters=prepared.distance_m,
            aspect_ratio=prepared.width_cm / prepared.height_cm,
        )
        layers = fetch_osm_layers(bounds.fetch_bounds, prepared, client)
        running_routes = load_running_page_routes(prepared, location)
        if running_routes:
            layers[RUNNING_ROUTE_LAYER] = running_routes
        projector = MercatorProjector.from_bounds(
            bounds.poster_bounds, size.width, size.height
        )
        theme = get_theme(prepared.theme)
        scene = build_scene(
            size=size,
            center=center,
            title=(prepared.title or location.city or location.label).strip(),
            subtitle=(prepared.subtitle or location.country).strip(),
            theme=theme,
            layers=layers,
            projector=projector,
            poster_bounds=bounds.poster_bounds,
            request=prepared,
        )
        output_paths = resolve_output_paths(prepared.output, prepared.formats)
        files: list[Path] = []
        for fmt, path in output_paths.items():
            if fmt == "png":
                render_png(scene, path)
            elif fmt == "svg":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_svg(scene), encoding="utf-8")
            files.append(path)
        return PosterResult(
            files=tuple(files),
            location=location,
            theme=theme,
            size=size,
            bounds=bounds,
        )


def prepare_request(request: PosterRequest) -> PosterRequest:
    if request.layout:
        layout = get_layout(request.layout)
        request.width_cm = layout.width_cm
        request.height_cm = layout.height_cm
    return request


def resolve_output_paths(output: Path, formats: tuple[str, ...]) -> dict[str, Path]:
    output = Path(output)
    if len(formats) == 1 and output.suffix.lower() == f".{formats[0]}":
        return {formats[0]: output}

    base = output.with_suffix("") if output.suffix else output
    return {fmt: base.with_suffix(f".{fmt}") for fmt in formats}


def generate_poster(request: PosterRequest) -> PosterResult:
    return PosterGenerator().generate(request)
