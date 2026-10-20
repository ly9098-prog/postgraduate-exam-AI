"""Shared declarative registry without runtime database configuration or engine creation."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """One metadata owner for models, Alembic and runtime initialization."""
