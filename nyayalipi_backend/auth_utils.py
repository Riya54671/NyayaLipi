"""
Auth helpers
------------
- Password hashing/verification with bcrypt
- JWT creation/decoding with PyJWT
- FastAPI dependency `get_current_user` for protecting routes

Env vars (see .env):
    JWT_SECRET_KEY      long random string — REQUIRED in production
    JWT_ALGORITHM       default HS256
    JWT_EXPIRE_MINUTES  default 10080 (7 days)
"""

import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
import hashlib
from database import users_collection

load_dotenv(Path(__file__).resolve().parent / ".env")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))  # 7 days

_bearer_scheme = HTTPBearer(auto_error=False)

if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY is missing")

print(
    "[JWT CONFIG] fingerprint:",
    hashlib.sha256(JWT_SECRET_KEY.encode()).hexdigest()[:12]
)
print("[JWT CONFIG] algorithm:", JWT_ALGORITHM)

import base64
import json




# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def create_access_token(user_id: str, email: str) -> str:
    print(
        "[JWT CREATE] secret fingerprint:",
        hashlib.sha256(JWT_SECRET_KEY.encode()).hexdigest()[:12],
        flush=True,
    )
    print("[JWT CREATE] algorithm:", JWT_ALGORITHM, flush=True)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }

    token = jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

    print("[JWT CREATE] token generated:", token[:25] + "...", flush=True)

    return token


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )
        print("[JWT] Token decoded successfully")
        print("[JWT] Claims:", {
            "sub": payload.get("sub"),
            "email": payload.get("email"),
            "iat": payload.get("iat"),
            "exp": payload.get("exp"),
        })
        print("[JWT VERIFY] secret fingerprint:",
    hashlib.sha256(JWT_SECRET_KEY.encode()).hexdigest()[:12],
    flush=True,
    )
        print("[JWT VERIFY] algorithm:", JWT_ALGORITHM, flush=True)

        return payload

    except jwt.ExpiredSignatureError:
        print("[JWT] Token expired")
        raise HTTPException(status_code=401, detail="Token has expired")

    except jwt.InvalidTokenError as e:
        print(f"[JWT] Invalid token: {type(e).__name__}: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")



# ---------------------------------------------------------------------------
# FastAPI dependency — protects routes, returns the Mongo user document
# ---------------------------------------------------------------------------
def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    print(
    "[AUTH] Token received:",
    credentials.credentials[:20] + "..."
    if credentials and credentials.credentials
    else None
)
    if credentials is None:
        print("[AUTH] Request rejected: missing Bearer credentials.", flush=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except HTTPException as exc:
        print(f"[AUTH] Request rejected: {exc.detail}.", flush=True)
        raise
    user_id = payload.get("sub")

    try:
        user = users_collection.find_one({"_id": ObjectId(user_id)})
    except InvalidId:
        print("[AUTH] Request rejected: token subject is not a valid user id.", flush=True)
        user = None

    if user is None:
        print(
            "[AUTH] Request rejected: token subject was not found in the users collection.",
            flush=True,
        )
        raise HTTPException(status_code=401, detail="User not found")

    return user


def user_to_dict(user: dict) -> dict:
    return {
        "id": str(user["_id"]),
        "username": user["username"],
        "email": user["email"],
        "auth_provider": user.get("auth_provider", "password"),
    }