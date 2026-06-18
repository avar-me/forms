#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from avarforms.core.pipeline import build_wordforms


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Avar wordforms CSV from all sources.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root directory",
    )
    args = parser.parse_args()
    result = build_wordforms(args.root)
    print(f"Built {result['records_aggregated']} aggregated records from {result['records_raw']} raw.")
    print(f"CSV:        {result['csv']}")
    print(f"Lemma freq: {result['lemma_freq']} ({result['lemma_count']} lemmas)")
    print(f"Stats JSON: {result['stats_json']}")
    print(f"Stats TXT:  {result['stats_txt']}")


if __name__ == "__main__":
    main()
