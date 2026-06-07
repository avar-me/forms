from __future__ import annotations

import json
import re
from collections import defaultdict
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


def safe_chunk_filename(prefix: str) -> str:
    s = prefix.replace("/", "_").replace("\\", "_").replace(":", "_")
    s = s.strip("._") or "_"
    return s


def split_into_chunks(
    entries: dict[str, dict[str, Any]],
    wordforms: list[str],
) -> dict[str, dict[str, Any]]:
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


def write_chunk_files(
    chunks: dict[str, dict[str, Any]],
    chunks_dir: Path,
) -> list[dict[str, Any]]:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunk_info: list[dict[str, Any]] = []
    for chunk_name, chunk_data in sorted(chunks.items()):
        safe = safe_chunk_filename(chunk_name)
        chunk_file = chunks_dir / f"{safe}.json"
        with chunk_file.open("w", encoding="utf-8") as fh:
            json.dump(chunk_data, fh, ensure_ascii=False, indent=2)
        chunk_info.append(
            {
                "prefix": chunk_name,
                "file": f"{safe}.json",
                "wordforms_count": len(chunk_data),
                "size": chunk_file.stat().st_size,
            }
        )
    return chunk_info
