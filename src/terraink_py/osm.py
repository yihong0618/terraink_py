from __future__ import annotations

import re
import time
from collections.abc import Sequence
from urllib.parse import urlencode

from .http import CachedHttpClient, HttpRequestError
from .models import Bounds, DEFAULT_OVERPASS_URL, LocationMetadata, PosterRequest

WATER_LANDUSE_VALUES = {"reservoir", "basin"}
PARK_LEISURE_VALUES = {"park", "garden", "pitch", "playground"}
PARK_LANDUSE_VALUES = {
    "grass",
    "recreation_ground",
    "forest",
    "meadow",
    "village_green",
}
PARK_NATURAL_VALUES = {"wood", "grassland", "scrub", "heath", "wetland"}
ROAD_MAJOR_CLASSES = {"motorway"}
ROAD_MINOR_HIGH_CLASSES = {
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "motorway_link",
    "trunk",
    "trunk_link",
}
ROAD_MINOR_MID_CLASSES = {"tertiary", "tertiary_link", "minor"}
ROAD_MINOR_LOW_CLASSES = {
    "residential",
    "living_street",
    "unclassified",
    "road",
    "street",
    "street_limited",
    "service",
}
ROAD_PATH_CLASSES = {
    "path",
    "pedestrian",
    "cycleway",
    "track",
    "footway",
    "steps",
    "bridleway",
}
RAIL_CLASSES = {"rail", "transit", "light_rail", "subway", "tram", "narrow_gauge"}
KNOWN_FOREIGN_CITIES = frozenset(
    {
        "东京",
        "大阪",
        "首尔",
        "平壤",
        "新加坡",
        "曼谷",
        "伦敦",
        "巴黎",
        "柏林",
        "罗马",
        "纽约",
        "洛杉矶",
        "悉尼",
        "迪拜",
    }
)
SETTLEMENT_TYPES = frozenset(
    {
        "city",
        "town",
        "village",
        "hamlet",
        "municipality",
        "borough",
        "suburb",
        "quarter",
        "neighbourhood",
    }
)
SETTLEMENT_ADDRESS_TYPES = frozenset(
    {
        "city",
        "town",
        "village",
        "municipality",
        "county",
        "district",
        "city_district",
        "suburb",
        "borough",
    }
)
ADMIN_NAME_SUFFIXES = (
    "特别行政区",
    "自治区",
    "自治州",
    "自治县",
    "省",
    "市",
    "区",
    "县",
    "州",
    "旗",
    "镇",
    "乡",
)
NOMINATIM_MIN_INTERVAL_SECONDS = 1.1
NOMINATIM_MAX_RETRIES = 2
NOMINATIM_RETRY_BACKOFF_SECONDS = 0.6
NOMINATIM_RESULT_LIMIT = 10
LAST_NOMINATIM_REQUEST_AT = 0.0
OVERPASS_FALLBACK_URLS = (
    DEFAULT_OVERPASS_URL,
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OVERPASS_MAX_RETRIES = 2
OVERPASS_RETRY_BACKOFF_SECONDS = 1.0
OVERPASS_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

LayerMap = dict[str, list[list[tuple[float, float]]]]


def resolve_location(
    request: PosterRequest, client: CachedHttpClient
) -> LocationMetadata:
    if request.location:
        return _geocode(request.location, request, client)
    assert request.lat is not None and request.lon is not None
    if request.title or request.subtitle:
        return LocationMetadata(
            label=request.title or f"{request.lat:.5f}, {request.lon:.5f}",
            lat=request.lat,
            lon=request.lon,
            city=request.title or "",
            country=request.subtitle or "",
        )
    return _reverse_geocode(request.lat, request.lon, request, client)


def fetch_osm_layers(
    bounds: Bounds,
    request: PosterRequest,
    client: CachedHttpClient,
) -> LayerMap:
    query = build_overpass_query(bounds, request)
    layers: LayerMap = {
        "water": [],
        "parks": [],
        "buildings": [],
        "aeroway": [],
        "waterway": [],
        "rail": [],
        "road_major": [],
        "road_minor_high": [],
        "road_minor_mid": [],
        "road_minor_low": [],
        "road_path": [],
    }
    if not query:
        return layers

    payload = _fetch_overpass_payload(query, request, client)

    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        polygon_layer = classify_polygon_layer(tags)
        if polygon_layer is not None:
            for geometry in extract_paths(element, polygon=True):
                if len(geometry) >= 4 and geometry[0] == geometry[-1]:
                    layers[polygon_layer].append(geometry)

        line_layer = classify_line_layer(tags, request)
        if line_layer is not None:
            for geometry in extract_paths(element, polygon=False):
                if len(geometry) >= 2:
                    layers[line_layer].append(geometry)

    return layers


def _fetch_overpass_payload(
    query: str,
    request: PosterRequest,
    client: CachedHttpClient,
) -> dict:
    last_error: Exception | None = None
    endpoints = list(_iter_overpass_urls(request.overpass_url))
    for endpoint_index, url in enumerate(endpoints):
        for attempt in range(OVERPASS_MAX_RETRIES + 1):
            try:
                return client.request_json(
                    "POST",
                    url,
                    body=query.encode("utf-8"),
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
            except HttpRequestError as exc:
                last_error = exc
                if not _should_retry_overpass(exc):
                    raise RuntimeError(f"Overpass request failed at {url}") from exc
                if attempt < OVERPASS_MAX_RETRIES:
                    time.sleep(OVERPASS_RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                break

        if endpoint_index < len(endpoints) - 1:
            time.sleep(OVERPASS_RETRY_BACKOFF_SECONDS)

    joined_urls = ", ".join(endpoints)
    raise RuntimeError(
        f"Overpass request failed after trying: {joined_urls}"
    ) from last_error


def _iter_overpass_urls(configured_url: str) -> list[str]:
    configured = [item.strip() for item in configured_url.split(",") if item.strip()]
    if not configured:
        configured = [DEFAULT_OVERPASS_URL]
    if configured != [DEFAULT_OVERPASS_URL]:
        return configured

    deduped: list[str] = []
    for url in OVERPASS_FALLBACK_URLS:
        if url not in deduped:
            deduped.append(url)
    return deduped


def _should_retry_overpass(exc: HttpRequestError) -> bool:
    return exc.status_code is None or exc.status_code in OVERPASS_RETRYABLE_STATUS_CODES


def build_overpass_query(bounds: Bounds, request: PosterRequest) -> str:
    bbox = (
        f"({bounds.south:.6f},{bounds.west:.6f},{bounds.north:.6f},{bounds.east:.6f})"
    )
    selectors: list[str] = []

    def add_way_relation(selector: str) -> None:
        selectors.append(f"way{selector}{bbox};")
        selectors.append(f"relation{selector}{bbox};")

    if request.include_buildings:
        add_way_relation('["building"]')
    if (
        request.include_roads
        or request.include_road_path
        or request.include_road_minor_low
    ):
        selectors.append(f'way["highway"]{bbox};')
    if request.include_rail:
        selectors.append(f'way["railway"]{bbox};')
        selectors.append(f'relation["railway"]{bbox};')
    if request.include_water:
        selectors.append(f'way["waterway"]{bbox};')
        selectors.append(f'relation["waterway"]{bbox};')
        add_way_relation('["natural"="water"]')
        add_way_relation('["water"]')
        add_way_relation('["landuse"~"reservoir|basin"]')
    if request.include_parks:
        add_way_relation('["leisure"~"park|garden|pitch|playground"]')
        add_way_relation(
            '["landuse"~"grass|recreation_ground|forest|meadow|village_green"]'
        )
        add_way_relation('["natural"~"wood|grassland|scrub|heath|wetland"]')
    if request.include_aeroway:
        add_way_relation('["aeroway"]')

    if not selectors:
        return ""
    return f"[out:json][timeout:{request.timeout_seconds}];({''.join(selectors)});out geom;"


def classify_polygon_layer(tags: dict[str, str]) -> str | None:
    if "building" in tags:
        return "buildings"
    if tags.get("natural") == "water" or "water" in tags:
        return "water"
    if tags.get("landuse") in WATER_LANDUSE_VALUES:
        return "water"
    if tags.get("leisure") in PARK_LEISURE_VALUES:
        return "parks"
    if tags.get("landuse") in PARK_LANDUSE_VALUES:
        return "parks"
    if tags.get("natural") in PARK_NATURAL_VALUES:
        return "parks"
    if "aeroway" in tags:
        return "aeroway"
    return None


def classify_line_layer(tags: dict[str, str], request: PosterRequest) -> str | None:
    waterway = tags.get("waterway")
    if request.include_water and waterway in {"river", "canal", "stream", "ditch"}:
        return "waterway"

    railway = tags.get("railway")
    if request.include_rail and railway in RAIL_CLASSES:
        return "rail"

    highway = tags.get("highway")
    if not highway:
        return None
    if highway in ROAD_PATH_CLASSES:
        return "road_path" if request.include_road_path else None
    if not request.include_roads:
        return None
    if highway in ROAD_MAJOR_CLASSES:
        return "road_major"
    if highway in ROAD_MINOR_HIGH_CLASSES:
        return "road_minor_high"
    if highway in ROAD_MINOR_MID_CLASSES:
        return "road_minor_mid"
    if highway in ROAD_MINOR_LOW_CLASSES:
        return "road_minor_low" if request.include_road_minor_low else None
    return None


def extract_paths(element: dict, *, polygon: bool) -> list[list[tuple[float, float]]]:
    element_type = element.get("type")
    if element_type == "way":
        path = geometry_to_points(element.get("geometry", []))
        if polygon:
            return (
                [close_path(path)]
                if is_closed_shape(path, element.get("tags", {}))
                else []
            )
        return [path] if len(path) >= 2 else []

    if element_type != "relation":
        return []

    members = [
        member
        for member in element.get("members", [])
        if member.get("type") == "way" and member.get("geometry")
    ]
    if polygon:
        preferred = [member for member in members if member.get("role") == "outer"] or [
            member for member in members if member.get("role") != "inner"
        ]
        paths = [
            close_path(geometry_to_points(member.get("geometry", [])))
            for member in preferred
        ]
        return [
            path for path in paths if is_closed_shape(path, element.get("tags", {}))
        ]

    return [
        path
        for path in (
            geometry_to_points(member.get("geometry", [])) for member in members
        )
        if len(path) >= 2
    ]


def geometry_to_points(items: list[dict]) -> list[tuple[float, float]]:
    return [
        (float(item["lon"]), float(item["lat"]))
        for item in items
        if "lon" in item and "lat" in item
    ]


def close_path(path: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(path) >= 3 and path[0] != path[-1]:
        return [*path, path[0]]
    return list(path)


def is_closed_shape(path: Sequence[tuple[float, float]], tags: dict[str, str]) -> bool:
    if len(path) < 4:
        return False
    if path[0] == path[-1]:
        return True
    return tags.get("area") == "yes"


def _geocode(
    query: str, request: PosterRequest, client: CachedHttpClient
) -> LocationMetadata:
    normalized_query = " ".join(query.split()).strip()
    if not normalized_query:
        raise RuntimeError("Location query is empty.")

    last_error: RuntimeError | None = None
    for candidate, countrycodes in build_geocode_search_plan(normalized_query):
        for attempt in range(NOMINATIM_MAX_RETRIES + 1):
            try:
                results = _nominatim_search(
                    candidate,
                    countrycodes=countrycodes,
                    request=request,
                    client=client,
                )
                if not results:
                    break
                return _location_from_nominatim_item(
                    _select_best_nominatim_result(normalized_query, results)
                )
            except RuntimeError as exc:
                last_error = exc
                if attempt < NOMINATIM_MAX_RETRIES:
                    time.sleep(NOMINATIM_RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                break

    if last_error is not None:
        raise RuntimeError(
            f"Could not geocode location: {normalized_query}"
        ) from last_error
    raise RuntimeError(f"Could not geocode location: {normalized_query}")


def _reverse_geocode(
    lat: float,
    lon: float,
    request: PosterRequest,
    client: CachedHttpClient,
) -> LocationMetadata:
    params = urlencode(
        {
            "lat": f"{lat:.7f}",
            "lon": f"{lon:.7f}",
            "format": "jsonv2",
            "zoom": "10",
            "addressdetails": "1",
        }
    )
    payload = client.request_json("GET", f"{request.nominatim_url}/reverse?{params}")
    if not isinstance(payload, dict):
        raise RuntimeError("Reverse geocoding returned an invalid response.")
    return _location_from_nominatim_item(payload)


def _location_from_nominatim_item(item: dict) -> LocationMetadata:
    address = item.get("address", {})
    city = ""
    for key in (
        "city_district",
        "city",
        "town",
        "village",
        "municipality",
        "county",
        "state_district",
        "suburb",
    ):
        value = str(address.get(key, "")).strip()
        if value:
            city = value
            break
    country = str(address.get("country", "")).strip()
    continent = str(address.get("continent", "")).strip()
    label = str(item.get("display_name", city or country)).strip()
    return LocationMetadata(
        label=label,
        lat=float(item["lat"]),
        lon=float(item["lon"]),
        city=city or label,
        country=country,
        continent=continent,
    )


def _select_best_nominatim_result(query: str, results: Sequence[dict]) -> dict:
    return max(results, key=lambda item: _nominatim_result_sort_key(query, item))


def _nominatim_result_sort_key(
    query: str, item: dict
) -> tuple[int, int, int, int, int, float, int]:
    category = str(item.get("category", "")).strip().casefold()
    item_type = str(item.get("type", "")).strip().casefold()
    addresstype = str(item.get("addresstype", "")).strip().casefold()
    importance = float(item.get("importance") or 0.0)
    place_rank = int(item.get("place_rank") or 0)
    return (
        1 if _nominatim_item_exact_name_match(query, item) else 0,
        1 if _nominatim_item_matches_query(query, item) else 0,
        _nominatim_settlement_score(category, item_type, addresstype),
        1 if category == "place" else 0,
        0 if category == "boundary" and item_type == "administrative" else 1,
        importance,
        place_rank,
    )


def _nominatim_settlement_score(
    category: str,
    item_type: str,
    addresstype: str,
) -> int:
    score = 0
    if category == "place":
        score += 2
    if item_type in SETTLEMENT_TYPES:
        score += 2
    if addresstype in SETTLEMENT_ADDRESS_TYPES:
        score += 1
    return score


def _nominatim_item_matches_query(query: str, item: dict) -> bool:
    query_names = _normalized_name_variants(query, strip_admin_suffixes=True)
    if not query_names:
        return False
    return not query_names.isdisjoint(
        _nominatim_item_name_variants(item, strip_admin_suffixes=True)
    )


def _nominatim_item_exact_name_match(query: str, item: dict) -> bool:
    query_names = _normalized_name_variants(query, strip_admin_suffixes=False)
    if not query_names:
        return False
    return not query_names.isdisjoint(
        _nominatim_item_name_variants(item, strip_admin_suffixes=False)
    )


def _nominatim_item_name_variants(
    item: dict, *, strip_admin_suffixes: bool
) -> set[str]:
    variants: set[str] = set()
    values = [item.get("name")]
    address = item.get("address", {})
    if isinstance(address, dict):
        values.extend(address.values())
    for value in values:
        variants.update(
            _normalized_name_variants(
                str(value), strip_admin_suffixes=strip_admin_suffixes
            )
        )
    return variants


def _normalized_name_variants(text: str, *, strip_admin_suffixes: bool) -> set[str]:
    normalized = _normalize_search_text(text)
    if not normalized:
        return set()

    variants = {normalized}
    if "," in normalized:
        primary = normalized.split(",", 1)[0].strip()
        if primary:
            variants.add(primary)

    for suffix in (" china", " 中国"):
        if normalized.endswith(suffix):
            stripped = normalized[: -len(suffix)].rstrip(", ")
            if stripped:
                variants.add(stripped)

    if strip_admin_suffixes:
        stripped_variants = {_strip_admin_name_suffix(value) for value in variants}
        variants.update(value for value in stripped_variants if value)
    return variants


def _normalize_search_text(text: str) -> str:
    return " ".join(text.replace("，", ",").split()).strip().casefold()


def _strip_admin_name_suffix(text: str) -> str:
    for suffix in ADMIN_NAME_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)].strip()
    return text


def build_geocode_search_plan(query: str) -> list[tuple[str, str | None]]:
    normalized = " ".join(query.split()).strip()
    if not normalized:
        return []

    plan: list[tuple[str, str | None]] = []
    candidate_queries = build_geocode_queries(normalized)
    if _contains_cjk(normalized) and not _is_known_foreign_city(normalized):
        plan.extend((candidate, "cn") for candidate in candidate_queries)
    plan.extend((candidate, None) for candidate in candidate_queries)

    deduped: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for item in plan:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def build_geocode_queries(query: str) -> list[str]:
    normalized = " ".join(query.split()).strip()
    if not normalized:
        return []

    queries = [normalized]
    if _contains_cjk(normalized):
        queries.append(f"{normalized}, 中国")
        if not normalized.endswith(("市", "区", "县", "州", "旗", "镇")):
            queries.append(f"{normalized}市")
            queries.append(f"{normalized}市, 中国")
    elif "," not in normalized:
        queries.append(f"{normalized}, China")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in queries:
        compact = " ".join(item.split()).strip()
        if compact and compact not in seen:
            seen.add(compact)
            deduped.append(compact)
    return deduped


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _is_known_foreign_city(query: str) -> bool:
    normalized = " ".join(query.split()).strip()
    return normalized in KNOWN_FOREIGN_CITIES


def _nominatim_search(
    query: str,
    *,
    countrycodes: str | None,
    request: PosterRequest,
    client: CachedHttpClient,
) -> list[dict]:
    global LAST_NOMINATIM_REQUEST_AT

    now = time.monotonic()
    wait_seconds = NOMINATIM_MIN_INTERVAL_SECONDS - (now - LAST_NOMINATIM_REQUEST_AT)
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    params = {
        "q": query,
        "format": "jsonv2",
        "limit": str(NOMINATIM_RESULT_LIMIT),
        "addressdetails": "1",
    }
    if countrycodes:
        params["countrycodes"] = countrycodes

    payload = client.request_json(
        "GET",
        f"{request.nominatim_url}/search?{urlencode(params)}",
        headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
    )
    LAST_NOMINATIM_REQUEST_AT = time.monotonic()
    return payload if isinstance(payload, list) else []
