from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True, slots=True)
class WordFormRecord:
    """Single word-form observation from a source."""

    wordform: str
    lemma: str = ""
    relation: str = ""
    pos: str = ""
    source: str = ""
    source_id: str = ""
    subsource: str = ""
    confidence: str = "high"  # high | medium | low
    detail: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def key(self) -> tuple[str, str, str, str, str]:
        return (self.wordform, self.lemma, self.relation, self.pos, self.source)

    def merge_key(self) -> tuple[str, str, str, str, str, str]:
        return (*self.key(), self.subsource)


@dataclass
class AggregatedRecord:
    wordform: str
    lemma: str = ""
    relation: str = ""
    pos: str = ""
    source: str = ""
    count: int = 0
    subsources: dict[str, int] = field(default_factory=dict)
    confidence: str = "high"

    @classmethod
    def from_record(cls, record: WordFormRecord) -> AggregatedRecord:
        agg = cls(
            wordform=record.wordform,
            lemma=record.lemma,
            relation=record.relation,
            pos=record.pos,
            source=record.source,
            count=1,
            confidence=record.confidence,
        )
        if record.subsource:
            agg.subsources[record.subsource] = 1
        return agg

    def absorb(self, record: WordFormRecord) -> None:
        self.count += 1
        if record.subsource:
            self.subsources[record.subsource] = self.subsources.get(record.subsource, 0) + 1
        if record.confidence == "low" and self.confidence == "high":
            self.confidence = "medium"
        elif record.confidence == "low" and self.confidence == "medium":
            pass
        elif record.confidence == "medium" and self.confidence == "high":
            self.confidence = "medium"


@dataclass
class LemmaMapping:
    lemma: str
    relation: str = ""
    pos: str = ""
    note: str = ""


MappingTable = dict[str, LemmaMapping]
