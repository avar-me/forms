from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from .models import MappingTable, WordFormRecord


def read_source_text(url: str) -> str:
    """Return a source's text, preferring a local mirror over the network.

    If AVARFORMS_SOURCES_DIR is set (e.g. a checkout of the avar-me/sources repo in CI),
    the file is read from there by its URL path — avoiding flaky GitHub-Pages fetches from
    GitHub Actions. Otherwise it is fetched from the URL (sources.avar.me) with retries.
    """
    mirror = os.environ.get("AVARFORMS_SOURCES_DIR")
    if mirror:
        local = Path(mirror) / urlparse(url).path.lstrip("/")
        if local.is_file():
            return local.read_text(encoding="utf-8")
    return fetch_url_text(url)


def fetch_url_text(url: str, *, retries: int = 4, timeout: int = 120) -> str:
    """Fetch a URL as UTF-8 text, retrying transient network errors.

    Sources are pulled from sources.avar.me at build time (incl. in CI); a single read can
    fail with IncompleteRead / timeouts on a flaky connection, which must not break the build.
    """
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "avarforms-build"})
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return response.read().decode("utf-8")
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts: {last_error}")


class SourceExtractor(ABC):
    """Base class for per-source word-form extractors."""

    def __init__(self, source_id: str, source_name: str, config: dict[str, Any], root: Path):
        self.source_id = source_id
        self.source_name = source_name
        self.config = config
        self.root = root

    @abstractmethod
    def extract(self, mappings: MappingTable | None = None) -> Iterator[WordFormRecord]:
        ...

    def resolve_path(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute():
            return path
        return self.root / path

    def open_data_lines(self) -> Iterator[str]:
        """Yield raw text lines for this source from a remote URL or local path.

        Sources are fetched fresh from `config["url"]` on every build (no cache).
        A local `config["path"]` is supported as a fallback for offline data.
        """
        url = self.config.get("url")
        if url:
            yield from read_source_text(url).splitlines()
            return

        path = self.resolve_path(self.config["path"])
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                yield line


def load_mappings(root: Path, mapping_files: list[str]) -> MappingTable:
    table: MappingTable = {}
    for rel in mapping_files:
        path = root / rel
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        from .models import LemmaMapping

        for wordform, payload in data.get("wordforms", {}).items():
            if isinstance(payload, str):
                table[wordform] = LemmaMapping(lemma=payload)
            else:
                table[wordform] = LemmaMapping(
                    lemma=payload.get("lemma", ""),
                    relation=payload.get("relation", ""),
                    pos=payload.get("pos", ""),
                    note=payload.get("note", ""),
                )
    return table
