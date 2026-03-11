from __future__ import annotations

from urllib.parse import urlparse

import duckdb

from .models import LocationMetadata, PosterRequest
from .osm import ADMIN_NAME_SUFFIXES

RUNNING_ROUTE_LAYER = "running_route"
DEFAULT_RUNNING_PAGE_BRANCH = "master"
DEFAULT_RUNNING_PAGE_PARQUET_PATH = "run_page/data.parquet"


def load_running_page_routes(
    request: PosterRequest,
) -> list[list[tuple[float, float]]]:
    source = (request.running_page or "").strip()
    if not source:
        return []

    parquet_source = resolve_running_page_parquet_url(source)

    sql = f"""
        SELECT DISTINCT summary_polyline
        FROM read_parquet('{sql_string_literal(parquet_source)}')
        WHERE summary_polyline IS NOT NULL
          AND length(trim(summary_polyline)) > 0
          AND (type IS NULL OR lower(type) LIKE '%run%')
    """
    with duckdb.connect() as connection:
        rows = connection.execute(sql).fetchall()

    routes: list[list[tuple[float, float]]] = []
    for (encoded_path,) in rows:
        try:
            decoded = decode_polyline(str(encoded_path))
        except ValueError:
            continue
        if len(decoded) >= 2:
            routes.append(decoded)
    return routes


def resolve_running_page_parquet_url(source: str) -> str:
    value = source.strip()
    if not value:
        raise ValueError("running_page source is empty.")

    if value.endswith(".parquet") and not value.startswith("http"):
        return value

    if "://" not in value:
        owner, repo, branch = parse_running_page_repo_ref(value)
        return build_raw_github_url(
            owner, repo, branch, DEFAULT_RUNNING_PAGE_PARQUET_PATH
        )

    parsed = urlparse(value)
    if parsed.netloc == "raw.githubusercontent.com":
        return value

    if parsed.netloc != "github.com":
        return value

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"Unsupported running_page source: {source}")

    owner, repo = parts[0], parts[1]
    if len(parts) == 2:
        return build_raw_github_url(
            owner, repo, DEFAULT_RUNNING_PAGE_BRANCH, DEFAULT_RUNNING_PAGE_PARQUET_PATH
        )

    if len(parts) >= 7 and parts[2:5] == ["raw", "refs", "heads"]:
        branch = parts[5]
        file_path = "/".join(parts[6:])
        return build_raw_github_url(owner, repo, branch, file_path)

    if len(parts) >= 5 and parts[2] in {"blob", "raw"}:
        branch = parts[3]
        file_path = "/".join(parts[4:])
        return build_raw_github_url(owner, repo, branch, file_path)

    if value.endswith(".parquet"):
        return value

    raise ValueError(f"Unsupported running_page source: {source}")


def parse_running_page_repo_ref(source: str) -> tuple[str, str, str]:
    owner, sep, repo_ref = source.partition("/")
    if not sep or not owner or not repo_ref:
        raise ValueError("running_page must be an owner/repo slug or a parquet URL.")
    repo, _, branch = repo_ref.partition("@")
    return owner, repo, branch or DEFAULT_RUNNING_PAGE_BRANCH


def build_raw_github_url(owner: str, repo: str, branch: str, file_path: str) -> str:
    return (
        f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/"
        f"{file_path.lstrip('/')}"
    )


def build_running_page_location_filters(
    request: PosterRequest, location: LocationMetadata
) -> list[str]:
    candidates = [request.location or "", location.city, location.label]
    filters: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        for variant in iter_location_variants(candidate):
            if variant not in seen:
                seen.add(variant)
                filters.append(variant)
    return filters


def iter_location_variants(text: str) -> list[str]:
    normalized = normalize_location_text(text)
    if not normalized:
        return []

    variants = [normalized]
    if "," in normalized:
        primary = normalized.split(",", 1)[0].strip()
        if primary:
            variants.append(primary)

    for value in list(variants):
        stripped = strip_admin_suffix(value)
        if stripped:
            variants.append(stripped)

    deduped: list[str] = []
    seen: set[str] = set()
    for value in variants:
        compact = value.strip()
        if compact and compact not in seen:
            seen.add(compact)
            deduped.append(compact)
    return deduped


def normalize_location_text(text: str) -> str:
    return " ".join(text.replace("，", ",").split()).strip().casefold()


def strip_admin_suffix(text: str) -> str:
    for suffix in ADMIN_NAME_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)].strip()
    return text


def decode_polyline(value: str, *, precision: int = 5) -> list[tuple[float, float]]:
    index = 0
    latitude = 0
    longitude = 0
    coordinates: list[tuple[float, float]] = []
    factor = 10**precision

    while index < len(value):
        latitude_delta, index = decode_polyline_value(value, index)
        longitude_delta, index = decode_polyline_value(value, index)
        latitude += latitude_delta
        longitude += longitude_delta
        coordinates.append((longitude / factor, latitude / factor))

    return coordinates


def decode_polyline_value(value: str, index: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if index >= len(value):
            raise ValueError("Invalid polyline: truncated value.")
        byte = ord(value[index]) - 63
        index += 1
        result |= (byte & 0x1F) << shift
        shift += 5
        if byte < 0x20:
            break
    if result & 1:
        return (-(result >> 1) - 1, index)
    return (result >> 1, index)


def sql_string_literal(value: str) -> str:
    return value.replace("'", "''")
