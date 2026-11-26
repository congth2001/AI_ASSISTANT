import zipfile
import os

import pytest

from etl_business.shop_data_extractor.access import (
    _select_mdb_member,
    open_mdb_source,
    resolve_mdb_source,
)


def test_selects_configured_mdb_from_zip(tmp_path):
    archive_path = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("backup/iShopman.mdb", b"mdb")
        archive.writestr("readme.txt", b"ignored")

    with zipfile.ZipFile(archive_path) as archive:
        selected = _select_mdb_member(archive, "iShopman.mdb")

    assert selected.filename == "backup/iShopman.mdb"


def test_requires_member_name_when_zip_has_multiple_mdb_files(tmp_path):
    archive_path = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("first.mdb", b"first")
        archive.writestr("second.mdb", b"second")

    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="exactly one"):
            _select_mdb_member(archive, None)


def test_resolves_newest_zip_from_source_directory(tmp_path):
    older = tmp_path / "ishopman_backup_0.zip"
    newer = tmp_path / "ishopman_backup_1.zip"
    older.write_bytes(b"older")
    newer.write_bytes(b"newer")
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))
    os.utime(newer, ns=(2_000_000_000, 2_000_000_000))

    assert resolve_mdb_source(tmp_path) == newer


def test_resolve_source_directory_requires_a_zip(tmp_path):
    (tmp_path / "notes.txt").write_text("not a backup", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="No ZIP files"):
        resolve_mdb_source(tmp_path)


def test_open_zip_closes_connection_before_temporary_cleanup(tmp_path, monkeypatch):
    archive_path = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("iShopman.mdb", b"mdb")

    events = []

    class FakeConnection:
        def close(self):
            events.append("closed")

    def fake_connect(path, password, driver=None):
        assert path.endswith("iShopman.mdb")
        events.append("connected")
        return FakeConnection()

    monkeypatch.setattr(
        "etl_business.shop_data_extractor.access.connect_mdb", fake_connect
    )

    with open_mdb_source(str(archive_path), mdb_member="iShopman.mdb"):
        events.append("used")

    assert events == ["connected", "used", "closed"]


def test_driver_resolution_prefers_config_then_access_then_mdbtools():
    from etl_business.shop_data_extractor.access import (
        ACCESS_ODBC_DRIVER,
        MDBTOOLS_ODBC_DRIVER,
        resolve_odbc_driver,
    )

    assert resolve_odbc_driver("Custom", []) == "Custom"
    assert resolve_odbc_driver(None, ["SQL Server", ACCESS_ODBC_DRIVER, MDBTOOLS_ODBC_DRIVER]) == ACCESS_ODBC_DRIVER
    assert resolve_odbc_driver(None, ["PostgreSQL", MDBTOOLS_ODBC_DRIVER]) == MDBTOOLS_ODBC_DRIVER
    with pytest.raises(RuntimeError, match="odbc-mdbtools"):
        resolve_odbc_driver(None, ["PostgreSQL"])


def test_extract_sorts_in_pandas_because_mdbtools_cannot_parse_order_by(tmp_path, monkeypatch):
    import pandas as pd

    from etl_business.shop_data_extractor import extractor

    executed = []

    def fake_read_sql(sql, conn):
        executed.append(sql)
        # MDBTools returns storage order, not key order.
        return pd.DataFrame({"invoice_id": [3, 1, 2, 1], "id": [9, 8, 7, 6], "reason": ["NT"] * 4})

    monkeypatch.setattr(extractor, "list_tables", lambda conn: ["exim_export_invoice_details"])
    monkeypatch.setattr(extractor.pd, "read_sql", fake_read_sql)
    config = {"datasets": {"sale_items": {
        "table": "exim_export_invoice_details",
        "columns": {"source_line_id": "id", "invoice_id": "invoice_id"},
        "where": "[reason] = 'NT'",
        "sort_by": ["invoice_id", "id"],
    }}}

    datasets, manifest = extractor.extract_all(object(), config, str(tmp_path))

    assert manifest[0]["status"] == "SUCCESS"
    assert "ORDER BY" not in executed[0].upper()
    assert executed[0].endswith("WHERE [reason] = 'NT'")
    frame = datasets["sale_items"]
    assert list(frame.columns) == ["source_line_id", "invoice_id"]
    assert frame.to_dict("list") == {"source_line_id": [6, 8, 7, 9], "invoice_id": [1, 1, 2, 3]}


def test_legacy_sql_order_by_is_reported_as_a_failed_dataset(tmp_path, monkeypatch):
    import pandas as pd

    from etl_business.shop_data_extractor import extractor

    monkeypatch.setattr(extractor, "list_tables", lambda conn: ["exim_export_invoice"])
    monkeypatch.setattr(extractor.pd, "read_sql", lambda sql, conn: pd.DataFrame({"invoice_id": [1]}))
    config = {"datasets": {"sales": {
        "table": "exim_export_invoice", "columns": {"invoice_id": "invoice_id"},
        "order_by": "[invoice_id]",
    }}}

    _, manifest = extractor.extract_all(object(), config, str(tmp_path))

    assert manifest[0]["status"] == "FAILED"
    assert "sort_by" in manifest[0]["error"]
