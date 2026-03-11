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
from .models import (
    Coordinate,
    PosterProgress,
    PosterRequest,
    PosterResult,
    ProgressCallback,
    ProgressStage,
)
from .osm import fetch_osm_layers, resolve_location
from .render import build_scene, render_png, render_svg
from .running_page import RUNNING_ROUTE_LAYER, load_running_page_routes


class PosterGenerator:
    def generate(
        self,
        request: PosterRequest,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> PosterResult:
        reporter = _ProgressReporter(progress_callback)
        reporter.emit("preparing_request", 5, "Preparing poster request")
        prepared = prepare_request(request)
        prepared.validate()

        client = CachedHttpClient(
            cache_dir=prepared.cache_dir,
            user_agent=prepared.user_agent,
            timeout_seconds=prepared.timeout_seconds,
        )
        reporter.emit("resolving_location", 15, "Resolving location")
        location = resolve_location(prepared, client)
        center = Coordinate(lat=location.lat, lon=location.lon)
        size = resolve_canvas_size(
            prepared.width_cm / CM_PER_INCH,
            prepared.height_cm / CM_PER_INCH,
            dpi=prepared.dpi,
            max_pixels=prepared.max_pixels,
            max_side=prepared.max_side,
        )
        reporter.emit("computing_bounds", 25, "Computing poster bounds")
        bounds = compute_poster_and_fetch_bounds(
            center=center,
            distance_meters=prepared.distance_m,
            aspect_ratio=prepared.width_cm / prepared.height_cm,
        )
        layers = fetch_osm_layers(
            bounds.fetch_bounds,
            prepared,
            client,
            progress_callback=lambda percent, message: reporter.emit(
                "fetching_map_data", percent, message
            ),
        )
        running_routes = load_running_page_routes(prepared)
        if running_routes:
            layers[RUNNING_ROUTE_LAYER] = running_routes
        projector = MercatorProjector.from_bounds(
            bounds.poster_bounds, size.width, size.height
        )
        theme = get_theme(prepared.theme)
        reporter.emit("building_scene", 75, "Projecting map geometry")
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
        total_outputs = max(len(output_paths), 1)
        for index, (fmt, path) in enumerate(output_paths.items(), start=1):
            reporter.emit(
                "rendering_output",
                85 + int(((index - 1) * 10) / total_outputs),
                f"Rendering {fmt.upper()} output",
            )
            if fmt == "png":
                render_png(scene, path)
            elif fmt == "svg":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_svg(scene), encoding="utf-8")
            files.append(path)
        result = PosterResult(
            files=tuple(files),
            location=location,
            theme=theme,
            size=size,
            bounds=bounds,
        )
        reporter.emit("done", 100, "Poster ready")
        return result


class _ProgressReporter:
    def __init__(self, callback: ProgressCallback | None) -> None:
        self._callback = callback
        self._last_event: tuple[ProgressStage, int, str] | None = None

    def emit(self, stage: ProgressStage, percent: int, message: str) -> None:
        if self._callback is None:
            return
        clamped = max(0, min(100, percent))
        event = (stage, clamped, message)
        if event == self._last_event:
            return
        self._last_event = event
        self._callback(PosterProgress(stage=stage, percent=clamped, message=message))


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


def generate_poster(
    request: PosterRequest,
    *,
    progress_callback: ProgressCallback | None = None,
) -> PosterResult:
    return PosterGenerator().generate(request, progress_callback=progress_callback)
