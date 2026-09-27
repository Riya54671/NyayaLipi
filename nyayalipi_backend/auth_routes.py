"""
Auth routes
-----------
POST /auth/signup   — email + password signup
POST /auth/login    — email + password login
POST /auth/google    — sign up OR log in with a Google ID token
                        (same endpoint handles both: creates the user on
                        first sign-in, logs them in on every sign-in after)
GET  /auth/me        — current user, requires Bearer token

Env vars (see .env):
    GOOGLE_CLIENT_ID   OAuth client ID from Google Cloud Console
                       (the "Web client" / "Web application" client ID —
                       used to verify tokens from ALL platforms: Android,
                       iOS and web, since google_sign_in on Flutter is
                       configured to request an ID token audienced to it)
"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from dotenv import load_dotenv

from database import users_collection
from auth_models import (
    SignupRequest,
    LoginRequest,
    GoogleAuthRequest,
    TokenResponse,
    UserOut,
)
from auth_utils import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    user_to_dict,
)

load_dotenv()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Email + password signup
# ---------------------------------------------------------------------------
@router.post("/signup", response_model=TokenResponse)
def signup(body: SignupRequest):
    if users_collection.find_one({"email": body.email}):
        raise HTTPException(status_code=409, detail="Email already registered")
    if users_collection.find_one({"username": body.username}):
        raise HTTPException(status_code=409, detail="Username already taken")

    user_doc = {
        "username": body.username,
        "email": body.email,
        "password_hash": hash_password(body.password),
        "auth_provider": "password",
        "google_id": None,
        "created_at": datetime.now(timezone.utc),
    }
    result = users_collection.insert_one(user_doc)
    user_doc["_id"] = result.inserted_id

    token = create_access_token(str(user_doc["_id"]), user_doc["email"])
    return TokenResponse(access_token=token, user=UserOut(**user_to_dict(user_doc)))


# ---------------------------------------------------------------------------
# Email + password login
# ---------------------------------------------------------------------------
@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    user = users_collection.find_one({"email": body.email})
    if not user or user.get("auth_provider") != "password":
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("password_hash") or not verify_password(
        body.password, user["password_hash"]
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(str(user["_id"]), user["email"])
    return TokenResponse(access_token=token, user=UserOut(**user_to_dict(user)))


# ---------------------------------------------------------------------------
# Google sign-in / sign-up (one endpoint, handles both)
# ---------------------------------------------------------------------------
@router.post("/google", response_model=TokenResponse)
def google_auth(body: GoogleAuthRequest):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="Server is missing GOOGLE_CLIENT_ID configuration",
        )

    try:
        idinfo = google_id_token.verify_oauth2_token(
            body.id_token, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    google_id = idinfo["sub"]
    email = idinfo.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    user = users_collection.find_one({"google_id": google_id})

    if user is None:
        # If someone already signed up with this email via password, link
        # the accounts instead of creating a duplicate user.
        user = users_collection.find_one({"email": email})

        if user is not None:
            users_collection.update_one(
                {"_id": user["_id"]},
                {"$set": {"google_id": google_id, "auth_provider": "google"}},
            )
            user = users_collection.find_one({"_id": user["_id"]})
        else:
            base_username = (idinfo.get("name") or email.split("@")[0]).replace(
                " ", "_"
            )
            username = base_username
            suffix = 1
            while users_collection.find_one({"username": username}):
                suffix += 1
                username = f"{base_username}{suffix}"

            user_doc = {
                "username": username,
                "email": email,
                "password_hash": None,
                "auth_provider": "google",
                "google_id": google_id,
                "created_at": datetime.now(timezone.utc),
            }
            result = users_collection.insert_one(user_doc)
            user_doc["_id"] = result.inserted_id
            user = user_doc

    token = create_access_token(str(user["_id"]), user["email"])
    return TokenResponse(access_token=token, user=UserOut(**user_to_dict(user)))


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------
@router.get("/me", response_model=UserOut)
def me(current_user: dict = Depends(get_current_user)):
    return UserOut(**user_to_dict(current_user))