from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

OutputFormat = Literal["png", "svg"]
ProgressStage = Literal[
    "preparing_request",
    "resolving_location",
    "computing_bounds",
    "fetching_map_data",
    "building_scene",
    "rendering_output",
    "done",
]
Point = tuple[float, float]
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"


@dataclass(slots=True, frozen=True)
class Bounds:
    south: float
    west: float
    north: float
    east: float


@dataclass(slots=True, frozen=True)
class Coordinate:
    lat: float
    lon: float


@dataclass(slots=True, frozen=True)
class PosterBoundsResult:
    poster_bounds: Bounds
    fetch_bounds: Bounds
    half_meters_x: float
    half_meters_y: float
    fetch_half_meters: float


@dataclass(slots=True, frozen=True)
class CanvasSize:
    width: int
    height: int
    requested_width: int
    requested_height: int
    downscale_factor: float


@dataclass(slots=True, frozen=True)
class ThemeUiColors:
    bg: str
    text: str


@dataclass(slots=True, frozen=True)
class ThemeRoadColors:
    major: str
    minor_high: str
    minor_mid: str
    minor_low: str
    path: str
    outline: str


@dataclass(slots=True, frozen=True)
class ThemeMapColors:
    land: str
    water: str
    waterway: str
    parks: str
    buildings: str
    aeroway: str
    rail: str
    roads: ThemeRoadColors


@dataclass(slots=True, frozen=True)
class Theme:
    id: str
    name: str
    description: str
    ui: ThemeUiColors
    map: ThemeMapColors


@dataclass(slots=True, frozen=True)
class Layout:
    id: str
    name: str
    description: str
    width: float
    height: float
    unit: str
    width_cm: float
    height_cm: float


@dataclass(slots=True, frozen=True)
class LocationMetadata:
    label: str
    lat: float
    lon: float
    city: str
    country: str
    continent: str = ""


@dataclass(slots=True)
class PosterRequest:
    output: Path
    formats: tuple[str, ...] = ("png",)
    location: str | None = None
    lat: float | None = None
    lon: float | None = None
    title: str | None = None
    subtitle: str | None = None
    width_cm: float = 21.0
    height_cm: float = 29.7
    distance_m: float = 12_000.0
    dpi: int = 300
    theme: str = "random"
    layout: str | None = None
    font_file: Path | None = None
    font_family: str | None = None
    show_poster_text: bool = True
    include_credits: bool = True
    include_buildings: bool = False
    include_water: bool = True
    include_parks: bool = True
    include_aeroway: bool = True
    include_rail: bool = True
    include_roads: bool = True
    include_road_path: bool = True
    include_road_minor_low: bool = True
    include_road_outline: bool = True
    user_agent: str = "terraink/0.1"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    overpass_url: str = DEFAULT_OVERPASS_URL
    timeout_seconds: int = 90
    cache_dir: Path | None = Path(".terraink-cache")
    max_pixels: int = 8_500_000
    max_side: int = 4_096

    def __post_init__(self) -> None:
        self.output = Path(self.output)
        self.formats = tuple(str(fmt).lower() for fmt in self.formats)  # type: ignore[assignment]
        if self.font_file is not None:
            self.font_file = Path(self.font_file)
        if self.cache_dir is not None:
            self.cache_dir = Path(self.cache_dir)

    def validate(self) -> None:
        if not self.location and (self.lat is None or self.lon is None):
            raise ValueError("Provide either --location or both --lat and --lon.")
        if self.width_cm <= 0 or self.height_cm <= 0:
            raise ValueError("Poster width and height must be positive.")
        if self.dpi <= 0:
            raise ValueError("DPI must be positive.")
        if self.distance_m < 1_000:
            raise ValueError("distance_m must be at least 1000.")
        if self.distance_m > 250_000:
            raise ValueError(
                "distance_m above 250000 is not supported in the Python renderer."
            )
        invalid_formats = sorted(set(self.formats) - {"png", "svg"})
        if invalid_formats:
            raise ValueError(
                f"Unsupported output format(s): {', '.join(invalid_formats)}"
            )


@dataclass(slots=True, frozen=True)
class ProjectedScene:
    width: int
    height: int
    requested_width: int
    requested_height: int
    downscale_factor: float
    dpi: int
    center: Coordinate
    title: str
    subtitle: str
    theme: Theme
    polygons: dict[str, list[list[Point]]]
    lines: dict[str, list[list[Point]]]
    show_poster_text: bool
    include_credits: bool
    include_road_outline: bool
    font_file: Path | None
    font_family: str | None
    distance_m: float


@dataclass(slots=True, frozen=True)
class PosterResult:
    files: tuple[Path, ...]
    location: LocationMetadata
    theme: Theme
    size: CanvasSize
    bounds: PosterBoundsResult


@dataclass(slots=True, frozen=True)
class PosterProgress:
    stage: ProgressStage
    percent: int
    message: str


ProgressCallback = Callable[[PosterProgress], None]
