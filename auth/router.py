"""
auth/router.py
FastAPI auth endpointok: login, me, users CRUD, kollekciók kezelése.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.database import (
    get_db, get_user, get_user_by_id, get_all_users,
    create_user, update_user_collections, get_user_collections,
    verify_password, log_action
)
from auth.jwt_handler import (
    create_access_token, get_current_user_id, require_admin, security
)

router = APIRouter(prefix="/auth", tags=["auth"])

ALL_COLLECTIONS = ["telenor", "yettel", "mvmi", "egis",
                   "extended_ecm", "oscript", "telenor_dk", "gmail"]


# ─── Pydantic modellek ───────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: str
    collections: list[str]


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"
    collections: list[str] = []


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: str
    last_login: Optional[str]
    collections: list[str]


class UpdateCollectionsRequest(BaseModel):
    collections: list[str]


# ─── Endpointok ──────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Bejelentkezés — JWT token visszaadása."""
    user = get_user(db, req.username)
    if not user or not verify_password(req.password, user.hashed_pw):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Hibás felhasználónév vagy jelszó"
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Fiók inaktív")

    # Last login frissítése
    user.last_login = datetime.utcnow()
    db.commit()

    collections = get_user_collections(db, user.id)
    token = create_access_token({
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "collections": collections,
    })

    log_action(db, user.id, "login", f"IP: unknown")

    return LoginResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        role=user.role,
        collections=collections,
    )


@router.get("/me", response_model=UserResponse)
def get_me(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Saját profil lekérése."""
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nem található")
    collections = get_user_collections(db, user.id)
    return _user_to_response(user, collections)


@router.get("/users", response_model=list[UserResponse])
def list_users(
    _: str = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Összes felhasználó listája (csak admin)."""
    users = get_all_users(db)
    result = []
    for u in users:
        cols = get_user_collections(db, u.id)
        result.append(_user_to_response(u, cols))
    return result


@router.post("/users", response_model=UserResponse)
def create_new_user(
    req: UserCreate,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Új felhasználó létrehozása (csak admin)."""
    existing = get_user(db, req.username)
    if existing:
        raise HTTPException(status_code=400, detail="Felhasználónév már foglalt")

    # Validálás: csak létező kollekciók
    invalid = [c for c in req.collections if c not in ALL_COLLECTIONS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Ismeretlen kollekciók: {invalid}")

    user = create_user(db, req.username, req.email, req.password, req.role, req.collections)
    return _user_to_response(user, req.collections)


@router.put("/users/{user_id}/collections")
def update_collections(
    user_id: str,
    req: UpdateCollectionsRequest,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Felhasználó kollekció jogosultságainak módosítása (csak admin)."""
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nem található")

    invalid = [c for c in req.collections if c not in ALL_COLLECTIONS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Ismeretlen kollekciók: {invalid}")

    update_user_collections(db, user_id, req.collections)
    return {"status": "ok", "user_id": user_id, "collections": req.collections}


@router.delete("/users/{user_id}")
def deactivate_user(
    user_id: str,
    _: str = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Felhasználó deaktiválása (csak admin)."""
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User nem található")
    user.is_active = False
    db.commit()
    return {"status": "deactivated", "user_id": user_id}


@router.get("/collections")
def list_collections():
    """Elérhető kollekciók listája."""
    return {"collections": ALL_COLLECTIONS}


# ─── Helper ──────────────────────────────────────────────────────────────────

def _user_to_response(user, collections: list[str]) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else "",
        last_login=user.last_login.isoformat() if user.last_login else None,
        collections=collections,
    )
