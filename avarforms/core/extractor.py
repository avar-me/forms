from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterator

from .models import MappingTable, WordFormRecord


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
