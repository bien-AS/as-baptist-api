"""Declarative metadata shared by all database models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root metadata registry for Alembic and model imports."""
