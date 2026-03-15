from __future__ import annotations

from pathlib import Path

import pytest

from terraink_py.models import (
    Bounds,
    CanvasSize,
    Coordinate,
    PosterBoundsResult,
    PosterRequest,
    Theme,
    ThemeMapColors,
    ThemeRoadColors,
    ThemeUiColors,
)


class TestBounds:
    def test_bounds_creation(self) -> None:
        bounds = Bounds(south=10.0, west=20.0, north=30.0, east=40.0)
        assert bounds.south == 10.0
        assert bounds.west == 20.0
        assert bounds.north == 30.0
        assert bounds.east == 40.0

    def test_bounds_is_frozen(self) -> None:
        bounds = Bounds(south=10.0, west=20.0, north=30.0, east=40.0)
        with pytest.raises(AttributeError):
            bounds.south = 15.0  # type: ignore[misc]


class TestCoordinate:
    def test_coordinate_creation(self) -> None:
        coord = Coordinate(lat=39.9042, lon=116.4074)
        assert coord.lat == 39.9042
        assert coord.lon == 116.4074


class TestPosterBoundsResult:
    def test_poster_bounds_result_creation(self) -> None:
        poster_bounds = Bounds(south=10.0, west=20.0, north=30.0, east=40.0)
        fetch_bounds = Bounds(south=5.0, west=15.0, north=35.0, east=45.0)
        result = PosterBoundsResult(
            poster_bounds=poster_bounds,
            fetch_bounds=fetch_bounds,
            half_meters_x=5000.0,
            half_meters_y=3000.0,
            fetch_half_meters=8000.0,
        )
        assert result.poster_bounds == poster_bounds
        assert result.fetch_bounds == fetch_bounds
        assert result.half_meters_x == 5000.0
        assert result.half_meters_y == 3000.0
        assert result.fetch_half_meters == 8000.0


class TestCanvasSize:
    def test_canvas_size_creation(self) -> None:
        size = CanvasSize(
            width=1920,
            height=1080,
            requested_width=1920,
            requested_height=1080,
            downscale_factor=1.0,
        )
        assert size.width == 1920
        assert size.height == 1080
        assert size.requested_width == 1920
        assert size.requested_height == 1080
        assert size.downscale_factor == 1.0


class TestTheme:
    def test_theme_creation(self) -> None:
        theme = Theme(
            id="test_theme",
            name="Test Theme",
            description="A test theme",
            ui=ThemeUiColors(bg="#000000", text="#FFFFFF"),
            map=ThemeMapColors(
                land="#111111",
                water="#222222",
                waterway="#333333",
                parks="#444444",
                buildings="#555555",
                aeroway="#666666",
                rail="#777777",
                roads=ThemeRoadColors(
                    major="#888888",
                    minor_high="#999999",
                    minor_mid="#AAAAAA",
                    minor_low="#BBBBBB",
                    path="#CCCCCC",
                    outline="#DDDDDD",
                ),
            ),
        )
        assert theme.id == "test_theme"
        assert theme.name == "Test Theme"
        assert theme.ui.bg == "#000000"
        assert theme.map.roads.major == "#888888"


class TestPosterRequest:
    def test_poster_request_creation(self) -> None:
        request = PosterRequest(
            output=Path("output.png"),
            lat=39.9042,
            lon=116.4074,
            title="Beijing",
            subtitle="China",
        )
        assert request.output == Path("output.png")
        assert request.lat == 39.9042
        assert request.lon == 116.4074
        assert request.title == "Beijing"
        assert request.subtitle == "China"

    def test_poster_request_defaults(self) -> None:
        request = PosterRequest(output=Path("output.png"), lat=39.9042, lon=116.4074)
        assert request.formats == ("png",)
        assert request.language == "auto"
        assert request.width_cm == 21.0
        assert request.height_cm == 29.7
        assert request.dpi == 300
        assert request.theme == "random"
        assert request.distance_m == 12_000.0
        assert request.running_page is None

    def test_poster_request_post_init(self) -> None:
        request = PosterRequest(
            output="output.png",  # type: ignore[arg-type]
            lat=39.9042,
            lon=116.4074,
            formats=["PNG", "SVG"],  # type: ignore[arg-type]
        )
        assert isinstance(request.output, Path)
        assert request.formats == ("png", "svg")

    def test_validate_with_location(self) -> None:
        request = PosterRequest(
            output=Path("output.png"),
            location="Beijing",
        )
        request.validate()  # Should not raise

    def test_validate_with_coords(self) -> None:
        request = PosterRequest(
            output=Path("output.png"),
            lat=39.9042,
            lon=116.4074,
        )
        request.validate()  # Should not raise

    def test_validate_missing_location_and_coords(self) -> None:
        request = PosterRequest(output=Path("output.png"))
        with pytest.raises(ValueError, match="Provide either --location"):
            request.validate()

    def test_validate_invalid_dimensions(self) -> None:
        request = PosterRequest(
            output=Path("output.png"),
            lat=39.9042,
            lon=116.4074,
            width_cm=-1,
        )
        with pytest.raises(ValueError, match="width and height must be positive"):
            request.validate()

    def test_validate_invalid_dpi(self) -> None:
        request = PosterRequest(
            output=Path("output.png"),
            lat=39.9042,
            lon=116.4074,
            dpi=0,
        )
        with pytest.raises(ValueError, match="DPI must be positive"):
            request.validate()

    def test_validate_distance_too_small(self) -> None:
        request = PosterRequest(
            output=Path("output.png"),
            lat=39.9042,
            lon=116.4074,
            distance_m=500,
        )
        with pytest.raises(ValueError, match="at least 1000"):
            request.validate()

    def test_validate_distance_too_large(self) -> None:
        request = PosterRequest(
            output=Path("output.png"),
            lat=39.9042,
            lon=116.4074,
            distance_m=300_000,
        )
        with pytest.raises(ValueError, match="above 250000 is not supported"):
            request.validate()

    def test_validate_invalid_format(self) -> None:
        request = PosterRequest(
            output=Path("output.png"),
            lat=39.9042,
            lon=116.4074,
            formats=("pdf",),  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="Unsupported output format"):
            request.validate()

    def test_validate_invalid_language(self) -> None:
        request = PosterRequest(
            output=Path("output.png"),
            lat=39.9042,
            lon=116.4074,
            language="jp",  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="language must be one of"):
            request.validate()
