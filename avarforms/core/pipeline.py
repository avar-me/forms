from __future__ import annotations

import csv
import importlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .extractor import SourceExtractor, load_mappings
from .models import AggregatedRecord, WordFormRecord
from .provenance import write_provenance
from .stats import build_gaps, build_stats, is_clear_record, write_gap_filters, write_stats
from avarforms.web.chunking import normalize_word


CSV_COLUMNS = ["wordform", "lemma", "relation", "pos", "source", "count"]


def load_sources_config(root: Path) -> dict[str, Any]:
    config_path = root / "config" / "sources.json"
    with config_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _instantiate_extractor(root: Path, spec: dict[str, Any]) -> SourceExtractor:
    module = importlib.import_module(spec["module"])
    cls = getattr(module, spec["class"])
    return cls(
        source_id=spec["id"],
        source_name=spec["name"],
        config=spec.get("config", {}),
        root=root,
    )


def _record_template_rank(record: WordFormRecord) -> tuple[int, int, int]:
    confidence_rank = {"high": 2, "medium": 1, "low": 0}.get(record.confidence, 0)
    meta_rank = int(bool(record.relation)) + int(bool(record.pos))
    return (int(is_clear_record(record)), confidence_rank, meta_rank)


def _merge_resolved_duplicates(records: list[WordFormRecord]) -> list[WordFormRecord]:
    """Propagate a single known lemma to unmapped rows of the same wordform."""
    grouped: dict[tuple[str, str], list[WordFormRecord]] = {}
    for record in records:
        grouped.setdefault((record.wordform, record.source), []).append(record)

    merged: list[WordFormRecord] = []
    for group in grouped.values():
        mapped = [record for record in group if record.lemma]
        unmapped = [record for record in group if not record.lemma]
        if not unmapped or not mapped:
            merged.extend(group)
            continue

        lemmas = {record.lemma for record in mapped}
        if len(lemmas) != 1:
            merged.extend(group)
            continue

        template = max(mapped, key=_record_template_rank)
        for record in group:
            if record.lemma:
                merged.append(record)
                continue
            merged.append(
                WordFormRecord(
                    wordform=record.wordform,
                    lemma=template.lemma,
                    relation=template.relation,
                    pos=template.pos,
                    source=record.source,
                    source_id=record.source_id,
                    subsource=record.subsource,
                    confidence="medium",
                    detail=record.detail,
                )
            )
    return merged


def _merge_case_variants(records: list[WordFormRecord]) -> list[WordFormRecord]:
    """Fold wordforms that differ only by case/palochka into one canonical surface."""
    grouped: dict[tuple[str, str], list[WordFormRecord]] = {}
    for record in records:
        grouped.setdefault((normalize_word(record.wordform), record.source), []).append(record)

    merged: list[WordFormRecord] = []
    for group in grouped.values():
        canonical = normalize_word(group[0].wordform)
        for record in group:
            if record.wordform == canonical:
                merged.append(record)
                continue
            merged.append(
                WordFormRecord(
                    wordform=canonical,
                    lemma=record.lemma,
                    relation=record.relation,
                    pos=record.pos,
                    source=record.source,
                    source_id=record.source_id,
                    subsource=record.subsource,
                    confidence=record.confidence,
                    detail=record.detail,
                )
            )
    return merged


def _aggregate(records: list[WordFormRecord]) -> list[AggregatedRecord]:
    buckets: dict[tuple[str, str, str, str, str], AggregatedRecord] = {}
    for record in records:
        key = record.key()
        if key in buckets:
            buckets[key].absorb(record)
        else:
            buckets[key] = AggregatedRecord.from_record(record)
    return sorted(buckets.values(), key=lambda r: (r.wordform, r.lemma, r.relation, r.source))


def write_csv(path: Path, rows: list[AggregatedRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "wordform": row.wordform,
                    "lemma": row.lemma,
                    "relation": row.relation,
                    "pos": row.pos,
                    "source": row.source,
                    "count": row.count,
                }
            )


def write_lemma_frequencies(path: Path, rows: list[AggregatedRecord]) -> int:
    """Per-wordform frequency: total occurrences summed over all sources.

    Every unique Avar wordform gets an entry. Sorted most-frequent first; this is
    the base list an орфограф/spell-checker is built from.
    """
    freq: Counter[str] = Counter()
    for row in rows:
        freq[row.wordform] += row.count
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["lemma", "count"])
        for wordform, count in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])):
            writer.writerow([wordform, count])
    return len(freq)


def build_wordforms(root: Path | None = None) -> dict[str, Any]:
    root = root or Path(__file__).resolve().parents[2]
    config = load_sources_config(root)
    mappings = load_mappings(root, config.get("mappings", []))

    all_records: list[WordFormRecord] = []
    per_source_counts: Counter[str] = Counter()

    for spec in config.get("sources", []):
        if not spec.get("enabled", True):
            continue
        extractor = _instantiate_extractor(root, spec)
        source_records = list(extractor.extract(mappings=mappings))
        all_records.extend(source_records)
        per_source_counts[spec["name"]] += len(source_records)

    all_records = _merge_case_variants(all_records)
    all_records = _merge_resolved_duplicates(all_records)
    aggregated = _aggregate(all_records)
    output_cfg = config.get("output", {})
    csv_path = root / output_cfg.get("csv", "output/wordforms.csv")
    stats_json_path = root / output_cfg.get("stats_json", "output/stats.json")
    stats_txt_path = root / output_cfg.get("stats_txt", "output/stats.txt")
    provenance_dir = root / output_cfg.get("provenance_dir", "output/sources")

    source_catalog = [
        {"id": spec["id"], "name": spec["name"]}
        for spec in config.get("sources", [])
        if spec.get("enabled", True)
    ]
    write_provenance(all_records, provenance_dir, source_catalog=source_catalog)

    write_csv(csv_path, aggregated)
    lemma_freq_path = root / output_cfg.get("lemma_freq", "output/lemma_frequencies.csv")
    lemma_count = write_lemma_frequencies(lemma_freq_path, aggregated)
    gap_filters, gap_mentions = build_gaps(all_records)
    stats = build_stats(
        all_records,
        aggregated,
        per_source_counts,
        gap_filters=gap_filters,
        gap_mentions=gap_mentions,
    )
    write_stats(stats, stats_json_path, stats_txt_path)

    gaps_dir = root / output_cfg.get("gaps_dir", "output/gaps")
    write_gap_filters(gap_filters, gaps_dir, gap_mentions)

    return {
        "records_raw": len(all_records),
        "records_aggregated": len(aggregated),
        "csv": str(csv_path),
        "lemma_freq": str(lemma_freq_path),
        "lemma_count": lemma_count,
        "stats_json": str(stats_json_path),
        "stats_txt": str(stats_txt_path),
        "gaps_dir": str(gaps_dir),
        "provenance_dir": str(provenance_dir),
    }
