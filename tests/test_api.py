from __future__ import annotations

from pathlib import Path

from terraink_py.api import generate_poster
from terraink_py.models import (
    Bounds,
    CanvasSize,
    LocationMetadata,
    PosterBoundsResult,
    PosterProgress,
    PosterRequest,
)


class FakeProjector:
    @classmethod
    def from_bounds(cls, bounds: Bounds, width: int, height: int) -> "FakeProjector":
        del bounds, width, height
        return cls()


def test_generate_poster_reports_progress(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "terraink_py.api.resolve_location",
        lambda request, client: LocationMetadata(
            label="Shanghai",
            lat=31.2304,
            lon=121.4737,
            city="Shanghai",
            country="China",
        ),
    )
    monkeypatch.setattr(
        "terraink_py.api.resolve_canvas_size",
        lambda *args, **kwargs: CanvasSize(
            width=100,
            height=140,
            requested_width=100,
            requested_height=140,
            downscale_factor=1.0,
        ),
    )
    monkeypatch.setattr(
        "terraink_py.api.compute_poster_and_fetch_bounds",
        lambda **kwargs: PosterBoundsResult(
            poster_bounds=Bounds(south=0.0, west=0.0, north=1.0, east=1.0),
            fetch_bounds=Bounds(south=0.0, west=0.0, north=1.0, east=1.0),
            half_meters_x=1000.0,
            half_meters_y=1000.0,
            fetch_half_meters=1000.0,
        ),
    )

    def fake_fetch_osm_layers(bounds, request, client, progress_callback=None):
        del bounds, request, client
        if progress_callback is not None:
            progress_callback(35, "Fetching OpenStreetMap data")
            progress_callback(45, "Parsing OpenStreetMap features")
            progress_callback(55, "Map data ready")
        return {}

    monkeypatch.setattr("terraink_py.api.fetch_osm_layers", fake_fetch_osm_layers)
    monkeypatch.setattr("terraink_py.api.MercatorProjector", FakeProjector)
    monkeypatch.setattr("terraink_py.api.get_theme", lambda theme_id: {"id": theme_id})
    monkeypatch.setattr(
        "terraink_py.api.build_scene",
        lambda **kwargs: {"scene": kwargs["title"]},
    )
    monkeypatch.setattr(
        "terraink_py.api.render_png",
        lambda scene, output_path: output_path.write_bytes(b"png"),
    )
    monkeypatch.setattr("terraink_py.api.render_svg", lambda scene: "<svg />")

    updates: list[PosterProgress] = []
    result = generate_poster(
        PosterRequest(
            output=tmp_path / "poster",
            formats=("png", "svg"),
            location="Shanghai",
        ),
        progress_callback=updates.append,
    )

    assert [update.stage for update in updates] == [
        "preparing_request",
        "resolving_location",
        "computing_bounds",
        "fetching_map_data",
        "fetching_map_data",
        "fetching_map_data",
        "building_scene",
        "rendering_output",
        "rendering_output",
        "done",
    ]
    assert [update.percent for update in updates] == [
        5,
        15,
        25,
        35,
        45,
        55,
        75,
        85,
        90,
        100,
    ]
    assert result.files == (tmp_path / "poster.png", tmp_path / "poster.svg")
    assert result.files[0].read_bytes() == b"png"
    assert result.files[1].read_text(encoding="utf-8") == "<svg />"
