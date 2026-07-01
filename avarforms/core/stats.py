from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import AggregatedRecord, WordFormRecord


STRUCTURED_SUBSOURCES = frozenset({"headword", "explicit_relation", "forms", "gender_forms"})

GAP_FILTER_META: dict[str, dict[str, str]] = {
    "needs_work": {
        "label": "Нужна ручная работа",
        "description": "Есть упоминания без уверенного маппинга",
    },
    "fully_unmapped": {
        "label": "Без маппинга",
        "description": "Нет ни одной записи с найденной леммой",
    },
    "partial": {
        "label": "Частичный маппинг",
        "description": "Есть и ясные записи, и пробелы в других упоминаниях",
    },
    "homograph": {
        "label": "Омонимы",
        "description": "Несколько лемм для одной словоформы — обычно норма",
    },
    "strange": {
        "label": "Аномалии",
        "description": "Словоформы с явными проблемами: цифры, посторонние символы, голая палочка в начале",
    },
}

LEGACY_GAP_FILTERS: dict[str, str] = {
    "missing_lemma": "needs_work",
    "missing_relation": "needs_work",
    "missing_pos": "needs_work",
    "missing_lemma_and_relation": "needs_work",
    "ambiguous_examples": "needs_work",
    "low_confidence": "needs_work",
}

# Characters not expected in Avar wordforms: anything outside Cyrillic, hyphen, palochka.
# Digits and Latin/special chars embedded in a token signal a bad token.
_STRANGE_WORDFORM_RE = re.compile(r"[^а-яёА-ЯЁӀӏ\-]")

FREQ_BUCKETS: list[tuple[str, int, int]] = [
    ("1",       1,   1),
    ("2",       2,   2),
    ("3–5",     3,   5),
    ("6–10",    6,  10),
    ("11–20",  11,  20),
    ("21–50",  21,  50),
    ("51–100", 51, 100),
    ("101–500",101, 500),
    ("501+",   501, 10**9),
]


@dataclass
class BuildStats:
    total_raw_records: int = 0
    total_aggregated_records: int = 0
    per_source_raw: dict[str, int] = field(default_factory=dict)
    per_subsource_raw: dict[str, int] = field(default_factory=dict)
    needs_work_mentions: int = 0
    gap_wordforms: dict[str, int] = field(default_factory=dict)
    gap_mentions: dict[str, int] = field(default_factory=dict)
    top_lemmas: list[tuple[str, int]] = field(default_factory=list)
    top_wordforms: list[tuple[str, int]] = field(default_factory=list)
    top_relations: list[tuple[str, int]] = field(default_factory=list)
    strange_records: list[dict[str, Any]] = field(default_factory=list)
    source_stats: list[dict[str, Any]] = field(default_factory=list)
    freq_distribution: list[dict[str, Any]] = field(default_factory=list)


def _is_missing(value: str) -> bool:
    return not value or not value.strip()


def is_clear_record(record: WordFormRecord) -> bool:
    """Record has enough metadata — no manual mapping work needed."""
    if record.subsource in STRUCTURED_SUBSOURCES and record.lemma:
        return True
    if record.confidence == "high" and record.lemma:
        return True
    if record.subsource == "examples" and record.lemma and record.confidence == "medium":
        return True
    return False


def is_strange_record(record: WordFormRecord) -> bool:
    """Wordform has an obvious structural problem."""
    w = record.wordform
    if not w:
        return False
    if w[0] == "ӏ":
        return True
    if _STRANGE_WORDFORM_RE.search(w):
        return True
    return False


def _group_by_wordform(records: list[WordFormRecord]) -> dict[str, list[WordFormRecord]]:
    grouped: dict[str, list[WordFormRecord]] = defaultdict(list)
    for record in records:
        grouped[record.wordform].append(record)
    return grouped


def _normalize_sort_key(word: str) -> str:
    return re.sub(r"[1IiｌlL|!ǀӀІ]", "ӏ", word.lower().strip())


def build_gaps(raw_records: list[WordFormRecord]) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Build gap wordform lists and mention counts in one pass over grouped records."""
    buckets: dict[str, set[str]] = {key: set() for key in GAP_FILTER_META}
    mention_counts = {key: 0 for key in GAP_FILTER_META}
    grouped = _group_by_wordform(raw_records)

    for wordform, records in grouped.items():
        clear = [record for record in records if is_clear_record(record)]
        unclear = [record for record in records if not is_clear_record(record)]
        clear_lemmas = {record.lemma for record in clear if record.lemma}
        unclear_count = len(unclear)

        if unclear:
            buckets["needs_work"].add(wordform)
            mention_counts["needs_work"] += unclear_count
            if clear:
                buckets["partial"].add(wordform)
                mention_counts["partial"] += unclear_count
            else:
                buckets["fully_unmapped"].add(wordform)
                mention_counts["fully_unmapped"] += unclear_count

        if len(clear_lemmas) > 1:
            buckets["homograph"].add(wordform)
            mention_counts["homograph"] += len(records)

        if any(is_strange_record(record) for record in records):
            buckets["strange"].add(wordform)

    mention_counts["strange"] = sum(1 for record in raw_records if is_strange_record(record))

    gap_filters = {
        key: sorted(words, key=_normalize_sort_key)
        for key, words in buckets.items()
    }
    return gap_filters, mention_counts


def build_gap_filters(raw_records: list[WordFormRecord]) -> dict[str, list[str]]:
    gap_filters, _ = build_gaps(raw_records)
    return gap_filters


def build_gap_mentions(
    raw_records: list[WordFormRecord],
    gap_filters: dict[str, list[str]],
) -> dict[str, int]:
    _, mention_counts = build_gaps(raw_records)
    return mention_counts


def _build_source_stats(aggregated: list[AggregatedRecord]) -> list[dict[str, Any]]:
    """Per-source: unique wordforms, total occurrences, exclusive wordforms."""
    # wordform -> set of sources that have it
    wordform_sources: dict[str, set[str]] = defaultdict(set)
    source_wordforms: dict[str, set[str]] = defaultdict(set)
    source_total: dict[str, int] = defaultdict(int)

    for rec in aggregated:
        wordform_sources[rec.wordform].add(rec.source)
        source_wordforms[rec.source].add(rec.wordform)
        source_total[rec.source] += rec.count

    result = []
    for source, wordforms in source_wordforms.items():
        exclusive = sum(1 for w in wordforms if len(wordform_sources[w]) == 1)
        result.append({
            "source": source,
            "total": source_total[source],
            "unique": len(wordforms),
            "exclusive": exclusive,
        })
    result.sort(key=lambda x: -x["total"])
    return result


def _build_freq_distribution(aggregated: list[AggregatedRecord]) -> list[dict[str, Any]]:
    """Bucket wordforms by total occurrence count across all sources."""
    wordform_total: dict[str, int] = defaultdict(int)
    for rec in aggregated:
        wordform_total[rec.wordform] += rec.count

    bucket_counts = [0] * len(FREQ_BUCKETS)
    for total in wordform_total.values():
        for i, (_, lo, hi) in enumerate(FREQ_BUCKETS):
            if lo <= total <= hi:
                bucket_counts[i] += 1
                break

    return [
        {"label": label, "wordforms": count}
        for (label, _, _), count in zip(FREQ_BUCKETS, bucket_counts)
    ]


def build_stats(
    raw_records: list[WordFormRecord],
    aggregated: list[AggregatedRecord],
    per_source_counts: Counter[str],
    *,
    gap_filters: dict[str, list[str]] | None = None,
    gap_mentions: dict[str, int] | None = None,
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

    if gap_filters is None or gap_mentions is None:
        gap_filters, gap_mentions = build_gaps(raw_records)
    stats.gap_wordforms = {key: len(gap_filters.get(key, [])) for key in GAP_FILTER_META}
    stats.gap_mentions = gap_mentions
    stats.needs_work_mentions = gap_mentions.get("needs_work", 0)

    for record in raw_records:
        subsource_counter[record.subsource or "unknown"] += 1

        if record.lemma:
            lemma_counter[record.lemma] += 1
        wordform_counter[record.wordform] += 1
        if record.relation:
            relation_counter[record.relation] += 1

        if is_strange_record(record):
            reason = (
                "starts_with_palochka"
                if record.wordform and record.wordform[0] == "ӏ"
                else "contains_non_avar_chars"
            )
            stats.strange_records.append(
                {
                    "wordform": record.wordform,
                    "lemma": record.lemma,
                    "relation": record.relation,
                    "source": record.source,
                    "subsource": record.subsource,
                    "reason": reason,
                }
            )

    stats.per_subsource_raw = dict(subsource_counter)
    stats.top_lemmas = lemma_counter.most_common(20)
    stats.top_wordforms = wordform_counter.most_common(20)
    stats.top_relations = relation_counter.most_common(20)
    stats.source_stats = _build_source_stats(aggregated)
    stats.freq_distribution = _build_freq_distribution(aggregated)
    return stats


def write_gap_filters(
    gap_filters: dict[str, list[str]],
    output_dir: Path,
    gap_mentions: dict[str, int] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    gap_mentions = gap_mentions or {}

    for path in output_dir.glob("*.txt"):
        if path.name not in {f"{key}.txt" for key in GAP_FILTER_META}:
            path.unlink()

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
            "mention_count": gap_mentions.get(filter_id, 0),
            "file": filename,
        }

    manifest = {
        "filters": manifest_filters,
        "legacy_filters": LEGACY_GAP_FILTERS,
    }
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
            "Coverage gaps (wordforms / mentions):",
        ]
    )
    for filter_id, meta in GAP_FILTER_META.items():
        wf = stats.gap_wordforms.get(filter_id, 0)
        mentions = stats.gap_mentions.get(filter_id, 0)
        lines.append(f"  {meta['label']}: {wf} / {mentions}")
    lines.extend(
        [
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
