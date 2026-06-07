"""Template for a new source extractor. Copy and adapt."""

from __future__ import annotations

from typing import Iterator

from avarforms.core.extractor import SourceExtractor
from avarforms.core.models import MappingTable, WordFormRecord


class TemplateExtractor(SourceExtractor):
    def extract(self, mappings: MappingTable | None = None) -> Iterator[WordFormRecord]:
        mappings = mappings or {}
        data_path = self.resolve_path(self.config["path"])

        # TODO: read data_path and yield WordFormRecord instances
        _ = data_path, mappings
        if False:
            yield WordFormRecord(
                wordform="",
                lemma="",
                relation="",
                pos="",
                source=self.source_name,
                subsource="",
            )
