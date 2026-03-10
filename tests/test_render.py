from __future__ import annotations

from pathlib import Path

from PIL import Image

from terraink_py.data import get_theme
from terraink_py.geo import MercatorProjector
from terraink_py.models import Bounds, CanvasSize, Coordinate, PosterRequest
from terraink_py.render import (
    RUNNING_ROUTE_COLOR,
    apply_png_fades,
    build_scene,
    draw_dashed_polyline,
    hex_to_rgba,
    path_intersects_bounds,
    render_svg,
    resolve_font,
    simplify_polygon,
    _resolve_font_cached,
)


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


class TestPathIntersectsBounds:
    """Tests for #1: single-pass bounding box check."""

    def test_path_inside_bounds(self) -> None:
        bounds = Bounds(south=-1.0, west=-1.0, north=1.0, east=1.0)
        path = [(0.0, 0.0), (0.5, 0.5)]
        assert path_intersects_bounds(path, bounds) is True

    def test_path_outside_bounds(self) -> None:
        bounds = Bounds(south=-1.0, west=-1.0, north=1.0, east=1.0)
        path = [(5.0, 5.0), (6.0, 6.0)]
        assert path_intersects_bounds(path, bounds) is False

    def test_path_partially_overlapping(self) -> None:
        bounds = Bounds(south=-1.0, west=-1.0, north=1.0, east=1.0)
        path = [(0.5, 0.5), (2.0, 2.0)]
        assert path_intersects_bounds(path, bounds) is True

    def test_path_touching_boundary_edge(self) -> None:
        bounds = Bounds(south=-1.0, west=-1.0, north=1.0, east=1.0)
        path = [(1.0, 0.0), (2.0, 0.0)]
        assert path_intersects_bounds(path, bounds) is True

    def test_path_just_outside_west(self) -> None:
        bounds = Bounds(south=-1.0, west=-1.0, north=1.0, east=1.0)
        path = [(-3.0, 0.0), (-2.0, 0.0)]
        assert path_intersects_bounds(path, bounds) is False

    def test_single_point_inside(self) -> None:
        bounds = Bounds(south=-1.0, west=-1.0, north=1.0, east=1.0)
        path = [(0.0, 0.0)]
        assert path_intersects_bounds(path, bounds) is True

    def test_single_point_outside(self) -> None:
        bounds = Bounds(south=-1.0, west=-1.0, north=1.0, east=1.0)
        path = [(5.0, 5.0)]
        assert path_intersects_bounds(path, bounds) is False


class TestResolveFontCache:
    """Tests for #2: resolve_font uses lru_cache."""

    def test_returns_font_object(self) -> None:
        font = resolve_font(None, 24, bold=False)
        assert font is not None

    def test_cache_hit_returns_same_object(self) -> None:
        _resolve_font_cached.cache_clear()
        font_a = resolve_font(None, 24, bold=True, text="hello")
        font_b = resolve_font(None, 24, bold=True, text="world")
        # Both are non-CJK, same params → should be the exact same cached object
        assert font_a is font_b

    def test_cjk_text_gets_different_font(self) -> None:
        _resolve_font_cached.cache_clear()
        _font_latin = resolve_font(None, 24, bold=False, text="hello")
        _font_cjk = resolve_font(None, 24, bold=False, text="你好")
        # They may differ (if CJK font available) or not, but cache keys differ
        info = _resolve_font_cached.cache_info()
        assert info.misses >= 2

    def test_minimum_size_enforced(self) -> None:
        font = resolve_font(None, 5, bold=False)
        assert font is not None


class TestSimplifyPolygonRDP:
    """Tests for #3: simplify_polygon uses Douglas-Peucker."""

    def test_triangle_unchanged(self) -> None:
        # A simple triangle with closing point should be preserved
        triangle = [(0.0, 0.0), (10.0, 0.0), (5.0, 10.0), (0.0, 0.0)]
        result = simplify_polygon(triangle, tolerance=0.5)
        assert len(result) == 4
        assert result[0] == result[-1]

    def test_collinear_points_removed(self) -> None:
        # Square with extra collinear points on edges
        square = [
            (0.0, 0.0),
            (5.0, 0.0),
            (10.0, 0.0),
            (10.0, 5.0),
            (10.0, 10.0),
            (5.0, 10.0),
            (0.0, 10.0),
            (0.0, 5.0),
            (0.0, 0.0),
        ]
        result = simplify_polygon(square, tolerance=0.5)
        # DPP removes most collinear midpoints; at most one may be kept as split point
        assert len(result) < len(square)
        assert result[0] == result[-1]

    def test_preserves_significant_vertices(self) -> None:
        # Create a shape where all vertices are significant
        points = [
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (5.0, 5.0),  # concavity — significant
            (0.0, 10.0),
            (0.0, 0.0),
        ]
        result = simplify_polygon(points, tolerance=0.5)
        assert len(result) >= 5  # concavity should be preserved
        assert result[0] == result[-1]

    def test_zero_tolerance_keeps_all(self) -> None:
        points = [
            (0.0, 0.0),
            (5.0, 0.1),
            (10.0, 0.0),
            (5.0, 10.0),
            (0.0, 0.0),
        ]
        result = simplify_polygon(points, tolerance=0)
        # Zero tolerance → all unique points + closing
        assert len(result) == 5

    def test_too_few_points_returns_empty(self) -> None:
        result = simplify_polygon([(0.0, 0.0), (1.0, 1.0)], tolerance=0.5)
        assert result == [] or len(result) < 4

    def test_result_is_closed_ring(self) -> None:
        hex_shape = [
            (5.0, 0.0),
            (10.0, 2.5),
            (10.0, 7.5),
            (5.0, 10.0),
            (0.0, 7.5),
            (0.0, 2.5),
            (5.0, 0.0),
        ]
        result = simplify_polygon(hex_shape, tolerance=0.3)
        assert len(result) >= 4
        assert result[0] == result[-1]


class TestApplyPngFades:
    """Tests for #4: apply_png_fades uses NumPy vectorization."""

    def test_top_left_pixel_is_opaque_overlay(self) -> None:
        img = Image.new("RGBA", (10, 100), (255, 0, 0, 255))
        apply_png_fades(img, "#00FF00")
        px = img.getpixel((0, 0))
        assert isinstance(px, tuple)
        r, g, b, a = px
        # Top pixel should have green overlay blended in
        assert g > 0

    def test_middle_pixels_unchanged(self) -> None:
        img = Image.new("RGBA", (10, 100), (255, 0, 0, 255))
        original_pixel = img.getpixel((5, 50))
        apply_png_fades(img, "#00FF00")
        middle_pixel = img.getpixel((5, 50))
        # Middle pixels (25%-75%) should have zero alpha overlay → unchanged
        assert middle_pixel == original_pixel

    def test_bottom_pixels_have_overlay(self) -> None:
        img = Image.new("RGBA", (10, 100), (255, 0, 0, 255))
        apply_png_fades(img, "#00FF00")
        px = img.getpixel((5, 99))
        assert isinstance(px, tuple)
        r, g, b, a = px
        # Bottom pixel should have green overlay blended in
        assert g > 0

    def test_does_not_crash_on_small_image(self) -> None:
        img = Image.new("RGBA", (2, 4), (128, 128, 128, 255))
        apply_png_fades(img, "#000000")
        assert img.size == (2, 4)


class TestHexToRgbaCache:
    """Tests for #5: hex_to_rgba uses lru_cache."""

    def test_basic_parsing(self) -> None:
        assert hex_to_rgba("#FF0000") == (255, 0, 0, 255)
        assert hex_to_rgba("#00ff00") == (0, 255, 0, 255)
        assert hex_to_rgba("#0000FF", 128) == (0, 0, 255, 128)

    def test_shorthand_hex(self) -> None:
        assert hex_to_rgba("#abc") == (170, 187, 204, 255)

    def test_invalid_returns_black(self) -> None:
        assert hex_to_rgba("xyz") == (0, 0, 0, 255)

    def test_cache_returns_same_result(self) -> None:
        hex_to_rgba.cache_clear()
        result_a = hex_to_rgba("#123456")
        result_b = hex_to_rgba("#123456")
        assert result_a == result_b
        info = hex_to_rgba.cache_info()
        assert info.hits >= 1

    def test_different_alpha_cached_separately(self) -> None:
        hex_to_rgba.cache_clear()
        a = hex_to_rgba("#FF0000", 255)
        b = hex_to_rgba("#FF0000", 128)
        assert a != b
        assert a[3] == 255
        assert b[3] == 128


class TestDrawDashedPolyline:
    """Tests for #6: draw_dashed_polyline batches segments."""

    def test_draws_dashes(self) -> None:
        img = Image.new("RGBA", (100, 10), (0, 0, 0, 255))
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img, "RGBA")
        points = [(0.0, 5.0), (100.0, 5.0)]
        draw_dashed_polyline(
            draw, points, fill=(255, 255, 255, 255), width=2.0, dash=10.0, gap=5.0
        )
        # Check some pixels along the line — some should be white (dash), some black (gap)
        white_count = sum(
            1
            for x in range(100)
            if (isinstance((px := img.getpixel((x, 5))), tuple) and px[0] > 200)
        )
        black_count = sum(
            1
            for x in range(100)
            if (isinstance((px := img.getpixel((x, 5))), tuple) and px[0] < 50)
        )
        assert white_count > 0
        assert black_count > 0

    def test_too_few_points_no_crash(self) -> None:
        img = Image.new("RGBA", (10, 10), (0, 0, 0, 255))
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img, "RGBA")
        draw_dashed_polyline(
            draw, [(5.0, 5.0)], fill=(255, 255, 255, 255), width=1.0, dash=3.0, gap=2.0
        )

    def test_zero_length_segment(self) -> None:
        img = Image.new("RGBA", (10, 10), (0, 0, 0, 255))
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img, "RGBA")
        draw_dashed_polyline(
            draw,
            [(5.0, 5.0), (5.0, 5.0)],
            fill=(255, 255, 255, 255),
            width=1.0,
            dash=3.0,
            gap=2.0,
        )


class TestRunningRouteRendering:
    def test_render_svg_draws_running_route_overlay(self) -> None:
        poster_bounds = Bounds(south=-1.0, west=-1.0, north=1.0, east=1.0)
        theme = get_theme("midnight_blue")
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
            theme=theme,
            layers={
                "running_route": [[(-0.5, -0.5), (0.0, 0.0), (0.5, 0.5)]],
            },
            projector=MercatorProjector.from_bounds(poster_bounds, 200, 200),
            poster_bounds=poster_bounds,
            request=PosterRequest(
                output=Path("test.png"),
                lat=0.0,
                lon=0.0,
                show_poster_text=False,
            ),
        )

        svg = render_svg(scene)
        assert f'stroke="{theme.map.land}"' in svg
        assert f'stroke="{RUNNING_ROUTE_COLOR}"' in svg
