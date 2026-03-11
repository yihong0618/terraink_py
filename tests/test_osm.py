from __future__ import annotations

import threading
from pathlib import Path
from typing import cast

from terraink_py.http import CachedHttpClient
from terraink_py.models import Bounds, PosterRequest
from terraink_py.osm import (
    _fetch_overpass_parallel,
    _nominatim_search,
    _reverse_geocode,
    _select_best_nominatim_result,
    build_geocode_queries,
    build_geocode_search_plan,
    build_overpass_query,
    classify_line_layer,
    classify_polygon_layer,
    close_path,
    extract_paths,
    fetch_osm_layers,
    geometry_to_points,
    is_closed_shape,
    KNOWN_FOREIGN_CITIES,
    PARK_LEISURE_VALUES,
    PARK_LANDUSE_VALUES,
    PARK_NATURAL_VALUES,
    RAIL_CLASSES,
    ROAD_MAJOR_CLASSES,
    ROAD_MINOR_HIGH_CLASSES,
    ROAD_MINOR_LOW_CLASSES,
    ROAD_MINOR_MID_CLASSES,
    ROAD_PATH_CLASSES,
    WATER_LANDUSE_VALUES,
)


class StubOverpassClient:
    def __init__(self) -> None:
        self.slow_started = threading.Event()
        self.release_slow = threading.Event()
        self.slow_finished = threading.Event()

    def request_json(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        del method, body, headers
        if url == "slow":
            self.slow_started.set()
            self.release_slow.wait(timeout=1.0)
            self.slow_finished.set()
            return {"endpoint": url}
        if url == "fast":
            self.slow_started.wait(timeout=1.0)
            return {"endpoint": url}
        raise RuntimeError(f"unexpected endpoint: {url}")


class RecordingClient:
    def __init__(self, payload: dict | list[dict]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict | list[dict]:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "body": body,
                "headers": headers or {},
            }
        )
        return self.payload


class TestBuildOverpassQuery:
    def test_empty_query_when_no_features(self) -> None:
        bounds = Bounds(south=0.0, west=0.0, north=1.0, east=1.0)
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.5,
            lon=0.5,
            include_buildings=False,
            include_roads=False,
            include_road_path=False,
            include_road_minor_low=False,
            include_rail=False,
            include_water=False,
            include_parks=False,
            include_aeroway=False,
        )
        query = build_overpass_query(bounds, request)
        assert query == ""

    def test_buildings_query(self) -> None:
        bounds = Bounds(south=0.0, west=0.0, north=1.0, east=1.0)
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.5,
            lon=0.5,
            include_buildings=True,
            include_roads=False,
            include_rail=False,
            include_water=False,
            include_parks=False,
            include_aeroway=False,
        )
        query = build_overpass_query(bounds, request)
        assert '["building"]' in query
        assert "way" in query
        assert "relation" in query

    def test_roads_query(self) -> None:
        bounds = Bounds(south=0.0, west=0.0, north=1.0, east=1.0)
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.5,
            lon=0.5,
            include_roads=True,
            include_buildings=False,
            include_rail=False,
            include_water=False,
            include_parks=False,
            include_aeroway=False,
        )
        query = build_overpass_query(bounds, request)
        assert '["highway"]' in query

    def test_water_query(self) -> None:
        bounds = Bounds(south=0.0, west=0.0, north=1.0, east=1.0)
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.5,
            lon=0.5,
            include_water=True,
            include_buildings=False,
            include_roads=False,
            include_rail=False,
            include_parks=False,
            include_aeroway=False,
        )
        query = build_overpass_query(bounds, request)
        assert '["waterway"]' in query
        assert '["natural"="water"]' in query

    def test_parks_query(self) -> None:
        bounds = Bounds(south=0.0, west=0.0, north=1.0, east=1.0)
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.5,
            lon=0.5,
            include_parks=True,
            include_buildings=False,
            include_roads=False,
            include_rail=False,
            include_water=False,
            include_aeroway=False,
        )
        query = build_overpass_query(bounds, request)
        assert '["leisure"' in query
        assert '["landuse"' in query
        assert '["natural"' in query

    def test_aeroway_query(self) -> None:
        bounds = Bounds(south=0.0, west=0.0, north=1.0, east=1.0)
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.5,
            lon=0.5,
            include_aeroway=True,
            include_buildings=False,
            include_roads=False,
            include_rail=False,
            include_water=False,
            include_parks=False,
        )
        query = build_overpass_query(bounds, request)
        assert '["aeroway"]' in query

    def test_rail_query(self) -> None:
        bounds = Bounds(south=0.0, west=0.0, north=1.0, east=1.0)
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.5,
            lon=0.5,
            include_rail=True,
            include_buildings=False,
            include_roads=False,
            include_water=False,
            include_parks=False,
            include_aeroway=False,
        )
        query = build_overpass_query(bounds, request)
        assert '["railway"]' in query

    def test_query_format(self) -> None:
        bounds = Bounds(south=0.0, west=0.0, north=1.0, east=1.0)
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.5,
            lon=0.5,
            include_roads=True,
        )
        query = build_overpass_query(bounds, request)
        assert query.startswith("[out:json]")
        assert "[timeout:" in query
        assert query.endswith("out geom qt;")

    def test_bbox_format(self) -> None:
        bounds = Bounds(south=1.5, west=2.5, north=3.5, east=4.5)
        request = PosterRequest(
            output=Path("test.png"),
            lat=2.5,
            lon=3.5,
            include_roads=True,
        )
        query = build_overpass_query(bounds, request)
        assert "(1.500000,2.500000,3.500000,4.500000)" in query


class TestFetchOverpassParallel:
    def test_returns_first_success_without_waiting_for_slower_endpoints(self) -> None:
        client = StubOverpassClient()
        result: dict[str, dict | None] = {"payload": None}
        finished = threading.Event()

        def call_fetch() -> None:
            result["payload"] = _fetch_overpass_parallel(
                "query",
                ["slow", "fast"],
                cast(CachedHttpClient, client),
            )
            finished.set()

        thread = threading.Thread(target=call_fetch)
        thread.start()

        assert client.slow_started.wait(timeout=0.5)
        assert finished.wait(timeout=0.2)
        assert result["payload"] == {"endpoint": "fast"}

        client.release_slow.set()
        assert client.slow_finished.wait(timeout=1.0)
        thread.join(timeout=1.0)


class TestFetchOsmLayersProgress:
    def test_reports_progress_updates(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "terraink_py.osm._fetch_overpass_payload",
            lambda query, request, client: {"elements": []},
        )
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.5,
            lon=0.5,
            include_roads=True,
        )
        updates: list[tuple[int, str]] = []

        fetch_osm_layers(
            Bounds(south=0.0, west=0.0, north=1.0, east=1.0),
            request,
            cast(CachedHttpClient, object()),
            progress_callback=lambda percent, message: updates.append(
                (percent, message)
            ),
        )

        assert updates[0] == (35, "Fetching OpenStreetMap data")
        assert updates[1] == (45, "Parsing OpenStreetMap features")
        assert updates[-1] == (55, "Map data ready")


class TestClassifyPolygonLayer:
    def test_building_classification(self) -> None:
        tags = {"building": "yes"}
        assert classify_polygon_layer(tags) == "buildings"

    def test_water_classification(self) -> None:
        tags = {"natural": "water"}
        assert classify_polygon_layer(tags) == "water"

    def test_water_landuse_classification(self) -> None:
        for value in WATER_LANDUSE_VALUES:
            tags = {"landuse": value}
            assert classify_polygon_layer(tags) == "water"

    def test_parks_leisure_classification(self) -> None:
        for value in PARK_LEISURE_VALUES:
            tags = {"leisure": value}
            assert classify_polygon_layer(tags) == "parks"

    def test_parks_landuse_classification(self) -> None:
        for value in PARK_LANDUSE_VALUES:
            tags = {"landuse": value}
            assert classify_polygon_layer(tags) == "parks"

    def test_parks_natural_classification(self) -> None:
        for value in PARK_NATURAL_VALUES:
            tags = {"natural": value}
            assert classify_polygon_layer(tags) == "parks"

    def test_aeroway_classification(self) -> None:
        tags = {"aeroway": "aerodrome"}
        assert classify_polygon_layer(tags) == "aeroway"

    def test_no_classification(self) -> None:
        tags = {"highway": "residential"}
        assert classify_polygon_layer(tags) is None

    def test_empty_tags(self) -> None:
        assert classify_polygon_layer({}) is None


class TestClassifyLineLayer:
    def test_waterway_classification(self) -> None:
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.0,
            lon=0.0,
            include_water=True,
        )
        for waterway in ["river", "canal", "stream", "ditch"]:
            tags = {"waterway": waterway}
            assert classify_line_layer(tags, request) == "waterway"

    def test_rail_classification(self) -> None:
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.0,
            lon=0.0,
            include_rail=True,
        )
        for railway in RAIL_CLASSES:
            tags = {"railway": railway}
            assert classify_line_layer(tags, request) == "rail"

    def test_road_major_classification(self) -> None:
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.0,
            lon=0.0,
            include_roads=True,
        )
        for highway in ROAD_MAJOR_CLASSES:
            tags = {"highway": highway}
            assert classify_line_layer(tags, request) == "road_major"

    def test_road_minor_high_classification(self) -> None:
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.0,
            lon=0.0,
            include_roads=True,
        )
        for highway in ROAD_MINOR_HIGH_CLASSES:
            tags = {"highway": highway}
            assert classify_line_layer(tags, request) == "road_minor_high"

    def test_road_minor_mid_classification(self) -> None:
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.0,
            lon=0.0,
            include_roads=True,
        )
        for highway in ROAD_MINOR_MID_CLASSES:
            tags = {"highway": highway}
            assert classify_line_layer(tags, request) == "road_minor_mid"

    def test_road_minor_low_classification(self) -> None:
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.0,
            lon=0.0,
            include_roads=True,
            include_road_minor_low=True,
        )
        for highway in ROAD_MINOR_LOW_CLASSES:
            tags = {"highway": highway}
            assert classify_line_layer(tags, request) == "road_minor_low"

    def test_road_path_classification(self) -> None:
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.0,
            lon=0.0,
            include_road_path=True,
        )
        for highway in ROAD_PATH_CLASSES:
            tags = {"highway": highway}
            assert classify_line_layer(tags, request) == "road_path"

    def test_no_highway_returns_none(self) -> None:
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.0,
            lon=0.0,
            include_roads=True,
        )
        tags = {"name": "Some Road"}
        assert classify_line_layer(tags, request) is None

    def test_roads_disabled(self) -> None:
        request = PosterRequest(
            output=Path("test.png"),
            lat=0.0,
            lon=0.0,
            include_roads=False,
        )
        tags = {"highway": "primary"}
        assert classify_line_layer(tags, request) is None


class TestGeometryToPoints:
    def test_basic_conversion(self) -> None:
        geometry = [
            {"lon": 1.0, "lat": 2.0},
            {"lon": 3.0, "lat": 4.0},
        ]
        points = geometry_to_points(geometry)
        assert points == [(1.0, 2.0), (3.0, 4.0)]

    def test_missing_coordinates_filtered(self) -> None:
        geometry = [
            {"lon": 1.0, "lat": 2.0},
            {"lat": 4.0},  # Missing lon
            {"lon": 5.0},  # Missing lat
            {"lon": 7.0, "lat": 8.0},
        ]
        points = geometry_to_points(geometry)
        assert points == [(1.0, 2.0), (7.0, 8.0)]

    def test_empty_geometry(self) -> None:
        assert geometry_to_points([]) == []


class TestClosePath:
    def test_already_closed(self) -> None:
        path = [(0, 0), (1, 0), (1, 1), (0, 0)]
        result = close_path(path)
        assert result == path

    def test_not_closed(self) -> None:
        path = [(0, 0), (1, 0), (1, 1)]
        result = close_path(path)
        assert result == [(0, 0), (1, 0), (1, 1), (0, 0)]

    def test_too_short(self) -> None:
        path = [(0, 0), (1, 0)]
        result = close_path(path)
        assert result == path

    def test_single_point(self) -> None:
        path = [(0, 0)]
        result = close_path(path)
        assert result == path


class TestIsClosedShape:
    def test_explicitly_closed(self) -> None:
        path = [(0, 0), (1, 0), (1, 1), (0, 0)]
        assert is_closed_shape(path, {}) is True

    def test_area_tag(self) -> None:
        # Need at least 4 points for area tag to work (path[0] != path[-1] check needs 4 points)
        path = [(0, 0), (1, 0), (1, 1), (0, 1)]
        assert is_closed_shape(path, {"area": "yes"}) is True

    def test_too_short(self) -> None:
        path = [(0, 0), (1, 0), (1, 1)]
        assert is_closed_shape(path, {}) is False

    def test_not_closed_no_tag(self) -> None:
        path = [(0, 0), (1, 0), (1, 1), (0, 1)]
        assert is_closed_shape(path, {}) is False


class TestExtractPaths:
    def test_way_element(self) -> None:
        element = {
            "type": "way",
            "geometry": [
                {"lon": 0.0, "lat": 0.0},
                {"lon": 1.0, "lat": 1.0},
            ],
        }
        paths = extract_paths(element, polygon=False)
        assert len(paths) == 1
        assert paths[0] == [(0.0, 0.0), (1.0, 1.0)]

    def test_way_polygon(self) -> None:
        element = {
            "type": "way",
            "geometry": [
                {"lon": 0.0, "lat": 0.0},
                {"lon": 1.0, "lat": 0.0},
                {"lon": 1.0, "lat": 1.0},
                {"lon": 0.0, "lat": 1.0},
                {"lon": 0.0, "lat": 0.0},
            ],
            "tags": {},
        }
        paths = extract_paths(element, polygon=True)
        assert len(paths) == 1


class TestBuildGeocodeQueries:
    def test_simple_query(self) -> None:
        queries = build_geocode_queries("Beijing")
        assert "Beijing" in queries

    def test_cjk_query(self) -> None:
        queries = build_geocode_queries("北京")
        assert "北京" in queries
        assert "北京, 中国" in queries

    def test_cjk_with_suffix(self) -> None:
        queries = build_geocode_queries("上海")
        assert "上海市" in queries
        assert "上海市, 中国" in queries

    def test_with_comma_not_appended(self) -> None:
        queries = build_geocode_queries("Beijing, China")
        assert queries == ["Beijing, China"]

    def test_whitespace_normalization(self) -> None:
        queries = build_geocode_queries("  Beijing   China  ")
        assert "Beijing China" in queries

    def test_empty_query(self) -> None:
        assert build_geocode_queries("") == []


class TestBuildGeocodeSearchPlan:
    def test_simple_plan(self) -> None:
        plan = build_geocode_search_plan("Beijing")
        assert ("Beijing", None) in plan

    def test_cjk_plan_includes_cn_code(self) -> None:
        plan = build_geocode_search_plan("北京")
        assert ("北京", "cn") in plan
        assert ("北京", None) in plan

    def test_known_foreign_city_no_cn_code(self) -> None:
        for city in KNOWN_FOREIGN_CITIES:
            plan = build_geocode_search_plan(city)
            codes = [code for _, code in plan]
            assert "cn" not in codes

    def test_deduplication(self) -> None:
        # Should not have duplicate entries
        plan = build_geocode_search_plan("Beijing")
        assert len(plan) == len(set(plan))


class TestSelectBestNominatimResult:
    def test_prefers_city_place_over_administrative_boundary(self) -> None:
        results = [
            {
                "name": "开封市",
                "category": "boundary",
                "type": "administrative",
                "addresstype": "region",
                "importance": 0.6032419272965156,
                "place_rank": 10,
                "lat": "34.6041670",
                "lon": "114.4972220",
                "address": {
                    "region": "开封市",
                    "state": "河南省",
                    "country": "中国",
                },
            },
            {
                "name": "开封市",
                "category": "place",
                "type": "city",
                "addresstype": "city",
                "importance": 0.6032419272965156,
                "place_rank": 16,
                "lat": "34.7990966",
                "lon": "114.3054796",
                "address": {
                    "city": "开封市",
                    "district": "龙亭区",
                    "state": "河南省",
                    "country": "中国",
                },
            },
        ]

        selected = _select_best_nominatim_result("开封市", results)

        assert selected["category"] == "place"
        assert selected["type"] == "city"
        assert selected["lat"] == "34.7990966"

    def test_keeps_exact_name_match_over_more_generic_place(self) -> None:
        results = [
            {
                "name": "河南省",
                "category": "boundary",
                "type": "administrative",
                "addresstype": "state",
                "importance": 0.8,
                "place_rank": 8,
                "address": {
                    "state": "河南省",
                    "country": "中国",
                },
            },
            {
                "name": "河南",
                "category": "place",
                "type": "city",
                "addresstype": "city",
                "importance": 0.9,
                "place_rank": 16,
                "address": {
                    "city": "河南",
                    "country": "中国",
                },
            },
        ]

        selected = _select_best_nominatim_result("河南省", results)

        assert selected["name"] == "河南省"


class TestNominatimLanguageHeaders:
    def test_search_uses_english_for_latin_request(self, monkeypatch) -> None:
        monkeypatch.setattr("terraink_py.osm.time.sleep", lambda _: None)
        client = RecordingClient([])

        _nominatim_search(
            "Georges River Council",
            countrycodes=None,
            request=PosterRequest(
                output=Path("test.png"),
                location="Georges River Council",
            ),
            client=cast(CachedHttpClient, client),
        )

        headers = cast(dict[str, str], client.calls[0]["headers"])
        assert headers["Accept-Language"].startswith("en")

    def test_search_uses_chinese_for_cjk_request(self, monkeypatch) -> None:
        monkeypatch.setattr("terraink_py.osm.time.sleep", lambda _: None)
        client = RecordingClient([])

        _nominatim_search(
            "开封",
            countrycodes=None,
            request=PosterRequest(
                output=Path("test.png"),
                location="开封",
            ),
            client=cast(CachedHttpClient, client),
        )

        headers = cast(dict[str, str], client.calls[0]["headers"])
        assert headers["Accept-Language"].startswith("zh-CN")

    def test_explicit_language_overrides_auto_detection(self, monkeypatch) -> None:
        monkeypatch.setattr("terraink_py.osm.time.sleep", lambda _: None)
        client = RecordingClient([])

        _nominatim_search(
            "Sydney",
            countrycodes=None,
            request=PosterRequest(
                output=Path("test.png"),
                location="Sydney",
                language="zh",
            ),
            client=cast(CachedHttpClient, client),
        )

        headers = cast(dict[str, str], client.calls[0]["headers"])
        assert headers["Accept-Language"].startswith("zh-CN")

    def test_reverse_geocode_uses_request_language(self) -> None:
        client = RecordingClient(
            {
                "lat": "-33.9682",
                "lon": "151.1355",
                "display_name": "Georges River Council, New South Wales, Australia",
                "address": {
                    "city": "Georges River Council",
                    "country": "Australia",
                },
            }
        )

        _reverse_geocode(
            -33.9682,
            151.1355,
            PosterRequest(
                output=Path("test.png"),
                lat=-33.9682,
                lon=151.1355,
                title="Georges River Council",
            ),
            cast(CachedHttpClient, client),
        )

        headers = cast(dict[str, str], client.calls[0]["headers"])
        assert headers["Accept-Language"].startswith("en")


class TestKnownForeignCities:
    def test_known_cities(self) -> None:
        # Basic sanity check
        assert "东京" in KNOWN_FOREIGN_CITIES
        assert "伦敦" in KNOWN_FOREIGN_CITIES
        assert "纽约" in KNOWN_FOREIGN_CITIES
        assert len(KNOWN_FOREIGN_CITIES) > 0
