from __future__ import annotations

from pathlib import Path
import yaml

from config.config_manager import ConfigManager

ETL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ETL_ROOT.parent


def _resolve_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load_settings(config_path: str | Path | None = None) -> dict:
    local_config = PROJECT_ROOT / "config" / "local.yml"
    etl_settings = ConfigManager(str(local_config)).get_settings().etl
    configured_path = config_path or etl_settings.extract_config_path
    cfg_path = (
        _resolve_path(str(configured_path), PROJECT_ROOT)
        if configured_path
        else ETL_ROOT / "config" / "extract.yml"
    )
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path}")

    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    cfg["_runtime"] = {
        "source_path": (
            str(_resolve_path(etl_settings.source_path, PROJECT_ROOT))
            if etl_settings.source_path
            else ""
        ),
        "mdb_member": etl_settings.mdb_member,
        "mdb_password": etl_settings.mdb_password,
        "output_dir": str(_resolve_path(etl_settings.output_dir, PROJECT_ROOT)),
        "snapshot_dir": str(
            _resolve_path(etl_settings.snapshot_dir, PROJECT_ROOT)
        ),
        "product_aliases_path": str(
            _resolve_path(etl_settings.product_aliases_path, PROJECT_ROOT)
        ),
        "customer_ward_aliases_path": str(
            _resolve_path(etl_settings.customer_ward_aliases_path, PROJECT_ROOT)
        ),
        "lock_path": str(_resolve_path(etl_settings.lock_path, PROJECT_ROOT)),
        "opening_balance_date": etl_settings.opening_balance_date,
        "project_config_path": str(local_config),
        "config_path": str(cfg_path),
    }
    return cfg
