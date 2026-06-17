"""Template for a new source extractor. Copy and adapt."""

from __future__ import annotations

from typing import Iterator

from avarforms.core.extractor import SourceExtractor
from avarforms.core.models import MappingTable, WordFormRecord


class TemplateExtractor(SourceExtractor):
    def extract(self, mappings: MappingTable | None = None) -> Iterator[WordFormRecord]:
        mappings = mappings or {}
        # Yields raw text lines from config["url"] (sources.avar.me) or local config["path"].
        lines = self.open_data_lines()

        # TODO: parse lines and yield WordFormRecord instances
        _ = lines, mappings
        if False:
            yield WordFormRecord(
                wordform="",
                lemma="",
                relation="",
                pos="",
                source=self.source_name,
                subsource="",
            )
