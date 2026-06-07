from __future__ import annotations

"""Class/gender prefix alternation for Avar verb forms (б/в/р/й/я/е)."""

from typing import Iterator

# Surface prefix -> base form starting with б (or ба/бо/бу/бе).
_CLASS_PREFIX_RULES: tuple[tuple[str, str], ...] = (
    ("в", "б"),
    ("р", "б"),
    ("я", "ба"),
    ("йи", "бу"),
    ("й", "б"),
    ("е", "бе"),
)


def class_prefix_base_candidates(token: str) -> Iterator[str]:
    """Yield possible б-class base forms for a conjugated surface token."""
    if len(token) < 2:
        return

    for surface_prefix, base_prefix in _CLASS_PREFIX_RULES:
        if not token.startswith(surface_prefix):
            continue
        suffix = token[len(surface_prefix) :]
        if not suffix:
            continue
        candidate = base_prefix + suffix
        if candidate != token:
            yield candidate
