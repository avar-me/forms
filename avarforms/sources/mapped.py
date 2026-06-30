"""Secondary sources that contribute only Avar wordforms, mapped onto av-ru lemmas.

These sources do not introduce new lemmas. Every Avar token is resolved against the
av-ru dictionary index (`config["index_source"]`); tokens that do not map to an existing
lemma are dropped — mapping onto av-ru is also what keeps the data Avar (Russian loans,
English, proper nouns fall away)."""
from __future__ import annotations

import json
from typing import Any, Iterator

from avarforms.core.extractor import SourceExtractor
from avarforms.core.models import MappingTable, WordFormRecord

from .gimbatov import NOUN_ENDINGS, VERB_ENDINGS, _iter_example_tokens, load_dictionary

# A fuzzy (stem/prefix) match is accepted from a secondary source only if the token ends in
# a recognised Avar inflectional ending — so an Avar inflection (наслу+ялъе) is kept but a
# foreign word that merely shares a prefix with an Avar loanword (рас+шить, сам+олет) is dropped.
_AVAR_FORM_ENDINGS: tuple[str, ...] = tuple(
    sorted(
        VERB_ENDINGS
        | NOUN_ENDINGS
        | {
            "еб", "ев", "ей", "ел", "раб", "рал", "рав", "рай", "себ", "сел",
            "на", "го", "ги", "де", "лъун", "лъи", "лъе", "ал", "би", "заби", "дул", "сан",
            # endings containing palochka (ӏ) — safe to add: palochka is Avar-specific,
            # no Russian word can end in these
            "ӏи", "чӏи", "тӏи", "кӏи", "хӏи", "гӏи",
        },
        key=len,
        reverse=True,
    )
)


def _has_avar_ending(token: str) -> bool:
    return token.endswith(_AVAR_FORM_ENDINGS)


class MappedFormsExtractor(SourceExtractor):
    """Base: yield Avar text strings, tokenize them, map each token to an av-ru lemma."""

    subsource = "wordforms"

    def avar_units(self) -> Iterator[tuple[str, dict[str, Any]]]:
        """Yield (avar_text, detail) — `detail` is the provenance context (`av`, optional
        `ru`) shown on the source page for every token found in `avar_text`."""
        raise NotImplementedError

    def _own_lines(self) -> list[str]:
        return list(self.open_data_lines())

    def extract(self, mappings: MappingTable | None = None) -> Iterator[WordFormRecord]:
        mappings = mappings or {}
        _, index = load_dictionary(self.config["index_source"])
        for text, detail in self.avar_units():
            for token in _iter_example_tokens(text):
                wordform = index._canonical_example_wordform(token)
                # Exact headword/declared-form match is always trusted. A fuzzy stem/prefix
                # match is trusted only when the token ends in an Avar inflectional ending,
                # so foreign words can't attach to Avar loanwords by a shared prefix.
                # Tokens that pass neither check are dropped (non-Avar: Russian, Latin, etc.).
                resolved = index.lookup_lemma_strict(token)
                is_avar = resolved is not None
                if resolved is None:
                    candidate = index.lookup_lemma(token)
                    if candidate[0] and _has_avar_ending(token):
                        resolved = candidate
                        is_avar = True
                    elif _has_avar_ending(token):
                        # Avar-shaped token but no known lemma — include without mapping
                        is_avar = True

                if not is_avar:
                    continue

                lemma, relation, pos, confidence = resolved or ("", "", "", "low")

                if wordform in mappings:
                    override = mappings[wordform]
                    lemma = override.lemma or lemma
                    relation = override.relation or relation
                    pos = override.pos or pos
                    confidence = "high"

                yield WordFormRecord(
                    wordform=wordform,
                    lemma=lemma,
                    relation=relation,
                    pos=pos,
                    source=self.source_name,
                    source_id=self.source_id,
                    subsource=self.subsource,
                    confidence=confidence,
                    detail=dict(detail),
                )


class RuAvFormsExtractor(MappedFormsExtractor):
    """ru-av dictionary: Avar translations (sense.text), comments, and example.av.

    Context: `av` is the Avar text the form was found in; `ru` is the Russian headword
    (for translations/comments) or the example's Russian (for examples)."""

    def avar_units(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for line in self._own_lines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            word = entry.get("word", "")
            for sense in entry.get("senses", []):
                if sense.get("text"):
                    yield sense["text"], {"av": sense["text"], "ru": word}
                if sense.get("comment"):
                    yield sense["comment"], {"av": sense["comment"], "ru": word}
                for example in sense.get("examples", []):
                    if example.get("av"):
                        yield example["av"], {"av": example["av"], "ru": example.get("ru", "")}


class EnAvFormsExtractor(MappedFormsExtractor):
    """en-av dictionary: only the Avar translation field (context: English source word)."""

    def avar_units(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for line in self._own_lines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("avar"):
                yield entry["avar"], {"av": entry["avar"], "ru": entry.get("word", "")}


class TarasBulbaFormsExtractor(MappedFormsExtractor):
    """Taras Bulba parallel corpus (JSON array): Avar sentence (av) with its Russian (ru)."""

    def avar_units(self) -> Iterator[tuple[str, dict[str, Any]]]:
        data: list[dict[str, Any]] = json.loads("".join(self._own_lines()))
        for sentence in data:
            if sentence.get("av"):
                yield sentence["av"], {"av": sentence["av"], "ru": sentence.get("ru", "")}


class IhdalFormsExtractor(MappedFormsExtractor):
    """«ХӀакъикъат» newspaper issue (JSON array): monolingual Avar sentences."""

    def avar_units(self) -> Iterator[tuple[str, dict[str, Any]]]:
        data: list[dict[str, Any]] = json.loads("".join(self._own_lines()))
        for sentence in data:
            if sentence.get("av"):
                yield sentence["av"], {"av": sentence["av"]}


class HakikatFormsExtractor(MappedFormsExtractor):
    """«ХӀакъикъат» online archive (JSONL): monolingual Avar article texts."""

    def avar_units(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for line in self._own_lines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if not entry.get("text"):
                continue
            detail: dict[str, Any] = {}
            if entry.get("slug"):
                detail["slug"] = entry["slug"]
            if entry.get("title"):
                detail["title"] = entry["title"]
            if entry.get("url"):
                detail["url"] = entry["url"]
            yield entry["text"], detail
