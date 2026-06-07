from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import AggregatedRecord, WordFormRecord


@dataclass
class BuildStats:
    total_raw_records: int = 0
    total_aggregated_records: int = 0
    per_source_raw: dict[str, int] = field(default_factory=dict)
    per_subsource_raw: dict[str, int] = field(default_factory=dict)
    missing_lemma: int = 0
    missing_relation: int = 0
    missing_pos: int = 0
    missing_lemma_and_relation: int = 0
    low_confidence: int = 0
    top_lemmas: list[tuple[str, int]] = field(default_factory=list)
    top_wordforms: list[tuple[str, int]] = field(default_factory=list)
    top_relations: list[tuple[str, int]] = field(default_factory=list)
    ambiguous_examples: int = 0
    unmatched_example_tokens: int = 0
    strange_records: list[dict[str, Any]] = field(default_factory=list)


def _is_missing(value: str) -> bool:
    return not value or not value.strip()


def build_stats(
    raw_records: list[WordFormRecord],
    aggregated: list[AggregatedRecord],
    per_source_counts: Counter[str],
) -> BuildStats:
    stats = BuildStats(
        total_raw_records=len(raw_records),
        total_aggregated_records=len(aggregated),
        per_source_raw=dict(per_source_counts),
    )

    lemma_counter: Counter[str] = Counter()
    wordform_counter: Counter[str] = Counter()
    relation_counter: Counter[str] = Counter()
    subsource_counter: Counter[str] = Counter()

    for record in raw_records:
        subsource_counter[record.subsource or "unknown"] += 1
        if _is_missing(record.lemma):
            stats.missing_lemma += 1
        if _is_missing(record.relation):
            stats.missing_relation += 1
        if _is_missing(record.pos):
            stats.missing_pos += 1
        if _is_missing(record.lemma) and _is_missing(record.relation):
            stats.missing_lemma_and_relation += 1
        if record.confidence == "low":
            stats.low_confidence += 1
        if record.subsource == "examples" and record.confidence in {"low", "medium"}:
            stats.ambiguous_examples += 1
        if record.subsource == "examples" and _is_missing(record.lemma):
            stats.unmatched_example_tokens += 1

        if record.lemma:
            lemma_counter[record.lemma] += 1
        wordform_counter[record.wordform] += 1
        if record.relation:
            relation_counter[record.relation] += 1

        if record.wordform == record.lemma and record.relation and record.relation != "именительный":
            stats.strange_records.append(
                {
                    "wordform": record.wordform,
                    "lemma": record.lemma,
                    "relation": record.relation,
                    "source": record.source,
                    "subsource": record.subsource,
                    "reason": "lemma_equals_wordform_with_non_nominative_relation",
                }
            )

    stats.per_subsource_raw = dict(subsource_counter)
    stats.top_lemmas = lemma_counter.most_common(20)
    stats.top_wordforms = wordform_counter.most_common(20)
    stats.top_relations = relation_counter.most_common(20)
    return stats


def write_stats(stats: BuildStats, json_path: Path, txt_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(asdict(stats), fh, ensure_ascii=False, indent=2)

    lines = [
        "=== Avar wordforms build statistics ===",
        "",
        f"Raw records:        {stats.total_raw_records}",
        f"Aggregated records: {stats.total_aggregated_records}",
        "",
        "Per source:",
    ]
    for source, count in sorted(stats.per_source_raw.items()):
        lines.append(f"  - {source}: {count}")
    lines.extend(
        [
            "",
            "Per subsource:",
        ]
    )
    for subsource, count in sorted(stats.per_subsource_raw.items()):
        lines.append(f"  - {subsource}: {count}")
    lines.extend(
        [
            "",
            "Coverage gaps:",
            f"  Missing lemma:              {stats.missing_lemma}",
            f"  Missing relation:           {stats.missing_relation}",
            f"  Missing POS:                {stats.missing_pos}",
            f"  Missing lemma & relation:   {stats.missing_lemma_and_relation}",
            f"  Low confidence:             {stats.low_confidence}",
            f"  Ambiguous examples:         {stats.ambiguous_examples}",
            f"  Unmatched example tokens:   {stats.unmatched_example_tokens}",
            "",
            "Top lemmas:",
        ]
    )
    for lemma, count in stats.top_lemmas:
        lines.append(f"  {lemma}: {count}")
    lines.extend(["", "Top wordforms:"])
    for wordform, count in stats.top_wordforms:
        lines.append(f"  {wordform}: {count}")
    lines.extend(["", "Top relations:"])
    for relation, count in stats.top_relations:
        lines.append(f"  {relation}: {count}")
    if stats.strange_records:
        lines.extend(["", f"Strange records ({len(stats.strange_records)}):"])
        for item in stats.strange_records[:20]:
            lines.append(f"  - {item}")

    with txt_path.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
