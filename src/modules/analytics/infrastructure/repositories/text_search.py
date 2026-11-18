"""Accent- and case-insensitive substring search for Vietnamese text.

Users type names without diacritics ("tiep chen" for "Tiệp Chen"), so filter
searches fold both sides to plain lowercase ASCII before comparing. PostgreSQL
``translate`` does the folding in SQL, which avoids requiring the ``unaccent``
extension (and the superuser migration it needs).
"""
from __future__ import annotations

import unicodedata

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

_COMBINING_MARKS = "".join(chr(code) for code in range(0x0300, 0x0370))


def _build_translation() -> tuple[str, str]:
    accented: list[str] = ["đ", "Đ"]
    plain: list[str] = ["d", "D"]
    # Latin-1 Supplement, Latin Extended-A/B and Latin Extended Additional cover
    # every precomposed Vietnamese letter (ắ, ợ, ữ...).
    ranges = (range(0x00C0, 0x0250), range(0x1E00, 0x1F00))
    for code in (code for block in ranges for code in block):
        char = chr(code)
        base = unicodedata.normalize("NFD", char)[0]
        if base != char and base.isascii() and base.isalpha():
            accented.append(char)
            plain.append(base)
    # Characters listed after the end of ``plain`` are deleted by translate():
    # this strips combining marks from text stored in decomposed (NFD) form.
    return "".join(accented) + _COMBINING_MARKS, "".join(plain)


TRANSLATE_FROM, TRANSLATE_TO = _build_translation()


def fold_vietnamese(text: str) -> str:
    """Return ``text`` lowercased with Vietnamese diacritics removed."""
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def folded_contains(column, search: str) -> ColumnElement[bool]:
    """``column`` contains ``search`` ignoring case and Vietnamese diacritics.

    ``autoescape`` keeps '%' and '_' typed by the user literal, not wildcards.
    """
    folded_column = func.lower(func.translate(column, TRANSLATE_FROM, TRANSLATE_TO))
    return folded_column.contains(fold_vietnamese(search), autoescape=True)
