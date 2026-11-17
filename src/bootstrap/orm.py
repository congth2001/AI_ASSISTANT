"""Load all mappings for Alembic; modules import their own models directly."""
from src.common.infrastructure.database.base import Base
from src.modules.auth.infrastructure import models as auth_models
from src.modules.conversations.infrastructure import models as conversation_models
from src.modules.sales.infrastructure import models as sales_models

__all__ = ["Base"]
