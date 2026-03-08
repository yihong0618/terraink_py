from __future__ import annotations

from pathlib import Path

from terraink_py.data import get_theme
from terraink_py.geo import MercatorProjector
from terraink_py.models import Bounds, CanvasSize, Coordinate, PosterRequest
from terraink_py.render import build_scene


class TestBuildSceneOptimization:
    def test_drops_line_fully_outside_poster_bounds(self) -> None:
        poster_bounds = Bounds(south=-1.0, west=-1.0, north=1.0, east=1.0)
        scene = build_scene(
            size=CanvasSize(
                width=200,
                height=200,
                requested_width=200,
                requested_height=200,
                downscale_factor=1.0,
            ),
            center=Coordinate(lat=0.0, lon=0.0),
            title="Center",
            subtitle="Earth",
            theme=get_theme("midnight_blue"),
            layers={
                "road_major": [[(5.0, 5.0), (6.0, 6.0)]],
            },
            projector=MercatorProjector.from_bounds(poster_bounds, 200, 200),
            poster_bounds=poster_bounds,
            request=PosterRequest(output=Path("test.png"), lat=0.0, lon=0.0),
        )

        assert scene.lines["road_major"] == []

    def test_clips_and_simplifies_dense_line_to_viewport(self) -> None:
        poster_bounds = Bounds(south=-1.0, west=-1.0, north=1.0, east=1.0)
        source_path = [
            (-2.0, 0.0),
            (-1.0, 0.0),
            (-0.5, 0.0),
            (-0.25, 0.0),
            (0.0, 0.0),
            (0.25, 0.0),
            (0.5, 0.0),
            (1.0, 0.0),
            (2.0, 0.0),
        ]
        scene = build_scene(
            size=CanvasSize(
                width=200,
                height=200,
                requested_width=200,
                requested_height=200,
                downscale_factor=1.0,
            ),
            center=Coordinate(lat=0.0, lon=0.0),
            title="Center",
            subtitle="Earth",
            theme=get_theme("midnight_blue"),
            layers={
                "road_major": [source_path],
            },
            projector=MercatorProjector.from_bounds(poster_bounds, 200, 200),
            poster_bounds=poster_bounds,
            request=PosterRequest(output=Path("test.png"), lat=0.0, lon=0.0),
        )

        projected_paths = scene.lines["road_major"]
        assert len(projected_paths) == 1
        assert len(projected_paths[0]) == 2
        assert all(-24.0 <= x <= 224.0 for x, _ in projected_paths[0])

    def test_clips_polygon_and_keeps_closed_ring(self) -> None:
        poster_bounds = Bounds(south=-1.0, west=-1.0, north=1.0, east=1.0)
        scene = build_scene(
            size=CanvasSize(
                width=200,
                height=200,
                requested_width=200,
                requested_height=200,
                downscale_factor=1.0,
            ),
            center=Coordinate(lat=0.0, lon=0.0),
            title="Center",
            subtitle="Earth",
            theme=get_theme("midnight_blue"),
            layers={
                "parks": [
                    [(-2.0, -2.0), (2.0, -2.0), (2.0, 2.0), (-2.0, 2.0), (-2.0, -2.0)]
                ],
            },
            projector=MercatorProjector.from_bounds(poster_bounds, 200, 200),
            poster_bounds=poster_bounds,
            request=PosterRequest(output=Path("test.png"), lat=0.0, lon=0.0),
        )

        polygons = scene.polygons["parks"]
        assert len(polygons) == 1
        assert polygons[0][0] == polygons[0][-1]
        assert len(polygons[0]) >= 4

    def test_preserves_closed_line_geometry(self) -> None:
        poster_bounds = Bounds(south=-1.0, west=-1.0, north=1.0, east=1.0)
        scene = build_scene(
            size=CanvasSize(
                width=200,
                height=200,
                requested_width=200,
                requested_height=200,
                downscale_factor=1.0,
            ),
            center=Coordinate(lat=0.0, lon=0.0),
            title="Center",
            subtitle="Earth",
            theme=get_theme("midnight_blue"),
            layers={
                "road_major": [
                    [(-0.2, 0.0), (0.0, 0.2), (0.2, 0.0), (0.0, -0.2), (-0.2, 0.0)]
                ],
            },
            projector=MercatorProjector.from_bounds(poster_bounds, 200, 200),
            poster_bounds=poster_bounds,
            request=PosterRequest(output=Path("test.png"), lat=0.0, lon=0.0),
        )

        projected_paths = scene.lines["road_major"]
        assert len(projected_paths) == 1
        assert projected_paths[0][0] == projected_paths[0][-1]
