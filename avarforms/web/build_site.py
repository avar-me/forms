from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_CHUNK_SIZE = 100 * 1024
MAX_WORDFORMS_PER_CHUNK = 500


def normalize_word(word: str) -> str:
    normalized = word.lower().strip()
    normalized = re.sub(r"[1IiｌlL|!ǀӀІ]", "ӏ", normalized)
    return normalized


def get_prefix(word: str, length: int = 2) -> str:
    normalized = normalize_word(word)
    return normalized[: min(length, len(normalized))]


def _safe_chunk_filename(prefix: str) -> str:
    s = prefix.replace("/", "_").replace("\\", "_").replace(":", "_")
    s = s.strip("._") or "_"
    return s


def load_wordforms_csv(path: Path) -> dict[str, list[dict[str, Any]]]:
    by_form: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            wordform = (row.get("wordform") or "").strip()
            if not wordform:
                continue
            by_form[wordform].append(
                {
                    "lemma": (row.get("lemma") or "").strip(),
                    "relation": (row.get("relation") or "").strip(),
                    "pos": (row.get("pos") or "").strip(),
                    "source": (row.get("source") or "").strip(),
                    "count": int(row.get("count") or 0),
                }
            )
    return dict(by_form)


def _browse_entry(entries: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(e["count"] for e in entries)
    primary = max(entries, key=lambda e: e["count"])
    return {
        "lemma": primary["lemma"],
        "relation": primary["relation"],
        "pos": primary["pos"],
        "count": total,
        "variants": len(entries),
    }


def split_into_chunks(entries: dict[str, dict[str, Any]], wordforms: list[str]) -> dict[str, dict[str, Any]]:
    chunks: dict[str, dict[str, Any]] = defaultdict(dict)
    prefix_groups: dict[str, list[str]] = defaultdict(list)
    for wordform in wordforms:
        prefix_groups[get_prefix(wordform, 2)].append(wordform)

    for prefix, group_wordforms in sorted(prefix_groups.items()):
        group_data = {w: entries[w] for w in group_wordforms if w in entries}
        group_json = json.dumps(group_data, ensure_ascii=False)
        group_size = len(group_json.encode("utf-8"))

        if group_size > MAX_CHUNK_SIZE or len(group_wordforms) > MAX_WORDFORMS_PER_CHUNK:
            sub_groups: dict[str, list[str]] = defaultdict(list)
            for wordform in group_wordforms:
                sub_groups[get_prefix(wordform, 3)].append(wordform)
            for sub_prefix, sub_wordforms in sorted(sub_groups.items()):
                chunk_name = sub_prefix if sub_prefix else prefix
                chunks[chunk_name] = {w: entries[w] for w in sub_wordforms if w in entries}
        else:
            chunks[prefix] = group_data
    return chunks


def build_site(root: Path | None = None) -> dict[str, Any]:
    root = root or Path(__file__).resolve().parents[2]
    csv_path = root / "output" / "wordforms.csv"
    stats_path = root / "output" / "stats.json"
    docs_dir = root / "docs"
    data_dir = docs_dir / "data" / "wordforms"

    if not csv_path.exists():
        raise FileNotFoundError(f"Missing {csv_path}. Run ./build.sh first.")

    grouped = load_wordforms_csv(csv_path)
    wordforms = sorted(grouped.keys(), key=lambda w: normalize_word(w))

    entries: dict[str, dict[str, Any]] = {}
    browse: dict[str, dict[str, Any]] = {}
    for wordform, records in grouped.items():
        entries[wordform] = {"wordform": wordform, "entries": records}
        browse[wordform] = _browse_entry(records)

    chunks = split_into_chunks(entries, wordforms)

    data_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir = data_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    with (data_dir / "index.wordforms.txt").open("w", encoding="utf-8") as fh:
        for wordform in wordforms:
            fh.write(wordform + "\n")

    with (data_dir / "browse.json").open("w", encoding="utf-8") as fh:
        json.dump(browse, fh, ensure_ascii=False, separators=(",", ":"))

    by_lemma: dict[str, set[str]] = defaultdict(set)
    for wordform, records in grouped.items():
        for record in records:
            lemma = record.get("lemma", "")
            if lemma:
                by_lemma[lemma].add(wordform)
    lemma_index = {
        lemma: sorted(wordforms, key=normalize_word)
        for lemma, wordforms in sorted(by_lemma.items())
    }
    with (data_dir / "lemma_index.json").open("w", encoding="utf-8") as fh:
        json.dump(lemma_index, fh, ensure_ascii=False, separators=(",", ":"))

    chunk_info: list[dict[str, Any]] = []
    for chunk_name, chunk_data in sorted(chunks.items()):
        safe = _safe_chunk_filename(chunk_name)
        chunk_file = chunks_dir / f"{safe}.json"
        with chunk_file.open("w", encoding="utf-8") as fh:
            json.dump(chunk_data, fh, ensure_ascii=False, indent=2)
        file_hash = hashlib.md5(chunk_file.read_bytes()).hexdigest()[:8]
        chunk_info.append(
            {
                "prefix": chunk_name,
                "file": f"{safe}.json",
                "wordforms_count": len(chunk_data),
                "size": chunk_file.stat().st_size,
                "hash": file_hash,
            }
        )

    build_id = hashlib.md5("".join(c["hash"] for c in chunk_info).encode()).hexdigest()[:12]
    manifest = {
        "version": "1.0.0",
        "source": "wordforms.csv",
        "build_date": datetime.now(timezone.utc).isoformat(),
        "build_id": build_id,
        "total_wordforms": len(wordforms),
        "total_records": sum(len(v) for v in grouped.values()),
        "total_chunks": len(chunk_info),
        "chunks": chunk_info,
    }
    with (data_dir / "manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    stats_dest = docs_dir / "data" / "stats.json"
    stats_dest.parent.mkdir(parents=True, exist_ok=True)
    if stats_path.exists():
        stats_dest.write_text(stats_path.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        stats_dest.write_text("{}", encoding="utf-8")

    gaps_src = root / "output" / "gaps"
    gaps_dest = docs_dir / "data" / "gaps"
    if gaps_src.is_dir():
        gaps_dest.mkdir(parents=True, exist_ok=True)
        for path in gaps_src.iterdir():
            if path.is_file():
                gaps_dest.joinpath(path.name).write_text(
                    path.read_text(encoding="utf-8"), encoding="utf-8"
                )

    site_meta = {
        "build_id": build_id,
        "total_wordforms": len(wordforms),
        "total_records": manifest["total_records"],
        "generated_at": manifest["build_date"],
    }
    with (docs_dir / "data" / "site-meta.json").open("w", encoding="utf-8") as fh:
        json.dump(site_meta, fh, ensure_ascii=False, indent=2)

    return {
        "wordforms": len(wordforms),
        "chunks": len(chunk_info),
        "build_id": build_id,
        "docs_dir": str(docs_dir),
    }
