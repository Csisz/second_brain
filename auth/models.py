"""
auth/models.py
SQLAlchemy modellek a felhasználókezeléshez.
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Table
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# Many-to-many: user <-> collections
user_collections = Table(
    "user_collections",
    Base.metadata,
    Column("user_id", String, ForeignKey("users.id"), primary_key=True),
    Column("collection", String, primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id           = Column(String, primary_key=True)  # UUID
    username     = Column(String, unique=True, nullable=False)
    email        = Column(String, unique=True, nullable=False)
    hashed_pw    = Column(String, nullable=False)
    role         = Column(String, default="user")  # admin / user / viewer
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    last_login   = Column(DateTime, nullable=True)

    collections  = relationship("User", secondary=user_collections,
                                primaryjoin="User.id == user_collections.c.user_id",
                                secondaryjoin="User.id == user_collections.c.user_id",
                                uselist=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id         = Column(String, primary_key=True)
    user_id    = Column(String, ForeignKey("users.id"))
    action     = Column(String)  # login, query, ingest, etc.
    detail     = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
