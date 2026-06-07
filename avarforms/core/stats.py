from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import AggregatedRecord, WordFormRecord


GAP_FILTER_META: dict[str, dict[str, str]] = {
    "missing_lemma": {
        "label": "Без леммы",
        "description": "Хотя бы одна запись без леммы",
    },
    "missing_relation": {
        "label": "Без связи",
        "description": "Хотя бы одна запись без грамматической связи",
    },
    "missing_pos": {
        "label": "Без части речи",
        "description": "Хотя бы одна запись без части речи",
    },
    "missing_lemma_and_relation": {
        "label": "Без леммы и связи",
        "description": "Хотя бы одна запись без леммы и без связи",
    },
    "ambiguous_examples": {
        "label": "Неоднозначные примеры",
        "description": "Из примеров av: низкая или средняя уверенность маппинга",
    },
    "low_confidence": {
        "label": "Низкая уверенность",
        "description": "Маппинг не найден или неоднозначен",
    },
    "strange": {
        "label": "Аномалии",
        "description": "Подозрительные записи для ручной проверки",
    },
}


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


def _normalize_sort_key(word: str) -> str:
    return re.sub(r"[1IiｌlL|!ǀӀІ]", "ӏ", word.lower().strip())


def build_gap_filters(
    raw_records: list[WordFormRecord],
    strange_records: list[dict[str, Any]],
) -> dict[str, list[str]]:
    buckets: dict[str, set[str]] = {key: set() for key in GAP_FILTER_META}

    for record in raw_records:
        wf = record.wordform
        if _is_missing(record.lemma):
            buckets["missing_lemma"].add(wf)
        if _is_missing(record.relation):
            buckets["missing_relation"].add(wf)
        if _is_missing(record.pos):
            buckets["missing_pos"].add(wf)
        if _is_missing(record.lemma) and _is_missing(record.relation):
            buckets["missing_lemma_and_relation"].add(wf)
        if record.subsource == "examples" and record.confidence in {"low", "medium"}:
            buckets["ambiguous_examples"].add(wf)
        if record.confidence == "low":
            buckets["low_confidence"].add(wf)

    for item in strange_records:
        wf = item.get("wordform", "")
        if wf:
            buckets["strange"].add(wf)

    return {
        key: sorted(words, key=_normalize_sort_key)
        for key, words in buckets.items()
    }


def write_gap_filters(gap_filters: dict[str, list[str]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_filters: dict[str, dict[str, Any]] = {}

    for filter_id, meta in GAP_FILTER_META.items():
        wordforms = gap_filters.get(filter_id, [])
        filename = f"{filter_id}.txt"
        with (output_dir / filename).open("w", encoding="utf-8") as fh:
            for wordform in wordforms:
                fh.write(wordform + "\n")
        manifest_filters[filter_id] = {
            "id": filter_id,
            "label": meta["label"],
            "description": meta["description"],
            "count": len(wordforms),
            "file": filename,
        }

    manifest = {"filters": manifest_filters}
    manifest_path = output_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return manifest_path


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
