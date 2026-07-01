from __future__ import annotations

import itertools
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Iterable, Iterator

from avarforms.core.extractor import SourceExtractor
from avarforms.core.models import MappingTable, WordFormRecord

from .class_prefix import class_prefix_matches

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

TOKEN_SPLIT_RE = re.compile(
    r"[\s,;:!?/«»\"\"''\u201c\u201d\u2018\u2019\u201a\u201b\u201e\u201f\u2039\u203a()\[\]{}—–\u2026\u2022\u2116]+"
)
PUNCT_STRIP = ".,;:!?/«»\"\"''\u201c\u201d\u2018\u2019\u201a\u201b\u201e\u201f\u2039\u203a()[]{}—–-\u2026\u2022\u2116"
MIN_MORPH_PREFIX_LEN = 3
LIMITATIVE_SUFFIX = "гӏан"  # инфинитив на -е + гӏан → форма предела («пока/до тех пор пока V»)
# Endings that mark a verb form (nouns don't take them). Used to disambiguate a token
# whose stem is shared by a verb and a noun: къечон (= къеч + он) → verb къечезе, not noun къеч.
VERB_ENDINGS = frozenset({
    "он", "ун", "ана", "уна", "ина",
    "улеб", "улел", "олеб", "арал", "араб",
    "изе", "ине", "езе", "азе", "озе", "узе",
    "ила", "ани", "анхъе",
})
# Nominal case endings that adjectives do NOT take (they agree by class: -ав/-ай/-аб/-ал).
# Used to prefer a noun's case form over an adjective whose stem is a longer coincidental
# prefix: гьаваялда (= гьава + ялда, locative) → гьава, not adjective гьаваяб (stem гьавая).
# Number endings (-ал/-би) are excluded — they are shared with adjective plurals.
NOUN_ENDINGS = frozenset({
    "да", "ялда", "лда", "ра", "ахъ", "ахъе", "укь", "укье", "ухъ", "ухъе", "тӏа", "тӏе",
    "ул", "лъул", "ялъул", "дул", "зул", "алъул",
    "ца", "алъ", "ялъ", "аз",
    "лъе", "ялъе",
    "аса", "ялдаса", "тӏаса", "дасан",
})
# Palochka variants (capital Ӏ, Latin I/i/l/L, pipe, digit 1, Cyrillic І) → canonical ӏ (U+04CF),
# matching normalize_word so example tokens hit dictionary keys (e.g. ГӀурул → гӏурул).
PALOCHKA_RE = re.compile(r"[1IiｌlL|ǀӀІ]")
# For token normalization: replace unambiguous palochka glyphs unconditionally;
# replace I/i only when adjacent to Cyrillic so Latin abbreviations (IT, Instagram)
# and Roman numerals (II, III) are left intact.
# Digit 1 is replaced only after Avar digraph consonants to avoid corrupting numbers.
_PALOCHKA_SAFE_RE = re.compile(r"[ｌlL|ǀӀІ]|(?<=[а-яёА-ЯЁӏ])[Ii]|[Ii](?=[а-яёА-ЯЁӏ])")
_PALOCHKA_DIGIT_RE = re.compile(r"(?<=[кКгГтТчЧхХцЦлЛ])1")


def _longest_common_prefix(strings: set[str]) -> str:
    """Longest common prefix shared by all strings (a lemma's morphological stem)."""
    items = [s for s in strings if s]
    if not items:
        return ""
    lo, hi = min(items), max(items)
    length = 0
    for left, right in zip(lo, hi):
        if left != right:
            break
        length += 1
    return lo[:length]


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


@dataclass(frozen=True)
class _EntryCache:
    form_lemmas: tuple[tuple[str, str], ...]
    declared_bases: frozenset[str]


def _build_entry_cache(entry: dict[str, Any], headwords: set[str]) -> _EntryCache:
    return _EntryCache(
        form_lemmas=tuple(_iter_entry_form_lemmas(entry, headwords)),
        declared_bases=frozenset(_iter_article_morph_bases(entry)),
    )


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


def _lookup_article_morphology(
    entry: dict[str, Any],
    token: str,
    *,
    cache: _EntryCache | None = None,
) -> str | None:
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

    # Strong link only: the token must contain a declared base as a prefix
    # (token = base + affix). Divergent shared prefixes (e.g. къаданиб vs the
    # къандалъо stem, sharing only «къа») are rejected — defer to honest non-match.
    morph_bases = cache.declared_bases if cache else set(_iter_article_morph_bases(entry))
    for base in morph_bases:
        if base == stem or len(base) < MIN_MORPH_PREFIX_LEN:
            continue
        if token.startswith(base) and len(token) > len(base):
            return headword
    return None


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
    _entries_by_id: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _entry_id_map: dict[int, int] = field(default_factory=dict, repr=False)
    _entry_caches: list[_EntryCache] = field(default_factory=list, repr=False)
    _suffix_by_initial: dict[str, list[tuple[str, frozenset[str]]]] = field(
        default_factory=dict, repr=False
    )
    _prefix_by_key: dict[str, list[tuple[str, frozenset[str]]]] = field(
        default_factory=dict, repr=False
    )
    # base[:MIN_MORPH_PREFIX_LEN] -> list of (base, lemma, is_headword); base is either a
    # lemma's headword surface or its stem (longest common prefix of declared forms)
    _base_by_key: dict[str, list[tuple[str, str, bool]]] = field(default_factory=dict, repr=False)
    _main_paradigm_cache: dict[str, dict[str, Any] | None] = field(default_factory=dict, repr=False)
    _lemma_pick_scores: dict[str, tuple[int, int, str]] = field(default_factory=dict, repr=False)
    _lookup_lemma_cached: Callable[[str, str, int], tuple[str, str, str, str]] | None = field(
        default=None, repr=False, compare=False
    )

    @classmethod
    def from_entries(cls, entries: list[dict[str, Any]]) -> DictionaryIndex:
        index = cls()
        index.headwords = {entry.get("word", "") for entry in entries if entry.get("word", "")}
        suffix_by_initial: dict[str, list[tuple[str, frozenset[str]]]] = defaultdict(list)
        prefix_by_key: dict[str, list[tuple[str, frozenset[str]]]] = defaultdict(list)

        for entry in entries:
            word = entry.get("word", "")
            if not word:
                continue
            index.word_to_entry.setdefault(word, []).append(entry)
            index._entry_id_map[id(entry)] = len(index._entries_by_id)
            index._entries_by_id.append(entry)
            index._entry_caches.append(_build_entry_cache(entry, index.headwords))

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

        for form, lemmas in index.form_to_lemmas.items():
            frozen = frozenset(lemmas)
            if form:
                # Index by first 2 chars (or 1 for single-char forms) to keep per-bucket
                # lists ~8× smaller than a 1-char key, reducing scan work in the hot path.
                suffix_by_initial[form[:2]].append((form, frozen))
            if len(form) >= MIN_MORPH_PREFIX_LEN:
                prefix_by_key[form[:MIN_MORPH_PREFIX_LEN]].append((form, frozen))

        for items in suffix_by_initial.values():
            items.sort(key=lambda item: len(item[0]), reverse=True)
        index._suffix_by_initial = dict(suffix_by_initial)
        index._prefix_by_key = dict(prefix_by_key)

        # Morphological bases for attaching example tokens (token = base + affix). Each lemma
        # contributes its headword surface and its stem (longest common prefix of declared
        # forms). Requiring the *full* base as a prefix rejects coincidental fragments
        # (къаданиб vs къандалъ-); the headword base recovers lemmas whose stem is destroyed
        # by an irregular form (гӏин, plural гӏундул collapses the LCP).
        base_by_key: dict[str, list[tuple[str, str, bool]]] = defaultdict(list)
        for lemma, lemma_entries in index.word_to_entry.items():
            surfaces: set[str] = {lemma}
            for entry in lemma_entries:
                surfaces.update(f for f in entry.get("forms", []) or [] if f)
                surfaces.update(f for f in entry.get("gender_forms", []) or [] if f)
                for sense in entry.get("senses", []):
                    surfaces.update(f for f in sense.get("forms", []) or [] if f)
            bases: set[tuple[str, bool]] = set()
            if len(lemma) >= MIN_MORPH_PREFIX_LEN:
                bases.add((lemma, True))
            stem = _longest_common_prefix(surfaces)
            if len(stem) >= MIN_MORPH_PREFIX_LEN and stem != lemma:
                bases.add((stem, False))
            for base, is_headword in bases:
                base_by_key[base[:MIN_MORPH_PREFIX_LEN]].append((base, lemma, is_headword))
        index._base_by_key = dict(base_by_key)

        for lemma in index.word_to_entry:
            entry = index._main_paradigm_entry(lemma)
            if not entry:
                index._lemma_pick_scores[lemma] = (0, 0, lemma)
                continue
            examples = sum(
                1
                for sense in entry.get("senses", [])
                for ex in sense.get("examples", [])
                if ex.get("av")
            )
            forms = len(entry.get("forms", []) or [])
            index._lemma_pick_scores[lemma] = (examples, forms, lemma)

        index._lookup_lemma_cached = lru_cache(maxsize=500_000)(index._lookup_lemma_impl)
        return index

    def _entry_key(self, entry: dict[str, Any] | None) -> int:
        if entry is None:
            return -1
        return self._entry_id_map.get(id(entry), -1)

    def _entry_cache(self, entry_key: int) -> _EntryCache | None:
        if entry_key < 0:
            return None
        return self._entry_caches[entry_key]

    def _token_declared_for_lemma(self, token: str, lemma: str) -> bool:
        for entry in self.word_to_entry.get(lemma, []):
            if _token_declared_for_entry(entry, token):
                return True
        return False

    def _suffix_form_applies(self, token: str, form: str, lemmas: frozenset[str]) -> bool:
        if form not in self.headwords:
            return True
        return any(self._token_declared_for_lemma(token, lemma) for lemma in lemmas)

    def _lookup_in_article(
        self,
        entry: dict[str, Any],
        token: str,
        cache: _EntryCache | None = None,
    ) -> tuple[str, str] | None:
        form_lemmas = cache.form_lemmas if cache else tuple(_iter_entry_form_lemmas(entry, self.headwords))
        for form, lemma in form_lemmas:
            if token == form:
                return lemma, ""
        # A token that is itself a declared form/gender-form of another lemma must not be
        # fuzzily reattached to this article by suffix/shared-prefix morphology (e.g. берцинал,
        # a gender-form of берцинаб, appearing in the «бер» article — «бер» is a form here, so a
        # naive suffix match would claim берцинал = бер + цинал). Defer to the global exact lookup.
        if token in self.form_to_lemmas and _entry_headword(entry) not in self.form_to_lemmas[token]:
            return None
        lemma = _suffix_match_lemma(token, iter(form_lemmas))
        if lemma:
            return lemma, ""
        morph_lemma = _lookup_article_morphology(entry, token, cache=cache)
        if morph_lemma:
            return morph_lemma, ""
        return None

    def _lookup_global_suffix(
        self,
        token: str,
        context_lemma: str | None,
        token_pos: str,
    ) -> tuple[str, str, str, str] | None:
        if not token:
            return None
        best_len = 0
        lemmas_at_best: set[str] = set()
        token_len = len(token)
        # Primary bucket: 2-char key covers forms with matching first 2 chars.
        # Secondary bucket: 1-char key covers single-character forms (very rare).
        key2 = token[:2]
        key1 = token[0]
        buckets = (
            itertools.chain(
                self._suffix_by_initial.get(key2, ()),
                self._suffix_by_initial.get(key1, ()) if key1 != key2 else (),
            )
        )
        for form, lemmas in buckets:
            form_len = len(form)
            if form_len >= token_len:
                continue
            # List is sorted by length descending; once form is shorter than best, no improvement.
            if form_len < best_len:
                break
            if not token.startswith(form):
                continue
            if not self._suffix_form_applies(token, form, lemmas):
                continue
            if form_len > best_len:
                best_len = form_len
                lemmas_at_best = set(lemmas)
            else:
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

    def _lookup_global_shared_prefix(
        self,
        token: str,
        context_lemma: str | None,
        token_pos: str,
    ) -> tuple[str, str, str, str] | None:
        if len(token) < MIN_MORPH_PREFIX_LEN:
            return None
        # Strong link: token = base + affix, where base is a lemma's headword or stem.
        # Collect every candidate base that is a proper prefix of the token.
        candidates: list[tuple[str, str, bool]] = []  # (base, lemma, is_headword)
        for base, lemma_, is_headword in self._base_by_key.get(token[:MIN_MORPH_PREFIX_LEN], ()):
            if len(base) < len(token) and token.startswith(base):
                candidates.append((base, lemma_, is_headword))
        if not candidates:
            return None

        lemma = self._resolve_base_candidates(token, candidates, context_lemma)
        if not lemma:
            return None
        pos = token_pos or (
            _entry_pos(self.word_to_entry[lemma][0]) if lemma in self.word_to_entry else ""
        )
        return lemma, "", pos, "medium"

    def _resolve_base_candidates(
        self,
        token: str,
        candidates: list[tuple[str, str, bool]],
        context_lemma: str | None,
    ) -> str | None:
        # A clearly verbal ending overrides base length: къечон (= къеч + он) is the
        # converb of verb къечезе, not the noun къеч that merely shares the stem.
        verbs = [
            (base, lemma)
            for base, lemma, _ in candidates
            if token[len(base):] in VERB_ENDINGS and self._lemma_pos(lemma) == "глагол"
        ]
        if verbs:
            return self._longest_base_lemma(verbs, context_lemma)

        # The longest base normally wins, but a noun's case form must not be lost to an
        # adjective whose stem is a longer coincidental prefix (гьаваялда → гьава, not
        # adjective гьаваяб). If the longest base is an adjective yet a noun candidate carries
        # a nominal case ending, take that noun.
        best = self._longest_base_lemma([(base, lemma) for base, lemma, _ in candidates], context_lemma)
        if best and self._lemma_pos(best) == "прилагательное":
            nouns = [
                (base, lemma)
                for base, lemma, _ in candidates
                if token[len(base):] in NOUN_ENDINGS and self._lemma_pos(lemma) == "существительное"
            ]
            if nouns:
                return self._longest_base_lemma(nouns, context_lemma)
        return best

    def _longest_base_lemma(
        self,
        pairs: list[tuple[str, str]],
        context_lemma: str | None,
    ) -> str | None:
        best = max(len(base) for base, _ in pairs)
        lemmas = {lemma for base, lemma in pairs if len(base) == best}
        if len(lemmas) == 1:
            return next(iter(lemmas))
        if context_lemma and context_lemma in lemmas:
            return context_lemma
        return self._pick_ambiguous_lemma(lemmas)

    def _lemma_pos(self, lemma: str) -> str:
        entries = self.word_to_entry.get(lemma)
        return _entry_pos(entries[0]) if entries else ""

    def _main_paradigm_entry(self, lemma: str) -> dict[str, Any] | None:
        if lemma in self._main_paradigm_cache:
            return self._main_paradigm_cache[lemma]
        entry: dict[str, Any] | None = None
        for candidate in self.word_to_entry.get(lemma, []):
            if candidate.get("word") == lemma and not _extract_relation_from_entry(candidate):
                entry = candidate
                break
        if entry is None:
            entries = self.word_to_entry.get(lemma)
            entry = entries[0] if entries else None
        self._main_paradigm_cache[lemma] = entry
        return entry

    def _pick_ambiguous_lemma(self, lemmas: set[str]) -> str:
        """Choose one lemma when the same surface form maps to several headwords."""
        return max(lemmas, key=lambda lemma: self._lemma_pick_scores.get(lemma, (0, 0, lemma)))

    def _lookup_headword_self(self, token: str, token_pos: str) -> tuple[str, str, str, str] | None:
        """Token is a dictionary headword — map to its own article, not a prefix of another."""
        entry = self._main_paradigm_entry(token)
        if not entry:
            return None
        pos = token_pos or _entry_pos(entry)
        relation = _gram_form_relation(entry)
        return token, relation, pos, "high"

    def _resolve_lemma_from_surface(self, surface: str, token_pos: str) -> tuple[str, str, str, str] | None:
        if surface in self.headwords:
            entry = self.word_to_entry[surface][0]
            if _entry_pos(entry) != "глагол":
                return None
            pos = token_pos or _entry_pos(entry)
            relation = _gram_form_relation(entry)
            return surface, relation, pos, "medium"

        if surface not in self.form_to_lemmas:
            return None

        lemmas = self.form_to_lemmas[surface]
        verb_lemmas = {
            lemma
            for lemma in lemmas
            if lemma in self.word_to_entry and _entry_pos(self.word_to_entry[lemma][0]) == "глагол"
        }
        if not verb_lemmas:
            return None
        if len(verb_lemmas) == 1:
            lemma = next(iter(verb_lemmas))
        else:
            lemma = self._pick_ambiguous_lemma(verb_lemmas)
        pos = token_pos or (_entry_pos(self.word_to_entry[lemma][0]) if lemma in self.word_to_entry else "")
        return lemma, "", pos, "medium"

    def _resolve_class_affix_surface(self, surface: str, token_pos: str) -> tuple[str, str, str, str] | None:
        """Resolve class-affix candidate to any dictionary headword or form (not verbs only)."""
        if surface in self.headwords:
            entry = self.word_to_entry[surface][0]
            pos = token_pos or _entry_pos(entry)
            relation = _gram_form_relation(entry)
            return surface, relation, pos, "medium"

        if surface not in self.form_to_lemmas:
            return None

        lemmas = self.form_to_lemmas[surface]
        verb_lemmas = {
            lemma
            for lemma in lemmas
            if lemma in self.word_to_entry and _entry_pos(self.word_to_entry[lemma][0]) == "глагол"
        }
        pick_from = verb_lemmas if verb_lemmas else lemmas
        if len(pick_from) == 1:
            lemma = next(iter(pick_from))
        else:
            lemma = self._pick_ambiguous_lemma(pick_from)
        pos = token_pos or (_entry_pos(self.word_to_entry[lemma][0]) if lemma in self.word_to_entry else "")
        return lemma, "", pos, "medium"

    def _lookup_class_prefix(self, token: str, token_pos: str) -> tuple[str, str, str, str] | None:
        """Map class/gender surface forms (в/р/й/я/е, including suffix ев/ей/ер) to б-class lemmas."""
        for candidate, relation in class_prefix_matches(token):
            resolved = self._resolve_class_affix_surface(candidate, token_pos)
            if not resolved:
                continue
            lemma, _old_relation, pos, confidence = resolved
            return lemma, relation, pos, confidence
        return None

    def _lookup_limitative(self, token: str, token_pos: str) -> tuple[str, str, str, str] | None:
        """Map verb-infinitive + гӏан (форма предела «пока V») to the verb infinitive.

        Only fires when stripping `гӏан` leaves a `-е` headword whose pos is глагол,
        so adverbs/postpositions ending in гӏан (their own headwords) are untouched.
        """
        if not token.endswith(LIMITATIVE_SUFFIX):
            return None
        base = token[: -len(LIMITATIVE_SUFFIX)]
        if len(base) < MIN_MORPH_PREFIX_LEN or not base.endswith("е"):
            return None
        entry = self._main_paradigm_entry(base)
        if entry is None or _entry_pos(entry) != "глагол":
            return None
        return base, "", token_pos or "глагол", "medium"

    def _lookup_sentence_case(self, token: str, token_pos: str) -> tuple[str, str, str, str] | None:
        """Map sentence-capitalized tokens when the lowercase form is an exact dictionary hit."""
        folded = _sentence_case_fold(token)
        if not folded:
            return None

        if folded in self.headwords:
            entry = self.word_to_entry[folded][0]
            pos = token_pos or _entry_pos(entry)
            relation = _gram_form_relation(entry)
            return folded, relation, pos, "high"

        if folded not in self.form_to_lemmas:
            return None

        lemmas = self.form_to_lemmas[folded]
        if len(lemmas) == 1:
            lemma = next(iter(lemmas))
        else:
            lemma = self._pick_ambiguous_lemma(lemmas)
        pos = token_pos or (_entry_pos(self.word_to_entry[lemma][0]) if lemma in self.word_to_entry else "")
        relation = ""
        if lemma == folded and folded in self.word_to_entry and folded not in self.word_relations:
            relation = _gram_form_relation(self.word_to_entry[folded][0])
        return lemma, relation, pos, "medium"

    def _canonical_example_wordform(self, token: str) -> str:
        folded = _sentence_case_fold(token)
        if folded and (folded in self.headwords or folded in self.form_to_lemmas):
            return folded
        return token

    def lookup_lemma(
        self,
        token: str,
        context_lemma: str | None = None,
        context_entry: dict[str, Any] | None = None,
    ) -> tuple[str, str, str, str]:
        """Return (lemma, relation, pos, confidence)."""
        assert self._lookup_lemma_cached is not None
        return self._lookup_lemma_cached(
            token,
            context_lemma or "",
            self._entry_key(context_entry),
        )

    def lookup_lemma_strict(self, token: str) -> tuple[str, str, str, str] | None:
        """Exact matches only — explicit relation, headword identity, or a declared form.

        Used for secondary sources: it skips the fuzzy stem/prefix paths so a foreign word
        cannot attach to an Avar loanword by a shared prefix (расшить↛рас, самолет↛самизе).
        """
        token_pos = ""
        if token in self.word_to_entry:
            token_pos = _entry_pos(self.word_to_entry[token][0])

        if token in self.word_relations:
            lemma, relation = self.word_relations[token]
            if not token_pos and lemma in self.word_to_entry:
                token_pos = _entry_pos(self.word_to_entry[lemma][0])
            return lemma, relation, token_pos, "high"

        headword = self._lookup_headword_self(token, token_pos)
        if headword:
            return headword

        sentence_case = self._lookup_sentence_case(token, token_pos)
        if sentence_case:
            return sentence_case

        if token in self.form_to_lemmas:
            lemmas = self.form_to_lemmas[token]
            lemma = next(iter(lemmas)) if len(lemmas) == 1 else self._pick_ambiguous_lemma(lemmas)
            relation = ""
            if lemma == token and token in self.word_to_entry and token not in self.word_relations:
                relation = _gram_form_relation(self.word_to_entry[token][0])
            pos = token_pos or (
                _entry_pos(self.word_to_entry[lemma][0]) if lemma in self.word_to_entry else ""
            )
            return lemma, relation, pos, "medium"

        return None

    def _lookup_lemma_impl(
        self,
        token: str,
        context_lemma: str,
        entry_key: int,
    ) -> tuple[str, str, str, str]:
        """Uncached lemma lookup; keyed by token, context lemma, and article id."""
        context_entry = self._entries_by_id[entry_key] if entry_key >= 0 else None
        entry_cache = self._entry_cache(entry_key)
        context_lemma = context_lemma or None

        token_pos = ""
        if token in self.word_to_entry:
            token_pos = _entry_pos(self.word_to_entry[token][0])

        if token in self.word_relations:
            lemma, relation = self.word_relations[token]
            if not token_pos and lemma in self.word_to_entry:
                token_pos = _entry_pos(self.word_to_entry[lemma][0])
            return lemma, relation, token_pos, "high"

        headword = self._lookup_headword_self(token, token_pos)
        if headword:
            return headword

        sentence_case = self._lookup_sentence_case(token, token_pos)
        if sentence_case:
            return sentence_case

        limitative = self._lookup_limitative(token, token_pos)
        if limitative:
            return limitative

        if context_entry is not None:
            local = self._lookup_in_article(context_entry, token, cache=entry_cache)
            if local:
                lemma, relation = local
                pos = token_pos or (
                    _entry_pos(self.word_to_entry[lemma][0]) if lemma in self.word_to_entry else ""
                )
                return lemma, relation, pos, "medium"

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
                pos = token_pos or (
                    _entry_pos(self.word_to_entry[context_lemma][0])
                    if context_lemma in self.word_to_entry
                    else ""
                )
                relation = ""
                if context_lemma == token and token in self.word_to_entry:
                    relation = _gram_form_relation(self.word_to_entry[token][0])
                return context_lemma, relation, pos, "medium"
            lemma = self._pick_ambiguous_lemma(lemmas)
            pos = token_pos or (_entry_pos(self.word_to_entry[lemma][0]) if lemma in self.word_to_entry else "")
            return lemma, "", pos, "medium"

        class_prefix = self._lookup_class_prefix(token, token_pos)
        if class_prefix:
            return class_prefix

        suffix = self._lookup_global_suffix(token, context_lemma, token_pos)
        if suffix:
            return suffix

        shared = self._lookup_global_shared_prefix(token, context_lemma, token_pos)
        if shared:
            return shared

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


def _normalize_entry_palochka(entry: dict[str, Any]) -> None:
    """Unify palochka in an entry's Avar match keys so it agrees with token normalization.

    Some headwords/forms carry a capital palochka (ГӀачинух); without this they would
    not match palochka-normalized example tokens.
    """
    def fix(value: str) -> str:
        return PALOCHKA_RE.sub("ӏ", value)

    if entry.get("word"):
        entry["word"] = fix(entry["word"])
    if entry.get("stem"):
        entry["stem"] = fix(entry["stem"])
    for key in ("forms", "gender_forms"):
        if entry.get(key):
            entry[key] = [fix(f) for f in entry[key]]
    for sense in entry.get("senses", []):
        if sense.get("forms"):
            sense["forms"] = [fix(f) for f in sense["forms"]]
        for rel_key in RELATION_FROM_KEYS:
            if rel_key in sense and isinstance(sense[rel_key], str):
                sense[rel_key] = fix(sense[rel_key])


def _load_entries(lines: Iterable[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if line:
            entry = json.loads(line)
            _normalize_entry_palochka(entry)
            entries.append(entry)
    return entries


@lru_cache(maxsize=4)
def load_dictionary(source: str) -> tuple[tuple[dict[str, Any], ...], DictionaryIndex]:
    """Load av-ru entries (url or path) and build the lemma index, once per source.

    Cached so the index is built a single time and shared by every extractor that
    maps wordforms onto av-ru lemmas (gimbatov + the secondary wordform sources).
    """
    if source.startswith(("http://", "https://")):
        from avarforms.core.extractor import read_source_text

        lines: Iterable[str] = read_source_text(source).splitlines()
    else:
        with open(source, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    entries = _load_entries(lines)
    return tuple(entries), DictionaryIndex.from_entries(entries)


def _sentence_case_fold(token: str) -> str | None:
    """Fold sentence-initial uppercase: «Хъахӏилаб» → «хъахӏилаб»."""
    if len(token) < 2 or not token[0].isupper():
        return None
    folded = token[0].lower() + token[1:]
    return folded if folded != token else None


# Zero-width and directional formatting characters that appear in corpus texts:
# U+200B-U+200F (ZWSP/ZWNJ/ZWJ/LRM/RLM), U+202A-U+202E (directional formatting),
# U+2060-U+2064 (word joiner etc.), U+FEFF (BOM), U+00AD (soft hyphen)
_INVISIBLE_RE = re.compile("[​-‏‪-‮⁠-⁤﻿­]")


def _normalize_example_token(raw: str) -> str:
    """Strip punctuation/quotes and unify palochka variants to canonical ӏ.

    Palochka is unified only in tokens that contain Cyrillic, so pure
    Latin/numeric tokens (e.g. «1990») are left intact.
    """
    token = _INVISIBLE_RE.sub("", raw).strip()
    while True:
        stripped = token.strip(PUNCT_STRIP)
        if stripped == token:
            break
        token = stripped
    if PALOCHKA_RE.search(token) and any("Ѐ" <= ch <= "ӿ" for ch in token):
        token = _PALOCHKA_SAFE_RE.sub("ӏ", token)
        token = _PALOCHKA_DIGIT_RE.sub("ӏ", token)
    return token


def _iter_example_tokens(av_text: str) -> Iterator[str]:
    for raw in TOKEN_SPLIT_RE.split(av_text):
        token = _normalize_example_token(raw)
        if token and not token.isdigit():
            yield token


def _entry_detail(entry: dict[str, Any], **extra: Any) -> dict[str, Any]:
    detail: dict[str, Any] = {"entry": entry.get("word", "")}
    pos = entry.get("pos") or ""
    if pos:
        detail["entry_pos"] = pos
    forms = entry.get("forms") or []
    if forms:
        detail["entry_forms"] = forms
    detail.update(extra)
    return detail


class GimbatovExtractor(SourceExtractor):
    """Extract word forms from Gimbatov AV-RU dictionary."""

    SUB_FORMS = "forms"
    SUB_GENDER = "gender_forms"
    SUB_EXPLICIT = "explicit_relation"
    SUB_HEADWORD = "headword"
    SUB_EXAMPLES = "examples"

    def extract(self, mappings: MappingTable | None = None) -> Iterator[WordFormRecord]:
        mappings = mappings or {}
        source = self.config.get("url") or str(self.resolve_path(self.config["path"]))
        entries, index = load_dictionary(source)

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
        detail: dict[str, Any] | None = None,
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
            source_id=self.source_id,
            subsource=subsource,
            confidence=confidence,
            detail=detail or {},
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
                detail=_entry_detail(entry, from_lemma=lemma),
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
                detail=_entry_detail(entry),
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
                detail=_entry_detail(entry),
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
                    detail=_entry_detail(entry),
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
            sense_text = sense.get("text", "") or ""
            for example in sense.get("examples", []):
                av_text = example.get("av", "")
                if not av_text:
                    continue
                example_detail = {
                    "entry": context_lemma,
                    "av": av_text,
                    "ru": example.get("ru", "") or "",
                }
                if sense_text:
                    example_detail["sense"] = sense_text
                for token in _iter_example_tokens(av_text):
                    wordform = index._canonical_example_wordform(token)
                    if token in mappings:
                        rec = self._record(
                            wordform=wordform,
                            subsource=self.SUB_EXAMPLES,
                            mappings=mappings,
                            detail=example_detail,
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
                        wordform=wordform,
                        lemma=lemma,
                        relation=relation,
                        pos=token_pos if lemma else "",
                        subsource=self.SUB_EXAMPLES,
                        confidence=confidence if lemma or relation else "low",
                        mappings=mappings,
                        allow_self=True,
                        detail=example_detail,
                    )
                    if rec:
                        yield rec
