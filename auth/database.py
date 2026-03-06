"""
auth/database.py
PostgreSQL kapcsolat és user CRUD műveletek.
"""
from __future__ import annotations
import os
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext

from auth.models import Base, User, AuditLog, user_collections

# ─── DB kapcsolat ────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://sbuser:sbpassword123@localhost:5432/second_brain"
)

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def init_db():
    """Táblák létrehozása és admin user inicializálása."""
    Base.metadata.create_all(bind=engine)

    # user_collections külön tábla
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_collections (
                user_id VARCHAR NOT NULL,
                collection VARCHAR NOT NULL,
                PRIMARY KEY (user_id, collection)
            )
        """))
        conn.commit()

    # Default admin user létrehozása ha nem létezik
    with SessionLocal() as db:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            create_user(
                db=db,
                username="admin",
                email="admin@secondbrain.local",
                password="admin123",
                role="admin",
                collections=["telenor", "yettel", "mvmi", "egis",
                             "extended_ecm", "oscript", "telenor_dk", "gmail"]
            )
            print("[Auth] Admin user létrehozva: admin / admin123")


def get_db():
    """FastAPI dependency injection."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── User CRUD ───────────────────────────────────────────────────────────────

def create_user(
    db: Session,
    username: str,
    email: str,
    password: str,
    role: str = "user",
    collections: list[str] = None,
) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        email=email,
        hashed_pw=pwd_context.hash(password),
        role=role,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()

    # Kollekció jogosultságok
    if collections:
        for col in collections:
            db.execute(
                user_collections.insert().values(user_id=user.id, collection=col)
            )
    db.commit()
    db.refresh(user)
    return user


def get_user(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def get_all_users(db: Session) -> list[User]:
    return db.query(User).all()


def update_user_collections(db: Session, user_id: str, collections: list[str]):
    db.execute(
        user_collections.delete().where(user_collections.c.user_id == user_id)
    )
    for col in collections:
        db.execute(
            user_collections.insert().values(user_id=user_id, collection=col)
        )
    db.commit()


def get_user_collections(db: Session, user_id: str) -> list[str]:
    result = db.execute(
        user_collections.select().where(user_collections.c.user_id == user_id)
    ).fetchall()
    return [row.collection for row in result]


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def log_action(db: Session, user_id: str, action: str, detail: str = ""):
    log = AuditLog(
        id=str(uuid.uuid4()),
        user_id=user_id,
        action=action,
        detail=detail,
        created_at=datetime.utcnow(),
    )
    db.add(log)
    db.commit()
