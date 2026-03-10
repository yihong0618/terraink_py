from __future__ import annotations

import heapq
import math
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import ImageFont

from .geo import MercatorProjector, format_coordinates
from .models import (
    Bounds,
    CanvasSize,
    Coordinate,
    Point,
    PosterRequest,
    ProjectedScene,
    Theme,
)
from .text import (
    ATTRIBUTION_FONT_BASE_PX,
    CITY_FONT_BASE_PX,
    CITY_FONT_MIN_PX,
    CITY_TEXT_SHRINK_THRESHOLD,
    COORDS_FONT_BASE_PX,
    COUNTRY_FONT_BASE_PX,
    CREATOR_CREDIT,
    DEFAULT_FONT_FAMILY,
    DEFAULT_MONO_FAMILY,
    TEXT_CITY_Y_RATIO,
    TEXT_COORDS_Y_RATIO,
    TEXT_COUNTRY_Y_RATIO,
    TEXT_DIMENSION_REFERENCE_PX,
    TEXT_DIVIDER_Y_RATIO,
    TEXT_EDGE_MARGIN_RATIO,
    contains_cjk,
    format_city_label,
)

LayerMap = dict[str, list[list[tuple[float, float]]]]

# Mirrors the working font-discovery idea from tg_bot_collections so CJK place
# names render without tofu on macOS/Linux even when the user provides no font.
CJK_FONT_CANDIDATES_REGULAR = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSerifCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
CJK_FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSerifCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
DEFAULT_SVG_FONT_STACK = [
    DEFAULT_FONT_FAMILY,
    "Arial",
    "Helvetica Neue",
    "sans-serif",
]
DEFAULT_SVG_MONO_STACK = [
    DEFAULT_MONO_FAMILY,
    "Menlo",
    "SFMono-Regular",
    "monospace",
]
CJK_SVG_FONT_STACK = [
    "Hiragino Sans GB",
    "PingFang SC",
    "STHeiti",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "Arial Unicode MS",
    "sans-serif",
]
EARTH_CIRCUMFERENCE_M = 40_075_016.686
TILE_SIZE_PX = 512.0
MIN_MAP_ZOOM = 0.5
MAX_MAP_ZOOM = 20.0
CLIP_PADDING_PX = 24.0
POINT_EQUALITY_EPSILON = 1e-6
POLYGON_SIMPLIFY_TOLERANCE_PX = {
    "water": 0.7,
    "parks": 0.85,
    "buildings": 0.45,
    "aeroway": 0.75,
}
LINE_SIMPLIFY_TOLERANCE_PX = {
    "waterway": 0.6,
    "rail": 0.7,
    "road_major": 0.55,
    "road_minor_high": 0.75,
    "road_minor_mid": 0.9,
    "road_minor_low": 1.0,
    "road_path": 1.1,
    "running_route": 0.4,
}
RUNNING_ROUTE_COLOR = "#D7EF57"


def build_scene(
    *,
    size: CanvasSize,
    center: Coordinate,
    title: str,
    subtitle: str,
    theme: Theme,
    layers: LayerMap,
    projector: MercatorProjector,
    poster_bounds: Bounds,
    request: PosterRequest,
) -> ProjectedScene:
    clip_rect = (
        -CLIP_PADDING_PX,
        -CLIP_PADDING_PX,
        size.width + CLIP_PADDING_PX,
        size.height + CLIP_PADDING_PX,
    )
    polygons = {
        name: [
            projected
            for path in paths
            if len(path) >= 4
            for projected in (
                project_polygon_path(
                    projector,
                    path,
                    poster_bounds=poster_bounds,
                    clip_rect=clip_rect,
                    tolerance=POLYGON_SIMPLIFY_TOLERANCE_PX.get(name, 0.75),
                ),
            )
            if projected
        ]
        for name, paths in layers.items()
        if name in {"water", "parks", "buildings", "aeroway"}
    }
    lines = {
        name: [
            projected
            for path in paths
            if len(path) >= 2
            for projected in project_line_paths(
                projector,
                path,
                poster_bounds=poster_bounds,
                clip_rect=clip_rect,
                tolerance=LINE_SIMPLIFY_TOLERANCE_PX.get(name, 0.75),
            )
            if len(projected) >= 2
        ]
        for name, paths in layers.items()
        if name not in {"water", "parks", "buildings", "aeroway"}
    }
    return ProjectedScene(
        width=size.width,
        height=size.height,
        requested_width=size.requested_width,
        requested_height=size.requested_height,
        downscale_factor=size.downscale_factor,
        dpi=request.dpi,
        center=center,
        title=title,
        subtitle=subtitle,
        theme=theme,
        polygons=polygons,
        lines=lines,
        show_poster_text=request.show_poster_text,
        include_credits=request.include_credits,
        include_road_outline=request.include_road_outline,
        font_file=request.font_file,
        font_family=request.font_family,
        distance_m=request.distance_m,
    )


def project_path(
    projector: MercatorProjector, path: list[tuple[float, float]]
) -> list[Point]:
    return [projector.project(lon, lat) for lon, lat in path]


def project_polygon_path(
    projector: MercatorProjector,
    path: list[tuple[float, float]],
    *,
    poster_bounds: Bounds,
    clip_rect: tuple[float, float, float, float],
    tolerance: float,
) -> list[Point]:
    if not path_intersects_bounds(path, poster_bounds):
        return []
    projected = project_path(projector, path)
    clipped = clip_polygon_to_rect(projected, clip_rect)
    if len(clipped) < 4:
        return []
    simplified = simplify_polygon(clipped, tolerance)
    if len(simplified) < 4:
        return []
    return simplified


def project_line_paths(
    projector: MercatorProjector,
    path: list[tuple[float, float]],
    *,
    poster_bounds: Bounds,
    clip_rect: tuple[float, float, float, float],
    tolerance: float,
) -> list[list[Point]]:
    if not path_intersects_bounds(path, poster_bounds):
        return []
    projected = project_path(projector, path)
    clipped_paths = clip_polyline_to_rect(projected, clip_rect)
    return [
        simplified
        for clipped in clipped_paths
        for simplified in (simplify_polyline(clipped, tolerance),)
        if len(simplified) >= 2
    ]


def path_intersects_bounds(path: list[tuple[float, float]], bounds: Bounds) -> bool:
    min_lon = min_lat = float("inf")
    max_lon = max_lat = float("-inf")
    for lon, lat in path:
        if lon < min_lon:
            min_lon = lon
        if lon > max_lon:
            max_lon = lon
        if lat < min_lat:
            min_lat = lat
        if lat > max_lat:
            max_lat = lat
    return not (
        max_lon < bounds.west
        or min_lon > bounds.east
        or max_lat < bounds.south
        or min_lat > bounds.north
    )


def clip_polyline_to_rect(
    points: list[Point], rect: tuple[float, float, float, float]
) -> list[list[Point]]:
    if len(points) < 2:
        return []

    clipped_paths: list[list[Point]] = []
    current: list[Point] = []
    for start, end in zip(points, points[1:]):
        clipped = clip_segment_to_rect(start, end, rect)
        if clipped is None:
            if len(current) >= 2:
                deduped = dedupe_consecutive_points(current)
                if len(deduped) >= 2:
                    clipped_paths.append(deduped)
            current = []
            continue

        clipped_start, clipped_end = clipped
        if not current:
            current = [clipped_start, clipped_end]
            continue

        if points_are_close(current[-1], clipped_start):
            if not points_are_close(current[-1], clipped_end):
                current.append(clipped_end)
            continue

        deduped = dedupe_consecutive_points(current)
        if len(deduped) >= 2:
            clipped_paths.append(deduped)
        current = [clipped_start, clipped_end]

    if len(current) >= 2:
        deduped = dedupe_consecutive_points(current)
        if len(deduped) >= 2:
            clipped_paths.append(deduped)

    return clipped_paths


def clip_polygon_to_rect(
    points: list[Point], rect: tuple[float, float, float, float]
) -> list[Point]:
    if len(points) < 4:
        return []

    ring = points[:-1] if points[0] == points[-1] else points[:]
    output = ring
    for edge in ("left", "right", "top", "bottom"):
        output = clip_polygon_edge(output, rect, edge)
        if len(output) < 3:
            return []

    output = dedupe_consecutive_points(output)
    if len(output) < 3:
        return []
    if not points_are_close(output[0], output[-1]):
        output.append(output[0])
    if polygon_area(output) <= POINT_EQUALITY_EPSILON:
        return []
    return output


def clip_polygon_edge(
    points: list[Point],
    rect: tuple[float, float, float, float],
    edge: str,
) -> list[Point]:
    if not points:
        return []

    clipped: list[Point] = []
    previous = points[-1]
    previous_inside = point_inside_edge(previous, rect, edge)
    for current in points:
        current_inside = point_inside_edge(current, rect, edge)
        if current_inside:
            if not previous_inside:
                clipped.append(
                    intersect_segment_with_edge(previous, current, rect, edge)
                )
            clipped.append(current)
        elif previous_inside:
            clipped.append(intersect_segment_with_edge(previous, current, rect, edge))
        previous = current
        previous_inside = current_inside
    return clipped


def point_inside_edge(
    point: Point, rect: tuple[float, float, float, float], edge: str
) -> bool:
    x, y = point
    min_x, min_y, max_x, max_y = rect
    if edge == "left":
        return x >= min_x
    if edge == "right":
        return x <= max_x
    if edge == "top":
        return y >= min_y
    return y <= max_y


def intersect_segment_with_edge(
    start: Point,
    end: Point,
    rect: tuple[float, float, float, float],
    edge: str,
) -> Point:
    x1, y1 = start
    x2, y2 = end
    min_x, min_y, max_x, max_y = rect
    dx = x2 - x1
    dy = y2 - y1

    if edge in {"left", "right"}:
        boundary_x = min_x if edge == "left" else max_x
        if abs(dx) <= POINT_EQUALITY_EPSILON:
            return (boundary_x, y1)
        ratio = (boundary_x - x1) / dx
        return (boundary_x, y1 + ratio * dy)

    boundary_y = min_y if edge == "top" else max_y
    if abs(dy) <= POINT_EQUALITY_EPSILON:
        return (x1, boundary_y)
    ratio = (boundary_y - y1) / dy
    return (x1 + ratio * dx, boundary_y)


def clip_segment_to_rect(
    start: Point,
    end: Point,
    rect: tuple[float, float, float, float],
) -> tuple[Point, Point] | None:
    min_x, min_y, max_x, max_y = rect
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    lower = 0.0
    upper = 1.0

    for p_value, q_value in (
        (-dx, x1 - min_x),
        (dx, max_x - x1),
        (-dy, y1 - min_y),
        (dy, max_y - y1),
    ):
        if abs(p_value) <= POINT_EQUALITY_EPSILON:
            if q_value < 0:
                return None
            continue
        ratio = q_value / p_value
        if p_value < 0:
            if ratio > upper:
                return None
            lower = max(lower, ratio)
        else:
            if ratio < lower:
                return None
            upper = min(upper, ratio)

    clipped_start = (x1 + lower * dx, y1 + lower * dy)
    clipped_end = (x1 + upper * dx, y1 + upper * dy)
    if points_are_close(clipped_start, clipped_end):
        return None
    return clipped_start, clipped_end


def simplify_polyline(points: list[Point], tolerance: float) -> list[Point]:
    deduped = dedupe_consecutive_points(points)
    if len(deduped) <= 2 or tolerance <= 0:
        return deduped

    keep = [False] * len(deduped)
    keep[0] = True
    keep[-1] = True
    stack = [(0, len(deduped) - 1)]
    while stack:
        start_index, end_index = stack.pop()
        max_distance = 0.0
        split_index: int | None = None
        for index in range(start_index + 1, end_index):
            distance = point_to_segment_distance(
                deduped[index], deduped[start_index], deduped[end_index]
            )
            if distance > max_distance:
                max_distance = distance
                split_index = index
        if split_index is not None and max_distance > tolerance:
            keep[split_index] = True
            stack.append((start_index, split_index))
            stack.append((split_index, end_index))

    return [point for point, should_keep in zip(deduped, keep) if should_keep]


def simplify_polygon(points: list[Point], tolerance: float) -> list[Point]:
    ring = points[:-1] if points[0] == points[-1] else points[:]
    ring = dedupe_consecutive_points(ring)
    if len(ring) <= 3 or tolerance <= 0:
        closed = ring[:]
        if closed and not points_are_close(closed[0], closed[-1]):
            closed.append(closed[0])
        return closed

    # Visvalingam-Whyatt: iteratively remove the vertex whose triangle
    # (formed with its two neighbours) has the smallest area, until all
    # remaining triangles exceed the area threshold.  This naturally
    # handles closed rings and preserves overall shape better than DP.
    area_threshold = tolerance * tolerance * 0.5

    n = len(ring)
    removed = [False] * n
    prev_idx = [(i - 1) % n for i in range(n)]
    next_idx = [(i + 1) % n for i in range(n)]

    def _triangle_area(i: int) -> float:
        p = ring[prev_idx[i]]
        c = ring[i]
        nx = ring[next_idx[i]]
        return (
            abs((p[0] - nx[0]) * (c[1] - p[1]) - (p[0] - c[0]) * (nx[1] - p[1])) * 0.5
        )

    areas = [0.0] * n
    heap: list[tuple[float, int, int]] = []  # (area, seq, index)
    seq = 0
    for i in range(n):
        a = _triangle_area(i)
        areas[i] = a
        heapq.heappush(heap, (a, seq, i))
        seq += 1

    remaining = n
    while heap and remaining > 3:
        a, _, i = heapq.heappop(heap)
        if removed[i] or a != areas[i]:
            continue
        if a >= area_threshold:
            break
        removed[i] = True
        remaining -= 1
        p = prev_idx[i]
        nx = next_idx[i]
        next_idx[p] = nx
        prev_idx[nx] = p
        for j in (p, nx):
            if not removed[j]:
                new_a = max(_triangle_area(j), a)
                areas[j] = new_a
                heapq.heappush(heap, (new_a, seq, j))
                seq += 1

    ring = [ring[i] for i in range(n) if not removed[i]]

    if len(ring) < 3:
        return []
    if polygon_area(ring) <= POINT_EQUALITY_EPSILON:
        return []
    ring.append(ring[0])
    return ring


def dedupe_consecutive_points(points: list[Point]) -> list[Point]:
    deduped: list[Point] = []
    for point in points:
        if deduped and points_are_close(deduped[-1], point):
            continue
        deduped.append(point)
    return deduped


def points_are_close(first: Point, second: Point) -> bool:
    return (
        abs(first[0] - second[0]) <= POINT_EQUALITY_EPSILON
        and abs(first[1] - second[1]) <= POINT_EQUALITY_EPSILON
    )


def point_to_segment_distance(point: Point, start: Point, end: Point) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) <= POINT_EQUALITY_EPSILON and abs(dy) <= POINT_EQUALITY_EPSILON:
        return math.hypot(px - x1, py - y1)
    ratio = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    clamped_ratio = max(0.0, min(1.0, ratio))
    projected_x = x1 + clamped_ratio * dx
    projected_y = y1 + clamped_ratio * dy
    return math.hypot(px - projected_x, py - projected_y)


def polygon_area(points: list[Point]) -> float:
    if len(points) < 3:
        return 0.0
    ring = points[:-1] if points[0] == points[-1] else points
    area = 0.0
    for start, end in zip(ring, ring[1:] + ring[:1]):
        area += start[0] * end[1] - end[0] * start[1]
    return abs(area) * 0.5


def render_svg(scene: ProjectedScene) -> str:
    theme = scene.theme
    metrics = compute_scene_metrics(scene)
    prefers_cjk = scene_prefers_cjk(scene)
    font_family = build_svg_font_stack(scene.font_family, prefers_cjk=prefers_cjk)
    mono_family = build_svg_font_stack(
        scene.font_family, prefers_cjk=False, monospace=True
    )
    aria_label = svg_attr(f"{scene.title} map poster")

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{scene.width}" height="{scene.height}" '
            f'viewBox="0 0 {scene.width} {scene.height}" role="img" aria-label="{aria_label}">'
        ),
        "<defs>",
        '<linearGradient id="terraink-fade-top" x1="0" y1="0" x2="0" y2="1">',
        f'<stop offset="0%" stop-color="{theme.ui.bg}" stop-opacity="1"/>',
        f'<stop offset="100%" stop-color="{theme.ui.bg}" stop-opacity="0"/>',
        "</linearGradient>",
        '<linearGradient id="terraink-fade-bottom" x1="0" y1="1" x2="0" y2="0">',
        f'<stop offset="0%" stop-color="{theme.ui.bg}" stop-opacity="1"/>',
        f'<stop offset="100%" stop-color="{theme.ui.bg}" stop-opacity="0"/>',
        "</linearGradient>",
        "</defs>",
        f'<rect width="{scene.width}" height="{scene.height}" fill="{theme.map.land}"/>',
    ]

    for layer_name, color, opacity in (
        ("parks", theme.map.parks, 1.0),
        ("water", theme.map.water, 1.0),
        ("aeroway", theme.map.aeroway, 0.85),
        ("buildings", theme.map.buildings, 0.84),
    ):
        for path in scene.polygons.get(layer_name, []):
            lines.append(
                f'<path d="{path_to_svg(path, closed=True)}" fill="{color}" fill-opacity="{opacity:.3f}"/>'
            )

    for path in scene.lines.get("waterway", []):
        lines.append(
            stroke_path_element(
                path,
                stroke=theme.map.waterway,
                stroke_width=metrics["waterway_width"],
                opacity=0.92,
            )
        )

    for path in scene.lines.get("rail", []):
        lines.append(
            stroke_path_element(
                path,
                stroke=theme.map.rail,
                stroke_width=metrics["rail_width"],
                opacity=0.7,
                dasharray=f"{fmt(metrics['rail_width'] * 2.0)} {fmt(metrics['rail_width'] * 1.6)}",
            )
        )

    for layer_name, color, width_key, opacity_key in (
        (
            "road_minor_high",
            theme.map.roads.minor_high,
            "minor_high_overview_width",
            "minor_high_overview_opacity",
        ),
        (
            "road_minor_mid",
            theme.map.roads.minor_mid,
            "minor_mid_overview_width",
            "minor_mid_overview_opacity",
        ),
        (
            "road_minor_low",
            theme.map.roads.minor_low,
            "minor_low_overview_width",
            "minor_low_overview_opacity",
        ),
        (
            "road_path",
            theme.map.roads.path,
            "path_overview_width",
            "path_overview_opacity",
        ),
    ):
        opacity = metrics[opacity_key]
        if opacity <= 0.001:
            continue
        for path in scene.lines.get(layer_name, []):
            lines.append(
                stroke_path_element(
                    path,
                    stroke=color,
                    stroke_width=metrics[width_key],
                    opacity=opacity,
                )
            )

    if scene.include_road_outline:
        for layer_name, width_key, opacity_key in (
            ("road_major", "major_casing_width", "major_casing_opacity"),
            ("road_minor_high", "minor_high_casing_width", "minor_high_casing_opacity"),
            ("road_minor_mid", "minor_mid_casing_width", "minor_mid_casing_opacity"),
            ("road_path", "path_casing_width", "path_casing_opacity"),
        ):
            opacity = metrics[opacity_key]
            if opacity <= 0.001:
                continue
            for path in scene.lines.get(layer_name, []):
                lines.append(
                    stroke_path_element(
                        path,
                        stroke=theme.map.roads.outline,
                        stroke_width=metrics[width_key],
                        opacity=opacity,
                    )
                )

    for layer_name, color, width_key, opacity_key in (
        ("road_major", theme.map.roads.major, "major_width", "major_opacity"),
        (
            "road_minor_high",
            theme.map.roads.minor_high,
            "minor_high_width",
            "minor_high_opacity",
        ),
        (
            "road_minor_mid",
            theme.map.roads.minor_mid,
            "minor_mid_width",
            "minor_mid_opacity",
        ),
        (
            "road_minor_low",
            theme.map.roads.minor_low,
            "minor_low_width",
            "minor_low_opacity",
        ),
        ("road_path", theme.map.roads.path, "path_width", "path_opacity"),
    ):
        opacity = metrics[opacity_key]
        if opacity <= 0.001:
            continue
        for path in scene.lines.get(layer_name, []):
            lines.append(
                stroke_path_element(
                    path,
                    stroke=color,
                    stroke_width=metrics[width_key],
                    opacity=opacity,
                )
            )

    for path in scene.lines.get("running_route", []):
        lines.append(
            stroke_path_element(
                path,
                stroke=theme.map.land,
                stroke_width=metrics["running_route_outline_width"],
                opacity=metrics["running_route_outline_opacity"],
            )
        )
        lines.append(
            stroke_path_element(
                path,
                stroke=RUNNING_ROUTE_COLOR,
                stroke_width=metrics["running_route_width"],
                opacity=metrics["running_route_opacity"],
            )
        )

    lines.extend(
        [
            f'<rect x="0" y="0" width="{scene.width}" height="{scene.height * 0.25}" fill="url(#terraink-fade-top)"/>',
            f'<rect x="0" y="{scene.height * 0.75}" width="{scene.width}" height="{scene.height * 0.25}" fill="url(#terraink-fade-bottom)"/>',
        ]
    )

    if scene.show_poster_text:
        lines.extend(
            render_svg_text_block(
                scene=scene,
                font_family=font_family,
                mono_family=mono_family,
                metrics=metrics,
            )
        )

    lines.extend(
        render_svg_credits(
            scene=scene,
            mono_family=mono_family,
            metrics=metrics,
        )
    )
    lines.append("</svg>")
    return "\n".join(lines)


def render_png(scene: ProjectedScene, output_path: Path) -> None:
    from PIL import Image, ImageDraw

    theme = scene.theme
    metrics = compute_scene_metrics(scene)
    image = Image.new("RGBA", (scene.width, scene.height), hex_to_rgba(theme.map.land))
    draw = ImageDraw.Draw(image, "RGBA")

    for layer_name, color, alpha in (
        ("parks", theme.map.parks, 255),
        ("water", theme.map.water, 255),
        ("aeroway", theme.map.aeroway, 217),
        ("buildings", theme.map.buildings, 214),
    ):
        for path in scene.polygons.get(layer_name, []):
            draw.polygon(path, fill=hex_to_rgba(color, alpha))

    for path in scene.lines.get("waterway", []):
        draw_polyline(
            draw,
            path,
            fill=hex_to_rgba(theme.map.waterway, 235),
            width=metrics["waterway_width"],
        )

    for path in scene.lines.get("rail", []):
        draw_dashed_polyline(
            draw,
            path,
            fill=hex_to_rgba(theme.map.rail, 180),
            width=metrics["rail_width"],
            dash=max(metrics["rail_width"] * 2.0, 3.0),
            gap=max(metrics["rail_width"] * 1.6, 2.0),
        )

    for layer_name, color, width_key, opacity_key in (
        (
            "road_minor_high",
            theme.map.roads.minor_high,
            "minor_high_overview_width",
            "minor_high_overview_opacity",
        ),
        (
            "road_minor_mid",
            theme.map.roads.minor_mid,
            "minor_mid_overview_width",
            "minor_mid_overview_opacity",
        ),
        (
            "road_minor_low",
            theme.map.roads.minor_low,
            "minor_low_overview_width",
            "minor_low_overview_opacity",
        ),
        (
            "road_path",
            theme.map.roads.path,
            "path_overview_width",
            "path_overview_opacity",
        ),
    ):
        alpha = opacity_to_alpha(metrics[opacity_key])
        if alpha <= 0:
            continue
        for path in scene.lines.get(layer_name, []):
            draw_polyline(
                draw,
                path,
                fill=hex_to_rgba(color, alpha),
                width=metrics[width_key],
            )

    if scene.include_road_outline:
        for layer_name, width_key, opacity_key in (
            ("road_major", "major_casing_width", "major_casing_opacity"),
            ("road_minor_high", "minor_high_casing_width", "minor_high_casing_opacity"),
            ("road_minor_mid", "minor_mid_casing_width", "minor_mid_casing_opacity"),
            ("road_path", "path_casing_width", "path_casing_opacity"),
        ):
            alpha = opacity_to_alpha(metrics[opacity_key])
            if alpha <= 0:
                continue
            for path in scene.lines.get(layer_name, []):
                draw_polyline(
                    draw,
                    path,
                    fill=hex_to_rgba(theme.map.roads.outline, alpha),
                    width=metrics[width_key],
                )

    for layer_name, color, width_key, opacity_key in (
        ("road_major", theme.map.roads.major, "major_width", "major_opacity"),
        (
            "road_minor_high",
            theme.map.roads.minor_high,
            "minor_high_width",
            "minor_high_opacity",
        ),
        (
            "road_minor_mid",
            theme.map.roads.minor_mid,
            "minor_mid_width",
            "minor_mid_opacity",
        ),
        (
            "road_minor_low",
            theme.map.roads.minor_low,
            "minor_low_width",
            "minor_low_opacity",
        ),
        ("road_path", theme.map.roads.path, "path_width", "path_opacity"),
    ):
        alpha = opacity_to_alpha(metrics[opacity_key])
        if alpha <= 0:
            continue
        for path in scene.lines.get(layer_name, []):
            draw_polyline(
                draw,
                path,
                fill=hex_to_rgba(color, alpha),
                width=metrics[width_key],
            )

    running_outline_alpha = opacity_to_alpha(metrics["running_route_outline_opacity"])
    running_alpha = opacity_to_alpha(metrics["running_route_opacity"])
    for path in scene.lines.get("running_route", []):
        draw_polyline(
            draw,
            path,
            fill=hex_to_rgba(theme.map.land, running_outline_alpha),
            width=metrics["running_route_outline_width"],
        )
        draw_polyline(
            draw,
            path,
            fill=hex_to_rgba(RUNNING_ROUTE_COLOR, running_alpha),
            width=metrics["running_route_width"],
        )

    apply_png_fades(image, theme.ui.bg)

    font_regular = resolve_font(
        scene.font_file,
        int(metrics["country_font_size"]),
        bold=False,
        text=scene.subtitle,
    )
    font_bold = resolve_font(
        scene.font_file,
        int(metrics["city_font_size"]),
        bold=True,
        text=scene.title,
    )
    font_coords = resolve_font(
        scene.font_file,
        int(metrics["coords_font_size"]),
        bold=False,
        monospace=True,
        text=format_coordinates(scene.center.lat, scene.center.lon),
    )
    font_credit = resolve_font(
        scene.font_file,
        int(metrics["attribution_font_size"]),
        bold=False,
        monospace=True,
        text=CREATOR_CREDIT,
    )

    if scene.show_poster_text:
        city_label = format_city_label(scene.title)
        draw_centered_text(
            draw,
            (scene.width * 0.5, scene.height * TEXT_CITY_Y_RATIO),
            city_label,
            font_bold,
            fill=hex_to_rgba(theme.ui.text),
        )
        draw.line(
            (
                scene.width * 0.4,
                scene.height * TEXT_DIVIDER_Y_RATIO,
                scene.width * 0.6,
                scene.height * TEXT_DIVIDER_Y_RATIO,
            ),
            fill=hex_to_rgba(theme.ui.text),
            width=max(1, int(round(3 * metrics["dim_scale"]))),
        )
        draw_centered_text(
            draw,
            (scene.width * 0.5, scene.height * TEXT_COUNTRY_Y_RATIO),
            scene.subtitle.upper(),
            font_regular,
            fill=hex_to_rgba(theme.ui.text),
        )
        draw_centered_text(
            draw,
            (scene.width * 0.5, scene.height * TEXT_COORDS_Y_RATIO),
            format_coordinates(scene.center.lat, scene.center.lon),
            font_coords,
            fill=hex_to_rgba(theme.ui.text, 192),
        )

    edge_margin_x = scene.width * TEXT_EDGE_MARGIN_RATIO
    edge_margin_y = scene.height * (1 - TEXT_EDGE_MARGIN_RATIO)
    draw.text(
        (scene.width - edge_margin_x, edge_margin_y),
        "\u00a9 OpenStreetMap contributors",
        fill=hex_to_rgba(theme.ui.text, opacity_to_alpha(0.55)),
        font=font_credit,
        anchor="rb",
    )
    if scene.include_credits:
        draw.text(
            (edge_margin_x, edge_margin_y),
            CREATOR_CREDIT,
            fill=hex_to_rgba(theme.ui.text, opacity_to_alpha(0.55)),
            font=font_credit,
            anchor="lb",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", dpi=(scene.dpi, scene.dpi))


def render_svg_text_block(
    *,
    scene: ProjectedScene,
    font_family: str,
    mono_family: str,
    metrics: dict[str, float],
) -> list[str]:
    city_label = escape(format_city_label(scene.title))
    return [
        (
            f'<text x="{fmt(scene.width * 0.5)}" y="{fmt(scene.height * TEXT_CITY_Y_RATIO)}" '
            f'fill="{scene.theme.ui.text}" text-anchor="middle" dominant-baseline="middle" '
            f'font-family="{svg_attr(font_family)}" font-size="{fmt(metrics["city_font_size"])}" '
            'font-weight="700">'
            f"{city_label}</text>"
        ),
        (
            f'<line x1="{fmt(scene.width * 0.4)}" y1="{fmt(scene.height * TEXT_DIVIDER_Y_RATIO)}" '
            f'x2="{fmt(scene.width * 0.6)}" y2="{fmt(scene.height * TEXT_DIVIDER_Y_RATIO)}" '
            f'stroke="{scene.theme.ui.text}" stroke-width="{fmt(3 * metrics["dim_scale"])}"/>'
        ),
        (
            f'<text x="{fmt(scene.width * 0.5)}" y="{fmt(scene.height * TEXT_COUNTRY_Y_RATIO)}" '
            f'fill="{scene.theme.ui.text}" text-anchor="middle" dominant-baseline="middle" '
            f'font-family="{svg_attr(font_family)}" font-size="{fmt(metrics["country_font_size"])}" '
            f'font-weight="300">{escape(scene.subtitle.upper())}</text>'
        ),
        (
            f'<text x="{fmt(scene.width * 0.5)}" y="{fmt(scene.height * TEXT_COORDS_Y_RATIO)}" '
            f'fill="{scene.theme.ui.text}" fill-opacity="0.75" text-anchor="middle" dominant-baseline="middle" '
            f'font-family="{svg_attr(mono_family)}" font-size="{fmt(metrics["coords_font_size"])}" '
            f'font-weight="400">{escape(format_coordinates(scene.center.lat, scene.center.lon))}</text>'
        ),
    ]


def render_svg_credits(
    *,
    scene: ProjectedScene,
    mono_family: str,
    metrics: dict[str, float],
) -> list[str]:
    output = [
        (
            f'<text x="{fmt(scene.width * (1 - TEXT_EDGE_MARGIN_RATIO))}" '
            f'y="{fmt(scene.height * (1 - TEXT_EDGE_MARGIN_RATIO))}" fill="{scene.theme.ui.text}" '
            'fill-opacity="0.55" text-anchor="end" dominant-baseline="baseline" '
            f'font-family="{svg_attr(mono_family)}" font-size="{fmt(metrics["attribution_font_size"])}">'
            "\u00a9 OpenStreetMap contributors</text>"
        )
    ]
    if scene.include_credits:
        output.append(
            (
                f'<text x="{fmt(scene.width * TEXT_EDGE_MARGIN_RATIO)}" '
                f'y="{fmt(scene.height * (1 - TEXT_EDGE_MARGIN_RATIO))}" fill="{scene.theme.ui.text}" '
                'fill-opacity="0.55" text-anchor="start" dominant-baseline="baseline" '
                f'font-family="{svg_attr(mono_family)}" font-size="{fmt(metrics["attribution_font_size"])}">'
                f"{escape(CREATOR_CREDIT)}</text>"
            )
        )
    return output


def compute_scene_metrics(scene: ProjectedScene) -> dict[str, float]:
    dim_scale = max(0.45, min(scene.width, scene.height) / TEXT_DIMENSION_REFERENCE_PX)
    distance_factor = clamp((4_000.0 / scene.distance_m) ** 0.38, 0.42, 2.2)
    line_scale = dim_scale * distance_factor
    estimated_zoom = estimate_map_zoom(scene)
    title_length = max(len(scene.title), 1)
    city_font_size = CITY_FONT_BASE_PX * dim_scale
    if title_length > CITY_TEXT_SHRINK_THRESHOLD:
        city_font_size = max(
            CITY_FONT_MIN_PX * dim_scale,
            city_font_size * (CITY_TEXT_SHRINK_THRESHOLD / title_length),
        )
    major_width = max(1.1, 5.4 * line_scale)
    minor_high_width = max(0.86, 3.15 * line_scale)
    minor_mid_width = max(0.72, 2.2 * line_scale)
    minor_low_width = max(0.58, 1.4 * line_scale)
    path_width = max(0.5, 0.92 * line_scale)
    return {
        "dim_scale": dim_scale,
        "estimated_zoom": estimated_zoom,
        "city_font_size": city_font_size,
        "country_font_size": COUNTRY_FONT_BASE_PX * dim_scale,
        "coords_font_size": COORDS_FONT_BASE_PX * dim_scale,
        "attribution_font_size": ATTRIBUTION_FONT_BASE_PX * dim_scale,
        "major_width": major_width,
        "minor_high_width": minor_high_width,
        "minor_mid_width": minor_mid_width,
        "minor_low_width": minor_low_width,
        "path_width": path_width,
        "running_route_width": max(1.4, major_width * 0.85),
        "waterway_width": max(0.62, 1.15 * line_scale),
        "rail_width": max(0.58, 0.92 * line_scale),
        "major_casing_width": major_width * 1.38,
        "minor_high_casing_width": minor_high_width * 1.45,
        "minor_mid_casing_width": minor_mid_width * 1.15,
        "path_casing_width": path_width * 1.6,
        "running_route_outline_width": max(2.2, major_width * 1.5),
        "minor_high_overview_width": max(0.1, minor_high_width * 0.34),
        "minor_mid_overview_width": max(0.08, minor_mid_width * 0.3),
        "minor_low_overview_width": max(0.06, minor_low_width * 0.26),
        "path_overview_width": max(0.05, path_width * 0.24),
        "major_opacity": 1.0,
        "minor_high_overview_opacity": interpolate_stops(
            estimated_zoom,
            ((0.0, 0.66), (8.0, 0.76), (12.0, 0.0)),
        ),
        "minor_mid_overview_opacity": interpolate_stops(
            estimated_zoom,
            ((0.0, 0.46), (8.0, 0.56), (12.0, 0.0)),
        ),
        "minor_low_overview_opacity": interpolate_stops(
            estimated_zoom,
            ((0.0, 0.26), (8.0, 0.34), (12.0, 0.0)),
        ),
        "path_overview_opacity": interpolate_stops(
            estimated_zoom,
            ((5.0, 0.45), (9.0, 0.58), (12.0, 0.0)),
        ),
        "major_casing_opacity": 0.95 if scene.include_road_outline else 0.0,
        "minor_high_casing_opacity": (
            interpolate_stops(
                estimated_zoom,
                ((6.0, 0.72), (12.0, 0.85), (18.0, 0.92)),
            )
            if scene.include_road_outline
            else 0.0
        ),
        "minor_mid_casing_opacity": (
            interpolate_stops(
                estimated_zoom,
                ((6.0, 0.42), (12.0, 0.56), (18.0, 0.66)),
            )
            if scene.include_road_outline
            else 0.0
        ),
        "path_casing_opacity": (
            interpolate_stops(
                estimated_zoom,
                ((8.0, 0.62), (12.0, 0.72), (18.0, 0.85)),
            )
            if scene.include_road_outline
            else 0.0
        ),
        "minor_high_opacity": interpolate_stops(
            estimated_zoom,
            ((6.0, 0.84), (10.0, 0.92), (18.0, 1.0)),
        ),
        "minor_mid_opacity": interpolate_stops(
            estimated_zoom,
            ((6.0, 0.62), (10.0, 0.74), (18.0, 0.86)),
        ),
        "minor_low_opacity": interpolate_stops(
            estimated_zoom,
            ((6.0, 0.34), (10.0, 0.46), (18.0, 0.58)),
        ),
        "path_opacity": interpolate_stops(
            estimated_zoom,
            ((8.0, 0.7), (12.0, 0.82), (18.0, 0.95)),
        ),
        "running_route_opacity": 1.0,
        "running_route_outline_opacity": 0.96,
    }


def estimate_map_zoom(scene: ProjectedScene) -> float:
    full_width_meters = max(scene.distance_m * 2.0, 1.0)
    cosine = max(abs(math.cos(math.radians(scene.center.lat))), 0.01)
    zoom = math.log2(
        (EARTH_CIRCUMFERENCE_M * cosine * max(scene.width, 1))
        / (full_width_meters * TILE_SIZE_PX)
    )
    return clamp(zoom, MIN_MAP_ZOOM, MAX_MAP_ZOOM)


def interpolate_stops(value: float, stops: tuple[tuple[float, float], ...]) -> float:
    if not stops:
        return 0.0
    if value <= stops[0][0]:
        return stops[0][1]
    for (start_x, start_y), (end_x, end_y) in zip(stops, stops[1:]):
        if value <= end_x:
            if end_x == start_x:
                return end_y
            ratio = (value - start_x) / (end_x - start_x)
            return start_y + (end_y - start_y) * ratio
    return stops[-1][1]


def stroke_path_element(
    path: list[Point],
    *,
    stroke: str,
    stroke_width: float,
    opacity: float,
    dasharray: str | None = None,
) -> str:
    dash_attr = f' stroke-dasharray="{dasharray}"' if dasharray else ""
    return (
        f'<path d="{path_to_svg(path, closed=False)}" fill="none" stroke="{stroke}" '
        f'stroke-width="{fmt(stroke_width)}" stroke-opacity="{opacity:.3f}" '
        f'stroke-linecap="round" stroke-linejoin="round"{dash_attr}/>'
    )


def path_to_svg(path: list[Point], *, closed: bool) -> str:
    parts = [f"M {fmt(path[0][0])} {fmt(path[0][1])}"]
    parts.extend(f"L {fmt(x)} {fmt(y)}" for x, y in path[1:])
    if closed:
        parts.append("Z")
    return " ".join(parts)


def fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def svg_attr(value: str) -> str:
    return escape(value, entities={'"': "&quot;", "'": "&apos;"})


def clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


@lru_cache(maxsize=64)
def hex_to_rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    raw = value.strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return (0, 0, 0, alpha)
    try:
        return (
            int(raw[0:2], 16),
            int(raw[2:4], 16),
            int(raw[4:6], 16),
            alpha,
        )
    except ValueError:
        return (0, 0, 0, alpha)


def opacity_to_alpha(opacity: float) -> int:
    return max(0, min(255, int(round(opacity * 255))))


def draw_polyline(
    draw, points: list[Point], *, fill: tuple[int, int, int, int], width: float
) -> None:
    draw.line(points, fill=fill, width=max(1, int(round(width))), joint="curve")


def draw_dashed_polyline(
    draw,
    points: list[Point],
    *,
    fill: tuple[int, int, int, int],
    width: float,
    dash: float,
    gap: float,
) -> None:
    if len(points) < 2:
        return
    width_int = max(1, int(round(width)))
    segments: list[tuple[float, float, float, float]] = []
    for start, end in zip(points, points[1:]):
        x1, y1 = start
        x2, y2 = end
        segment_length = math.hypot(x2 - x1, y2 - y1)
        if segment_length == 0:
            continue
        dx = (x2 - x1) / segment_length
        dy = (y2 - y1) / segment_length
        position = 0.0
        while position < segment_length:
            dash_end = min(position + dash, segment_length)
            segments.append(
                (
                    x1 + dx * position,
                    y1 + dy * position,
                    x1 + dx * dash_end,
                    y1 + dy * dash_end,
                )
            )
            position += dash + gap
    for seg in segments:
        draw.line(seg, fill=fill, width=width_int)


def apply_png_fades(image, color: str) -> None:
    from PIL import Image

    rgb = hex_to_rgba(color, 255)
    width, height = image.size
    top_end = int(height * 0.25) or 1
    bottom_start = int(height * 0.75)

    alpha_values = [0] * height
    top_steps = max(1, top_end - 1)
    for index in range(top_end):
        alpha_values[index] = round(255 * (top_steps - index) / top_steps)

    bottom_length = height - bottom_start
    bottom_steps = max(1, bottom_length - 1)
    for offset in range(bottom_length):
        alpha_values[bottom_start + offset] = round(255 * offset / bottom_steps)

    alpha_strip = Image.new("L", (1, height))
    alpha_strip.putdata(alpha_values)
    overlay = Image.new("RGBA", image.size, (rgb[0], rgb[1], rgb[2], 0))
    overlay.putalpha(alpha_strip.resize((width, height), Image.Resampling.NEAREST))
    image.alpha_composite(overlay)


def scene_prefers_cjk(scene: ProjectedScene) -> bool:
    return contains_cjk(scene.title) or contains_cjk(scene.subtitle)


def build_svg_font_stack(
    preferred_family: str | None,
    *,
    prefers_cjk: bool,
    monospace: bool = False,
) -> str:
    stack: list[str] = []
    if preferred_family:
        stack.append(preferred_family)
    stack.extend(CJK_SVG_FONT_STACK if prefers_cjk else [])
    stack.extend(DEFAULT_SVG_MONO_STACK if monospace else DEFAULT_SVG_FONT_STACK)

    deduped: list[str] = []
    seen: set[str] = set()
    for family in stack:
        normalized = family.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        if " " in normalized and not normalized.startswith('"'):
            deduped.append(f'"{normalized}"')
        else:
            deduped.append(normalized)
    return ", ".join(deduped)


def resolve_font(
    font_file: Path | None,
    size: int,
    *,
    bold: bool,
    monospace: bool = False,
    text: str | None = None,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    needs_cjk = contains_cjk(text)
    font_file_str = str(font_file) if font_file is not None else None
    return _resolve_font_cached(font_file_str, size, bold, monospace, needs_cjk)


@lru_cache(maxsize=32)
def _resolve_font_cached(
    font_file_str: str | None,
    size: int,
    bold: bool,
    monospace: bool,
    needs_cjk: bool,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(size, 12)
    candidates: list[str] = []
    if font_file_str is not None:
        candidates.append(font_file_str)
    if needs_cjk:
        candidates.extend(
            CJK_FONT_CANDIDATES_BOLD if bold else CJK_FONT_CANDIDATES_REGULAR
        )
    if monospace:
        candidates.extend(
            [
                "IBMPlexMono-Regular.ttf",
                "IBM Plex Mono.ttf",
                "/Library/Fonts/IBM Plex Mono.ttf",
                "/System/Library/Fonts/SFNSMono.ttf",
                "/System/Library/Fonts/Supplemental/Menlo.ttc",
                "DejaVuSansMono.ttf",
            ]
        )
    if bold:
        candidates.extend(
            [
                "SpaceGrotesk-Bold.ttf",
                "Space Grotesk Bold.ttf",
                "/Library/Fonts/SpaceGrotesk-Bold.ttf",
                "DejaVuSans-Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            ]
        )
    elif not monospace:
        candidates.extend(
            [
                "SpaceGrotesk-Regular.ttf",
                "SpaceGrotesk-Medium.ttf",
                "Space Grotesk Regular.ttf",
                "/Library/Fonts/SpaceGrotesk-Regular.ttf",
                "DejaVuSans.ttf",
                "/Library/Fonts/Arial.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
            ]
        )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_centered_text(
    draw,
    position: tuple[float, float],
    text: str,
    font,
    *,
    fill: tuple[int, int, int, int],
    tracking: float = 0.0,
) -> None:
    if tracking <= 0:
        draw.text(position, text, fill=fill, font=font, anchor="mm")
        return

    char_boxes = [font.getbbox(char) for char in text]
    char_widths = [box[2] - box[0] for box in char_boxes]
    total_width = sum(char_widths) + tracking * max(len(text) - 1, 0)
    x = position[0] - total_width / 2.0
    for char, char_width in zip(text, char_widths):
        draw.text(
            (x + char_width / 2.0, position[1]), char, fill=fill, font=font, anchor="mm"
        )
        x += char_width + tracking
