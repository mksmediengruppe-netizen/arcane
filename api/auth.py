"""
ARCANE Authentication
JWT-based auth with bcrypt password hashing.
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from shared.utils.logger import get_logger

logger = get_logger("api.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)

_env_secret = os.getenv("JWT_SECRET")
if not _env_secret:
    _env_secret = secrets.token_hex(32)
    logger.warning(
        "JWT_SECRET not set in environment! Generated random secret. "
        "Sessions will NOT survive server restart. "
        "Set JWT_SECRET in /root/arcane/.env for persistence."
    )
JWT_SECRET = _env_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 72


# ─── Schemas ─────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: str

    @property
    def login_id(self) -> str:
        return self.username or self.email or ""



class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserInfo(BaseModel):
    id: str
    username: str
    role: str
    model_strategy: str
    budget_limit: float
    total_spent: float


# ─── Helpers ─────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


def create_token(user_id: str, username: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": time.time(),
        "exp": time.time() + (JWT_EXPIRATION_HOURS * 3600),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Dependency: extract current user from JWT token."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_token(credentials.credentials)
    return {
        "id": payload.get("sub", ""),
        "username": payload.get("username", ""),
        "role": payload.get("role", "user"),
    }


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """Dependency: extract current user or return None."""
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    """Authenticate user and return JWT token."""
    from config.settings import get_config
    from shared.models.database import get_session_factory, User
    from sqlalchemy import select

    config = get_config()

    try:
        factory = get_session_factory(config.db.url)
        async with factory() as session:
            result = await session.execute(
                select(User).where((User.username == req.login_id) | (User.email == req.login_id))
            )
            user = result.scalar_one_or_none()
            logger.debug(f"Login attempt for: {req.login_id}")

            if user is None or not verify_password(req.password, user.password_hash):
                raise HTTPException(status_code=401, detail="Invalid credentials")

            if not user.is_active:
                raise HTTPException(status_code=403, detail="Account disabled")

            # Update last login
            user.last_login = datetime.utcnow()
            await session.commit()

            token = create_token(user.id, user.username, user.role)

            return TokenResponse(
                access_token=token,
                user={
                    "id": user.id,
                    "username": user.username,
                    "role": user.role,
                    "model_strategy": user.model_strategy,
                    "budget_limit": user.budget_limit,
                    "total_spent": user.total_spent,
                },
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest):
    """Register a new user."""
    from config.settings import get_config
    from shared.models.database import get_session_factory, User
    from sqlalchemy import select

    config = get_config()

    try:
        factory = get_session_factory(config.db.url)
        async with factory() as session:
            # Check if username or email already exists (v7: separate checks)
            existing_user = await session.execute(
                select(User).where(User.username == req.username)
            )
            if existing_user.scalar_one_or_none() is not None:
                raise HTTPException(status_code=409, detail="Username already taken")
            if req.email:
                existing_email = await session.execute(
                    select(User).where(User.email == req.email)
                )
                if existing_email.scalar_one_or_none() is not None:
                    raise HTTPException(status_code=409, detail="Email already registered")

            # Create user
            user = User(
                username=req.username,
                email=req.email,
                password_hash=hash_password(req.password),
                role="user",
                is_active=True,
                model_strategy="balance",
                budget_limit=5.0,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            token = create_token(user.id, user.username, user.role)

            return TokenResponse(
                access_token=token,
                user={
                    "id": user.id,
                    "username": user.username,
                    "role": user.role,
                    "model_strategy": user.model_strategy,
                    "budget_limit": user.budget_limit,
                    "total_spent": user.total_spent,
                },
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Register error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Get current user info."""
    from config.settings import get_config
    from shared.models.database import get_session_factory, User
    from sqlalchemy import select

    config = get_config()

    try:
        factory = get_session_factory(config.db.url)
        async with factory() as session:
            result = await session.execute(
                select(User).where(User.id == user["id"])
            )
            db_user = result.scalar_one_or_none()
            if db_user is None:
                raise HTTPException(status_code=404, detail="User not found")

            return {
                "id": db_user.id,
                "username": db_user.username,
                "email": db_user.email,
                "role": db_user.role,
                "model_strategy": db_user.model_strategy,
                "budget_limit": db_user.budget_limit,
                "total_spent": db_user.total_spent,
                "created_at": db_user.created_at.isoformat() if db_user.created_at else None,
                "last_login": db_user.last_login.isoformat() if db_user.last_login else None,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get me error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/change-password")
async def change_password(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Change user password."""
    body = await request.json()
    old_password = body.get("old_password", "")
    new_password = body.get("new_password", "")

    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    from config.settings import get_config
    from shared.models.database import get_session_factory, User
    from sqlalchemy import select

    config = get_config()
    factory = get_session_factory(config.db.url)

    async with factory() as session:
        result = await session.execute(
            select(User).where(User.id == user["id"])
        )
        db_user = result.scalar_one_or_none()
        if db_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        if not verify_password(old_password, db_user.password_hash):
            raise HTTPException(status_code=401, detail="Current password is incorrect")

        db_user.password_hash = hash_password(new_password)
        await session.commit()

    return {"status": "ok", "message": "Password changed"}
