from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from urllib import error, request


class HttpRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CachedHttpClient:
    def __init__(
        self, cache_dir: Path | None, user_agent: str, timeout_seconds: int
    ) -> None:
        self.cache_dir = cache_dir
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def request_json(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        payload = self.request_bytes(method, url, body=body, headers=headers)
        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to decode JSON from {url}") from exc

    def request_bytes(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        req_headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        }
        if headers:
            req_headers.update(headers)

        cache_path = self._cache_path(method, url, body, req_headers)
        if cache_path is not None and cache_path.exists():
            return cache_path.read_bytes()

        req = request.Request(
            url, data=body, headers=req_headers, method=method.upper()
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                payload = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    payload = gzip.decompress(payload)
        except error.HTTPError as exc:
            snippet = exc.read(400).decode("utf-8", errors="replace")
            raise HttpRequestError(
                f"{method.upper()} {url} failed with HTTP {exc.code}: {snippet}",
                status_code=exc.code,
            ) from exc
        except error.URLError as exc:
            raise HttpRequestError(
                f"{method.upper()} {url} failed: {exc.reason}"
            ) from exc

        if cache_path is not None:
            cache_path.write_bytes(payload)
        return payload

    def _cache_path(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: dict[str, str],
    ) -> Path | None:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha256()
        digest.update(method.upper().encode("utf-8"))
        digest.update(b"\0")
        digest.update(url.encode("utf-8"))
        digest.update(b"\0")
        for key, value in sorted(
            (name.casefold(), item) for name, item in headers.items()
        ):
            digest.update(key.encode("utf-8"))
            digest.update(b"\0")
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
        if body:
            digest.update(body)
        return self.cache_dir / f"{digest.hexdigest()}.bin"
