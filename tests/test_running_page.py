from __future__ import annotations

from pathlib import Path

import duckdb

from terraink_py.models import PosterRequest
from terraink_py.running_page import (
    decode_polyline,
    load_running_page_routes,
    resolve_running_page_parquet_url,
)


def test_resolve_running_page_parquet_url_from_repo_slug() -> None:
    assert (
        resolve_running_page_parquet_url("yihong0618/run")
        == "https://raw.githubusercontent.com/yihong0618/run/master/run_page/data.parquet"
    )


def test_resolve_running_page_parquet_url_from_blob_url() -> None:
    assert (
        resolve_running_page_parquet_url(
            "https://github.com/yihong0618/run/blob/master/run_page/data.parquet"
        )
        == "https://raw.githubusercontent.com/yihong0618/run/master/run_page/data.parquet"
    )


def test_resolve_running_page_parquet_url_from_github_raw_heads_url() -> None:
    assert (
        resolve_running_page_parquet_url(
            "https://github.com/yihong0618/run/raw/refs/heads/master/run_page/data.parquet"
        )
        == "https://raw.githubusercontent.com/yihong0618/run/master/run_page/data.parquet"
    )


def test_decode_polyline_returns_lon_lat_pairs() -> None:
    assert decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [
        (-120.2, 38.5),
        (-120.95, 40.7),
        (-126.453, 43.252),
    ]


def test_load_running_page_routes_loads_all_runs(
    tmp_path: Path,
) -> None:
    parquet_path = tmp_path / "runs.parquet"
    connection = duckdb.connect()
    connection.execute("""
        CREATE TABLE runs (
            type VARCHAR,
            location_country VARCHAR,
            summary_polyline VARCHAR
        )
        """)
    connection.execute("""
        INSERT INTO runs VALUES
            ('Run', '高能街, 甘井子区, 大连市, 辽宁省, 中国', '_p~iF~ps|U_ulLnnqC_mqNvxq`@'),
            ('Ride', '高能街, 甘井子区, 大连市, 辽宁省, 中国', '_ulLnnqC_mqNvxq`@_mqNvxq`@'),
            ('Run', '海淀区, 北京市, 中国', '_ulLnnqC_mqNvxq`@_mqNvxq`@')
        """)
    connection.execute(f"COPY runs TO '{parquet_path.as_posix()}' (FORMAT PARQUET)")
    connection.close()

    routes = load_running_page_routes(
        PosterRequest(
            output=tmp_path / "output.png",
            location="大连",
            running_page=parquet_path.as_posix(),
        ),
    )

    # Returns both Run rows (Dalian + Beijing), skipping the Ride
    assert len(routes) == 2
