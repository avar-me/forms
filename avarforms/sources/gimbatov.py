from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from avarforms.core.extractor import SourceExtractor
from avarforms.core.models import MappingTable, WordFormRecord

RELATION_FROM_KEYS: dict[str, str] = {
    "masdarfrom": "масдар",
    "masdarforceto": "масдар (понудительная)",
    "pluralfor": "множественное число",
    "genitivefrom": "родительный падеж",
    "dativefrom": "дательный падеж",
    "locativefrom": "местный падеж",
    "ablativefrom": "отложительный падеж",
    "ergativefrom": "эргативный падеж",
    "participlefrom": "причастие",
    "deverbfrom": "деепричастие",
    "forceto": "понудительная форма",
    "casefrom": "падеж",
}

TOKEN_SPLIT_RE = re.compile(r"[\s,;:!?«»\"()\[\]{}]+")
PUNCT_STRIP = ".,;:!?«»\"()[]{}—–-"
MIN_MORPH_PREFIX_LEN = 3


def _common_prefix_len(a: str, b: str) -> int:
    length = 0
    for left, right in zip(a, b):
        if left != right:
            break
        length += 1
    return length


def _iter_article_morph_bases(entry: dict[str, Any]) -> Iterator[str]:
    """Surface bases for morphology within one dictionary entry."""
    seen: set[str] = set()
    for value in (
        entry.get("stem"),
        entry.get("word"),
        _entry_headword(entry),
    ):
        text = (value or "").strip()
        if text and text not in seen:
            seen.add(text)
            yield text
    for form in entry.get("forms", []):
        text = (form or "").strip()
        if text and text not in seen:
            seen.add(text)
            yield text
    for form in entry.get("gender_forms", []):
        text = (form or "").strip()
        if text and text not in seen:
            seen.add(text)
            yield text
    for sense in entry.get("senses", []):
        for form in sense.get("forms", []):
            text = (form or "").strip()
            if text and text not in seen:
                seen.add(text)
                yield text


def _iter_entry_example_tokens(entry: dict[str, Any]) -> Iterator[str]:
    for sense in entry.get("senses", []):
        for example in sense.get("examples", []):
            yield from _iter_example_tokens(example.get("av", ""))


def _has_strict_attested_prefix(entry: dict[str, Any], token: str) -> bool:
    """True when examples attest a shorter token that is not a declared form."""
    declared = set(_iter_article_morph_bases(entry))
    for example_token in _iter_entry_example_tokens(entry):
        if example_token == token or example_token in declared:
            continue
        if token.startswith(example_token) and len(example_token) < len(token):
            return True
    return False


def _token_declared_for_entry(entry: dict[str, Any], token: str) -> bool:
    if token == entry.get("word"):
        return True
    if token in entry.get("forms", []):
        return True
    if token in entry.get("gender_forms", []):
        return True
    for sense in entry.get("senses", []):
        if token in sense.get("forms", []):
            return True
    return False


def _lookup_article_morphology(entry: dict[str, Any], token: str) -> str | None:
    """Map example token to article headword via stem or shared prefix."""
    headword = _entry_headword(entry)
    if not headword:
        return None

    stem = (entry.get("stem") or "").strip()
    if (
        stem
        and len(stem) >= MIN_MORPH_PREFIX_LEN
        and token.startswith(stem)
        and len(token) > len(stem)
    ):
        return headword

    best_prefix = 0
    via_startswith = False
    for base in _iter_article_morph_bases(entry):
        if base == stem:
            continue
        if token.startswith(base) and len(token) > len(base):
            if len(base) > best_prefix:
                best_prefix = len(base)
                via_startswith = True
            continue
        prefix_len = _common_prefix_len(token, base)
        if (
            prefix_len >= MIN_MORPH_PREFIX_LEN
            and len(token) > prefix_len
            and len(base) > prefix_len
            and prefix_len > best_prefix
        ):
            best_prefix = prefix_len
            via_startswith = False

    if best_prefix < MIN_MORPH_PREFIX_LEN:
        return None
    if not via_startswith and _has_strict_attested_prefix(entry, token):
        return None
    return headword


def _entry_headword(entry: dict[str, Any]) -> str:
    relation = _extract_relation_from_entry(entry)
    if relation:
        return relation[0]
    return entry.get("word", "") or ""


def _iter_entry_form_lemmas(
    entry: dict[str, Any],
    headwords: set[str] | None = None,
) -> Iterator[tuple[str, str]]:
    """Yield (surface_form, lemma) pairs declared in a dictionary entry."""
    headword = _entry_headword(entry)
    word = entry.get("word", "")
    if word and not (headwords and _should_skip_cross_headword_form(word, headword, headwords)):
        yield word, headword
    for form in entry.get("forms", []):
        if headwords and _should_skip_cross_headword_form(form, headword, headwords):
            continue
        yield form, headword
    for form in entry.get("gender_forms", []):
        if headwords and _should_skip_cross_headword_form(form, headword, headwords):
            continue
        yield form, headword
    for sense in entry.get("senses", []):
        for form in sense.get("forms", []):
            if headwords and _should_skip_cross_headword_form(form, headword, headwords):
                continue
            yield form, headword


def _suffix_match_lemma(
    token: str,
    form_lemmas: Iterator[tuple[str, str]],
) -> str | None:
    """Longest base form where token = base + suffix."""
    best_lemma: str | None = None
    best_len = 0
    ambiguous = False
    for form, lemma in form_lemmas:
        if not form or len(form) >= len(token):
            continue
        if not token.startswith(form):
            continue
        if len(form) > best_len:
            best_len = len(form)
            best_lemma = lemma
            ambiguous = False
        elif len(form) == best_len and lemma != best_lemma:
            ambiguous = True
    if best_lemma and not ambiguous:
        return best_lemma
    return None


def _should_skip_cross_headword_form(form: str, lemma: str, headwords: set[str]) -> bool:
    """Form is its own dictionary entry — do not attach it to another lemma."""
    return bool(form and form in headwords and form != lemma)


@dataclass
class DictionaryIndex:
    word_to_entry: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    form_to_lemmas: dict[str, set[str]] = field(default_factory=dict)
    word_relations: dict[str, tuple[str, str]] = field(default_factory=dict)
    headwords: set[str] = field(default_factory=set)

    @classmethod
    def from_entries(cls, entries: list[dict[str, Any]]) -> DictionaryIndex:
        index = cls()
        index.headwords = {entry.get("word", "") for entry in entries if entry.get("word", "")}
        for entry in entries:
            word = entry.get("word", "")
            if not word:
                continue
            index.word_to_entry.setdefault(word, []).append(entry)
            for form in entry.get("forms", []):
                if _should_skip_cross_headword_form(form, word, index.headwords):
                    continue
                index.form_to_lemmas.setdefault(form, set()).add(word)
            for form in entry.get("gender_forms", []):
                if _should_skip_cross_headword_form(form, word, index.headwords):
                    continue
                index.form_to_lemmas.setdefault(form, set()).add(word)

            relation = _extract_relation_from_entry(entry)
            if relation:
                index.word_relations[word] = relation

        return index

    def _token_declared_for_lemma(self, token: str, lemma: str) -> bool:
        for entry in self.word_to_entry.get(lemma, []):
            if _token_declared_for_entry(entry, token):
                return True
        return False

    def _reject_attested_undeclared(self, token: str, lemma: str) -> bool:
        for entry in self.word_to_entry.get(lemma, []):
            if _has_strict_attested_prefix(entry, token):
                return True
        return False

    def _suffix_form_applies(self, token: str, form: str, lemmas: set[str]) -> bool:
        if form not in self.headwords:
            return True
        return any(self._token_declared_for_lemma(token, lemma) for lemma in lemmas)

    def _lookup_in_article(self, entry: dict[str, Any], token: str) -> tuple[str, str] | None:
        form_lemmas = list(_iter_entry_form_lemmas(entry, self.headwords))
        for form, lemma in form_lemmas:
            if token == form:
                return lemma, ""
        lemma = _suffix_match_lemma(token, iter(form_lemmas))
        if lemma:
            return lemma, ""
        morph_lemma = _lookup_article_morphology(entry, token)
        if morph_lemma:
            return morph_lemma, ""
        return None

    def _lookup_global_suffix(
        self,
        token: str,
        context_lemma: str | None,
        token_pos: str,
    ) -> tuple[str, str, str, str] | None:
        best_len = 0
        lemmas_at_best: set[str] = set()
        for form, lemmas in self.form_to_lemmas.items():
            if not form or len(form) >= len(token) or not token.startswith(form):
                continue
            if not self._suffix_form_applies(token, form, set(lemmas)):
                continue
            form_len = len(form)
            if form_len > best_len:
                best_len = form_len
                lemmas_at_best = set(lemmas)
            elif form_len == best_len:
                lemmas_at_best |= lemmas

        if best_len == 0:
            return None

        if len(lemmas_at_best) == 1:
            lemma = next(iter(lemmas_at_best))
            pos = token_pos or (
                _entry_pos(self.word_to_entry[lemma][0]) if lemma in self.word_to_entry else ""
            )
            return lemma, "", pos, "medium"

        if context_lemma and context_lemma in lemmas_at_best:
            pos = token_pos or (
                _entry_pos(self.word_to_entry[context_lemma][0])
                if context_lemma in self.word_to_entry
                else ""
            )
            return context_lemma, "", pos, "medium"

        return "", "", token_pos, "low"

    def _paradigm_lemma_for_form(self, form: str, candidates: set[str]) -> str | None:
        """Headword of a main paradigm entry that lists form (not a *from-only article)."""
        owners: list[str] = []
        for lemma in candidates:
            for entry in self.word_to_entry.get(lemma, []):
                if form not in entry.get("forms", []):
                    continue
                if _extract_relation_from_entry(entry):
                    continue
                if entry.get("word") == lemma:
                    owners.append(lemma)
        unique = list(dict.fromkeys(owners))
        if len(unique) == 1:
            return unique[0]
        return None

    def _lookup_global_shared_prefix(
        self,
        token: str,
        context_lemma: str | None,
        token_pos: str,
    ) -> tuple[str, str, str, str] | None:
        best_len = 0
        forms_at_best: list[tuple[str, set[str]]] = []
        for form, lemmas in self.form_to_lemmas.items():
            if not form:
                continue
            prefix_len = _common_prefix_len(token, form)
            if (
                prefix_len < MIN_MORPH_PREFIX_LEN
                or len(token) <= prefix_len
                or len(form) <= prefix_len
            ):
                continue
            if not (token.startswith(form) or form.startswith(token)):
                tail = max(len(token) - prefix_len, len(form) - prefix_len)
                if tail > 2:
                    continue
            if prefix_len > best_len:
                best_len = prefix_len
                forms_at_best = [(form, set(lemmas))]
            elif prefix_len == best_len:
                forms_at_best.append((form, set(lemmas)))

        if best_len == 0:
            return None

        lemmas_at_best: set[str] = set()
        for _, lemma_set in forms_at_best:
            lemmas_at_best |= lemma_set

        lemma: str | None = None
        if len(lemmas_at_best) == 1:
            lemma = next(iter(lemmas_at_best))
        else:
            for form, lemma_set in forms_at_best:
                pick = self._paradigm_lemma_for_form(form, lemma_set)
                if pick:
                    lemma = pick
                    break
            if not lemma:
                for form, _ in forms_at_best:
                    pick = self._paradigm_lemma_for_form(form, lemmas_at_best)
                    if pick:
                        lemma = pick
                        break
            if not lemma and context_lemma and context_lemma in lemmas_at_best:
                lemma = context_lemma

        if not lemma or self._reject_attested_undeclared(token, lemma):
            return "", "", token_pos, "low"

        pos = token_pos or (
            _entry_pos(self.word_to_entry[lemma][0]) if lemma in self.word_to_entry else ""
        )
        return lemma, "", pos, "medium"

    def _main_paradigm_entry(self, lemma: str) -> dict[str, Any] | None:
        for entry in self.word_to_entry.get(lemma, []):
            if entry.get("word") == lemma and not _extract_relation_from_entry(entry):
                return entry
        entries = self.word_to_entry.get(lemma)
        return entries[0] if entries else None

    def _pick_ambiguous_lemma(self, lemmas: set[str]) -> str:
        """Choose one lemma when the same surface form maps to several headwords."""

        def score(lemma: str) -> tuple[int, int, str]:
            entry = self._main_paradigm_entry(lemma)
            if not entry:
                return (0, 0, lemma)
            examples = sum(
                1
                for sense in entry.get("senses", [])
                for ex in sense.get("examples", [])
                if ex.get("av")
            )
            forms = len(entry.get("forms", []) or [])
            return (examples, forms, lemma)

        return max(lemmas, key=score)

    def lookup_lemma(
        self,
        token: str,
        context_lemma: str | None = None,
        context_entry: dict[str, Any] | None = None,
    ) -> tuple[str, str, str, str]:
        """Return (lemma, relation, pos, confidence)."""
        token_pos = ""
        if token in self.word_to_entry:
            token_pos = _entry_pos(self.word_to_entry[token][0])

        if context_entry:
            local = self._lookup_in_article(context_entry, token)
            if local:
                lemma, relation = local
                pos = token_pos or (
                    _entry_pos(self.word_to_entry[lemma][0]) if lemma in self.word_to_entry else ""
                )
                return lemma, relation, pos, "medium"

        if token in self.word_relations:
            lemma, relation = self.word_relations[token]
            if not token_pos and lemma in self.word_to_entry:
                token_pos = _entry_pos(self.word_to_entry[lemma][0])
            return lemma, relation, token_pos, "high"

        if token in self.form_to_lemmas:
            lemmas = self.form_to_lemmas[token]
            if len(lemmas) == 1:
                lemma = next(iter(lemmas))
                relation = ""
                if lemma == token and token in self.word_to_entry and token not in self.word_relations:
                    relation = _gram_form_relation(self.word_to_entry[token][0])
                pos = token_pos or (_entry_pos(self.word_to_entry[lemma][0]) if lemma in self.word_to_entry else "")
                return lemma, relation, pos, "medium"
            if context_lemma and context_lemma in lemmas:
                pos = token_pos or (_entry_pos(self.word_to_entry[context_lemma][0]) if context_lemma in self.word_to_entry else "")
                relation = ""
                if context_lemma == token and token in self.word_to_entry:
                    relation = _gram_form_relation(self.word_to_entry[token][0])
                return context_lemma, relation, pos, "medium"
            lemma = self._pick_ambiguous_lemma(lemmas)
            pos = token_pos or (_entry_pos(self.word_to_entry[lemma][0]) if lemma in self.word_to_entry else "")
            return lemma, "", pos, "medium"

        suffix = self._lookup_global_suffix(token, context_lemma, token_pos)
        if suffix:
            return suffix

        shared = self._lookup_global_shared_prefix(token, context_lemma, token_pos)
        if shared:
            return shared

        if token in self.word_to_entry and token not in self.word_relations:
            entry = self.word_to_entry[token][0]
            relation = _gram_form_relation(entry)
            return token, relation, token_pos, "high"

        return "", "", "", "low"


def _extract_relation_from_entry(entry: dict[str, Any]) -> tuple[str, str] | None:
    for sense in entry.get("senses", []):
        for key, label in RELATION_FROM_KEYS.items():
            if key in sense:
                return sense[key], label
    return None


def _entry_pos(entry: dict[str, Any]) -> str:
    return entry.get("pos", "") or ""


def _gram_form_relation(entry: dict[str, Any]) -> str:
    gram_form = entry.get("form", "") or ""
    if gram_form in ("", "—"):
        return ""
    return gram_form


def _load_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _iter_example_tokens(av_text: str) -> Iterator[str]:
    for raw in TOKEN_SPLIT_RE.split(av_text):
        token = raw.strip(PUNCT_STRIP)
        if token and not token.isdigit():
            yield token


class GimbatovExtractor(SourceExtractor):
    """Extract word forms from Gimbatov AV-RU dictionary."""

    SUB_FORMS = "forms"
    SUB_GENDER = "gender_forms"
    SUB_EXPLICIT = "explicit_relation"
    SUB_HEADWORD = "headword"
    SUB_EXAMPLES = "examples"

    def extract(self, mappings: MappingTable | None = None) -> Iterator[WordFormRecord]:
        mappings = mappings or {}
        data_path = self.resolve_path(self.config["path"])
        entries = _load_entries(data_path)
        index = DictionaryIndex.from_entries(entries)

        for entry in entries:
            yield from self._extract_entry(entry, mappings, index.headwords)

        for entry in entries:
            yield from self._extract_examples(entry, index, mappings)

    def _record(
        self,
        *,
        wordform: str,
        lemma: str = "",
        relation: str = "",
        pos: str = "",
        subsource: str,
        confidence: str = "high",
        mappings: MappingTable,
        allow_self: bool = False,
    ) -> WordFormRecord | None:
        if not wordform:
            return None
        if wordform == lemma and not relation and not allow_self:
            return None

        if wordform in mappings:
            override = mappings[wordform]
            lemma = override.lemma or lemma
            relation = override.relation or relation
            pos = override.pos or pos
            confidence = "high"

        return WordFormRecord(
            wordform=wordform,
            lemma=lemma,
            relation=relation,
            pos=pos,
            source=self.source_name,
            subsource=subsource,
            confidence=confidence,
        )

    def _extract_entry(
        self,
        entry: dict[str, Any],
        mappings: MappingTable,
        headwords: set[str],
    ) -> Iterator[WordFormRecord]:
        word = entry.get("word", "")
        if not word:
            return

        pos = _entry_pos(entry)

        relation_info = _extract_relation_from_entry(entry)
        if relation_info:
            lemma, relation = relation_info
            rec = self._record(
                wordform=word,
                lemma=lemma,
                relation=relation,
                pos=pos,
                subsource=self.SUB_EXPLICIT,
                mappings=mappings,
            )
            if rec:
                yield rec

        headword = word
        if relation_info:
            headword = relation_info[0]
        else:
            rec = self._record(
                wordform=word,
                lemma=word,
                relation=_gram_form_relation(entry),
                pos=pos,
                subsource=self.SUB_HEADWORD,
                allow_self=True,
                mappings=mappings,
            )
            if rec:
                yield rec

        forms = entry.get("forms", [])
        for form in forms:
            if form == word:
                continue
            if _should_skip_cross_headword_form(form, headword, headwords):
                continue
            rec = self._record(
                wordform=form,
                lemma=headword,
                relation="",
                pos=pos,
                subsource=self.SUB_FORMS,
                confidence="high",
                mappings=mappings,
            )
            if rec:
                yield rec

        gender_forms = entry.get("gender_forms", [])
        if gender_forms:
            for gform in gender_forms:
                if gform == word:
                    continue
                if _should_skip_cross_headword_form(gform, headword, headwords):
                    continue
                rec = self._record(
                    wordform=gform,
                    lemma=headword,
                    relation="родовая форма",
                    pos=pos,
                    subsource=self.SUB_GENDER,
                    mappings=mappings,
                )
                if rec:
                    yield rec

    def _extract_examples(
        self,
        entry: dict[str, Any],
        index: DictionaryIndex,
        mappings: MappingTable,
    ) -> Iterator[WordFormRecord]:
        context_lemma = entry.get("word", "")

        for sense in entry.get("senses", []):
            for example in sense.get("examples", []):
                av_text = example.get("av", "")
                if not av_text:
                    continue
                for token in _iter_example_tokens(av_text):
                    if token in mappings:
                        rec = self._record(
                            wordform=token,
                            subsource=self.SUB_EXAMPLES,
                            mappings=mappings,
                        )
                        if rec:
                            yield rec
                        continue

                    lemma, relation, token_pos, confidence = index.lookup_lemma(
                        token,
                        context_lemma=context_lemma,
                        context_entry=entry,
                    )

                    if confidence == "low":
                        lemma, relation = "", ""
                        token_pos = ""

                    rec = self._record(
                        wordform=token,
                        lemma=lemma,
                        relation=relation,
                        pos=token_pos if lemma else "",
                        subsource=self.SUB_EXAMPLES,
                        confidence=confidence if lemma or relation else "low",
                        mappings=mappings,
                        allow_self=True,
                    )
                    if rec:
                        yield rec
