from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

SYSTEM_PREFIXES = ("MSys", "~")


def resolve_mdb_source(source_path: str | Path) -> Path:
    """Resolve a direct MDB/ZIP path or the newest ZIP inside a directory."""
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"ETL source path not found: {source}")
    if source.is_file():
        return source

    zip_files = [path for path in source.glob("*.zip") if path.is_file()]
    if not zip_files:
        raise FileNotFoundError(f"No ZIP files found in ETL source directory: {source}")
    return max(zip_files, key=lambda path: (path.stat().st_mtime_ns, path.name))

def quote_ident(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"

def connect_mdb(path: str, password: str = ""):
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError(
            "pyodbc is not installed. Run scripts\\setup.bat or pip install -r requirements.txt"
        ) from exc

    # Access creates a sibling .ldb lock file. ODBC pooling can keep the
    # physical connection alive after close(), which prevents cleanup of the
    # temporary extraction directory on Windows.
    pyodbc.pooling = False

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"MDB file not found: {p}")

    parts = [
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)}",
        f"DBQ={p}",
        "READONLY=1",
    ]
    if password:
        parts.append(f"PWD={password}")
    conn_str = ";".join(parts) + ";"
    return pyodbc.connect(conn_str, autocommit=True)


def _select_mdb_member(
    archive: zipfile.ZipFile, configured_member: str | None
) -> zipfile.ZipInfo:
    candidates = [
        entry
        for entry in archive.infolist()
        if not entry.is_dir() and Path(entry.filename).suffix.lower() == ".mdb"
    ]
    if configured_member:
        expected = configured_member.replace("\\", "/").casefold()
        matches = [
            entry
            for entry in candidates
            if entry.filename.replace("\\", "/").casefold() == expected
            or Path(entry.filename).name.casefold() == Path(expected).name.casefold()
        ]
        if len(matches) == 1:
            return matches[0]
        raise FileNotFoundError(
            f"MDB member {configured_member!r} was not found uniquely in the ZIP"
        )
    if len(candidates) != 1:
        raise ValueError(
            "ZIP must contain exactly one .mdb file when etl.mdb_member is omitted"
        )
    return candidates[0]


@contextmanager
def open_mdb_source(
    source_path: str, password: str = "", mdb_member: str | None = None
):
    """Open an MDB directly or materialize one safely from a ZIP archive."""
    source = resolve_mdb_source(source_path)

    if source.suffix.lower() != ".zip":
        connection = connect_mdb(str(source), password)
        try:
            yield connection
        finally:
            connection.close()
        return

    with zipfile.ZipFile(source) as archive:
        member = _select_mdb_member(archive, mdb_member)
        with tempfile.TemporaryDirectory(prefix="business-etl-") as temp_dir:
            extracted_path = Path(temp_dir) / Path(member.filename).name
            with archive.open(member) as source_file, extracted_path.open("wb") as target:
                shutil.copyfileobj(source_file, target)
            connection = connect_mdb(str(extracted_path), password)
            try:
                yield connection
            finally:
                connection.close()

def list_tables(conn) -> list[str]:
    names = []
    for row in conn.cursor().tables(tableType="TABLE"):
        name = row.table_name
        if not name.startswith(SYSTEM_PREFIXES):
            names.append(name)
    return sorted(set(names), key=str.lower)

def get_columns(conn, table: str) -> list[dict]:
    result = []
    for row in conn.cursor().columns(table=table):
        result.append({
            "name": row.column_name,
            "type_name": getattr(row, "type_name", None),
            "data_type": getattr(row, "data_type", None),
            "column_size": getattr(row, "column_size", None),
            "nullable": getattr(row, "nullable", None),
            "ordinal": getattr(row, "ordinal_position", None),
        })
    return sorted(result, key=lambda x: x["ordinal"] or 0)

def row_count(conn, table: str) -> int | None:
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {quote_ident(table)}")
        return int(cur.fetchone()[0])
    except Exception:
        return None

def sample_rows(conn, table: str, limit: int = 5):
    cur = conn.cursor()
    cur.execute(f"SELECT TOP {int(limit)} * FROM {quote_ident(table)}")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    return rows

def normalize_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())

def detect_table(tables: list[str], candidates: Iterable[str]) -> str | None:
    exact = {normalize_name(t): t for t in tables}
    for cand in candidates:
        n = normalize_name(cand)
        if n in exact:
            return exact[n]

    # Fallback substring, ưu tiên match ngắn nhất.
    matches = []
    for table in tables:
        nt = normalize_name(table)
        for cand in candidates:
            nc = normalize_name(cand)
            if nc and (nc in nt or nt in nc):
                matches.append((abs(len(nt) - len(nc)), len(table), table))
    return sorted(matches)[0][2] if matches else None
