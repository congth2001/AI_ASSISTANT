"""Static checks of the Alembic history; no database needed."""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[2]


def _script() -> ScriptDirectory:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    return ScriptDirectory.from_config(config)


def test_history_is_linear_with_a_single_head():
    script = _script()

    assert len(script.get_heads()) == 1
    # No merge revisions: every down_revision is a single id (or None for the root).
    assert all(
        revision.down_revision is None or isinstance(revision.down_revision, str)
        for revision in script.walk_revisions()
    )


def test_index_tuning_migration_has_a_real_downgrade():
    revision = _script().get_revision("e7b3c5a19f42")
    source = Path(revision.path).read_text(encoding="utf-8")
    downgrade = source[source.index("def downgrade"):]

    assert revision.down_revision == "d1e5b7a93c28"
    assert "pass" not in downgrade.split()
    for index in (
        "ix_sales_return_lines_return_id", "ix_sales_invoice_lines_invoice_id",
        "ix_sales_invoices_issued_at", "ix_debt_transactions_customer_id",
    ):
        assert f'"{index}"' in downgrade  # each dropped index is recreated on downgrade


def test_debt_audit_migration_drops_its_tables_on_downgrade():
    script = _script()
    revision = script.get_revision("8008434c9371")
    source = Path(revision.path).read_text(encoding="utf-8")
    downgrade = source[source.index("def downgrade"):]

    assert revision.down_revision == "e7b3c5a19f42"
    for table in ("etl_sync_runs", "customer_debt_transaction_changes", "customer_debt_revisions"):
        assert f'op.drop_table("{table}")' in downgrade


def test_sql_reader_role_migration_is_the_head_and_drops_the_role_on_downgrade():
    script = _script()
    revision = script.get_revision("a91c3e7d5b20")
    source = Path(revision.path).read_text(encoding="utf-8")
    downgrade = source[source.index("def downgrade"):]

    assert script.get_current_head() == "a91c3e7d5b20"
    assert revision.down_revision == "8008434c9371"
    assert "DROP OWNED BY" in downgrade and "DROP ROLE" in downgrade
