"""One metadata registry shared by all module ORM mappings."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
