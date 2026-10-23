"""Pydantic schemas for signup / login / Google auth."""

from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    # ID token obtained on the frontend via Google Sign-In
    # (google_sign_in on Flutter, Google Identity Services on web).
    id_token: str


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    auth_provider: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class ProfileUpdateRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    new_password: Optional[str] = Field(None, min_length=8)