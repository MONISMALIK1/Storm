"""Authentication + authorization — JWT, bcrypt, RBAC dependencies."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import AuditLog, User, get_session, session_scope

ROLES = ("super_admin", "admin", "analyst", "viewer")
ROLE_RANK = {r: i for i, r in enumerate(reversed(ROLES))}

SECRET_KEY = os.environ.get("INTEL_JWT_SECRET") or secrets.token_urlsafe(64)
ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MIN = int(os.environ.get("INTEL_TOKEN_TTL_MIN", "240"))

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_ctx.verify(plain, hashed)
    except Exception:
        return False


def create_access_token(user: User) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_TTL_MIN)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def authenticate(session: Session, email: str, password: str) -> Optional[User]:
    user = session.scalar(select(User).where(User.email == email.lower()))
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.utcnow()
    return user


def create_user(email: str, password: str, role: str = "viewer") -> User:
    if role not in ROLES:
        raise ValueError(f"invalid role; must be one of {ROLES}")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    with session_scope() as session:
        existing = session.scalar(select(User).where(User.email == email.lower()))
        if existing:
            raise ValueError(f"user already exists: {email}")
        u = User(
            email=email.lower(),
            password_hash=hash_password(password),
            role=role,
        )
        session.add(u)
        session.flush()
        session.refresh(u)
        # Detach so caller can read fields outside session
        session.expunge(u)
        return u


def log_audit(
    session: Session,
    user_id: Optional[int],
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    ip: Optional[str] = None,
    metadata: Optional[str] = None,
) -> None:
    session.add(AuditLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip=ip,
        metadata_json=metadata,
    ))


def get_current_user(
    token: str = Depends(oauth2),
    session: Session = Depends(get_session),
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub", 0))
    except (JWTError, ValueError):
        raise cred_exc
    user = session.get(User, user_id)
    if not user or not user.is_active:
        raise cred_exc
    return user


def require_role(min_role: str):
    if min_role not in ROLES:
        raise ValueError(f"invalid role: {min_role}")
    required_rank = ROLE_RANK[min_role]

    def _dep(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK.get(user.role, -1) < required_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires role >= {min_role}",
            )
        return user

    return _dep


def client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
