from __future__ import annotations

"""Class/gender prefix alternation for Avar verb forms (б/в/р/й/я/е)."""

from typing import Iterator

# (surface_prefix, base_prefix, relation label)
CLASS_PREFIX_RULES: tuple[tuple[str, str, str], ...] = (
    ("в", "б", "мужской род"),
    ("р", "б", "множественное число"),
    ("я", "ба", "женский род"),
    ("йи", "бу", "женский род"),
    ("й", "б", "женский род"),
    ("е", "бе", "женский род"),
)


def class_prefix_matches(token: str) -> Iterator[tuple[str, str]]:
    """Yield (base_candidate, relation) for a conjugated surface token."""
    if len(token) < 2:
        return

    for surface_prefix, base_prefix, relation in CLASS_PREFIX_RULES:
        if not token.startswith(surface_prefix):
            continue
        suffix = token[len(surface_prefix) :]
        if not suffix:
            continue
        candidate = base_prefix + suffix
        if candidate != token:
            yield candidate, relation


def class_prefix_base_candidates(token: str) -> Iterator[str]:
    """Yield possible б-class base forms for a conjugated surface token."""
    for candidate, _relation in class_prefix_matches(token):
        yield candidate
