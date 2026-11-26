from sqlalchemy import column
from sqlalchemy.dialects import postgresql

from src.modules.analytics.infrastructure.repositories.text_search import (
    TRANSLATE_FROM,
    TRANSLATE_TO,
    fold_vietnamese,
    folded_contains,
)


def _translate(text: str) -> str:
    """Python model of PostgreSQL translate(text, FROM, TO)."""
    mapping = {ch: (TRANSLATE_TO[i] if i < len(TRANSLATE_TO) else "") for i, ch in enumerate(TRANSLATE_FROM)}
    return "".join(mapping.get(ch, ch) for ch in text)


def test_fold_vietnamese_strips_diacritics_and_case():
    assert fold_vietnamese("Đặng Tiệp Chen") == "dang tiep chen"
    assert fold_vietnamese("Ưu Ơn Ữ Ợ") == "uu on u o"
    assert fold_vietnamese("100%_x") == "100%_x"


def test_sql_translation_matches_python_folding_for_composed_and_decomposed_text():
    import unicodedata

    for name in ("Đặng Tiệp Chen", "Thụy Hưng", "Xã Thụy Việt", "Cao Dượng Hạ"):
        assert _translate(name).lower() == fold_vietnamese(name)
        assert _translate(unicodedata.normalize("NFD", name)).lower() == fold_vietnamese(name)


def test_folded_contains_escapes_like_wildcards():
    sql = str(folded_contains(column("name"), "Tiệp 100%_").compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    assert "translate(name" in sql and "lower(" in sql
    assert "tiep 100/%%/_" in sql and "ESCAPE '/'" in sql
