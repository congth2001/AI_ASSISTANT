"""Helpers shared by repositories that return plain dictionaries."""
from typing import Any, Dict


def model_to_dict(model: Any) -> Dict[str, Any]:
    """Copy loaded column attributes of an ORM instance (skips SQLAlchemy internals)."""
    return {key: value for key, value in model.__dict__.items() if not key.startswith("_")}
