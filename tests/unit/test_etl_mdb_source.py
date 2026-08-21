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

    def fake_connect(path, password):
        assert path.endswith("iShopman.mdb")
        events.append("connected")
        return FakeConnection()

    monkeypatch.setattr(
        "etl_business.shop_data_extractor.access.connect_mdb", fake_connect
    )

    with open_mdb_source(str(archive_path), mdb_member="iShopman.mdb"):
        events.append("used")

    assert events == ["connected", "used", "closed"]
