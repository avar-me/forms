from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from avarforms.web.chunking import normalize_word, split_into_chunks, write_chunk_files

from .models import WordFormRecord

SUBSOURCE_ORDER = {
    "headword": 0,
    "explicit_relation": 1,
    "forms": 2,
    "gender_forms": 3,
    "examples": 4,
}


def _mention_key(mention: dict[str, Any]) -> str:
    return json.dumps(mention, ensure_ascii=False, sort_keys=True)


def _build_mention(record: WordFormRecord) -> dict[str, Any]:
    mention: dict[str, Any] = {"subsource": record.subsource or "unknown"}
    if record.lemma:
        mention["lemma"] = record.lemma
    if record.relation:
        mention["relation"] = record.relation
    if record.pos:
        mention["pos"] = record.pos
    if record.confidence != "high":
        mention["confidence"] = record.confidence
    for key, value in record.detail.items():
        if value not in ("", None, []):
            mention[key] = value
    return mention


def build_provenance_entries(records: list[WordFormRecord]) -> dict[str, dict[str, Any]]:
    by_form: dict[str, dict[str, Any]] = {}

    for record in records:
        form_entry = by_form.setdefault(
            record.wordform,
            {"wordform": record.wordform, "sources": {}},
        )
        source_id = record.source_id or "unknown"
        source_entry = form_entry["sources"].setdefault(
            source_id,
            {"id": source_id, "name": record.source, "mentions": [], "_seen": set()},
        )
        mention = _build_mention(record)
        mention_key = _mention_key(mention)
        if mention_key in source_entry["_seen"]:
            continue
        source_entry["_seen"].add(mention_key)
        source_entry["mentions"].append(mention)

    for form_entry in by_form.values():
        for source_entry in form_entry["sources"].values():
            source_entry["mentions"].sort(
                key=lambda mention: (
                    SUBSOURCE_ORDER.get(mention.get("subsource", ""), 99),
                    mention.get("entry", ""),
                    mention.get("av", ""),
                )
            )
            del source_entry["_seen"]

    return by_form


def write_provenance(
    records: list[WordFormRecord],
    dest_dir: Path,
    *,
    source_catalog: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    entries = build_provenance_entries(records)
    wordforms = sorted(entries.keys(), key=normalize_word)
    chunks = split_into_chunks(entries, wordforms)
    chunks_dir = dest_dir / "chunks"
    chunk_info = write_chunk_files(chunks, chunks_dir)

    manifest = {
        "version": "1.0.0",
        "build_date": datetime.now(timezone.utc).isoformat(),
        "total_wordforms": len(wordforms),
        "total_mentions": len(records),
        "sources": source_catalog or [],
        "chunks": chunk_info,
    }
    dest_dir.mkdir(parents=True, exist_ok=True)
    with (dest_dir / "manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    return {
        "wordforms": len(wordforms),
        "mentions": len(records),
        "chunks": len(chunk_info),
        "dest_dir": str(dest_dir),
    }
