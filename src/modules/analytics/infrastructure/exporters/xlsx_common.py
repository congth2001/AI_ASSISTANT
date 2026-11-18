"""Helpers shared by the OpenPyXL workbook adapters."""

import re

# A cell starting with one of these may be read as a formula/DDE by spreadsheet apps.
FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
_INVALID_SHEET_CHARS = re.compile(r"[\\/*?:\[\]\x00-\x1f]")
_RESERVED_SHEET_NAMES = {"history"}
SHEET_NAME_MAX_LENGTH = 31


def write_text(cell, value: str | None) -> None:
    """Store ``value`` as a literal string.

    The cell type is forced to string (never a formula) and ``quotePrefix`` keeps the
    text literal if a user edits the cell. The visible value stays unchanged, so
    legitimate text such as ``-5kg`` is not altered.
    """
    text = value or ""
    cell.value = text
    cell.data_type = "s"
    if text.startswith(FORMULA_TRIGGERS):
        cell.quotePrefix = True


def clean_sheet_name(raw_name: str, *, fallback: str, replacement: str = "-") -> str:
    """Remove forbidden characters and edge apostrophes/spaces (Excel rejects them)."""
    cleaned = _INVALID_SHEET_CHARS.sub(replacement, raw_name or "")
    return cleaned.strip(" '") or fallback


def truncate_sheet_name(name: str, max_length: int = SHEET_NAME_MAX_LENGTH) -> str:
    """Cut to Excel's limit without leaving an edge apostrophe or space; avoid reserved names."""
    truncated = name[:max_length].strip(" '") or "Sheet"
    if truncated.casefold() in _RESERVED_SHEET_NAMES:
        truncated = f"{truncated[:max_length - 1]}_"
    return truncated
