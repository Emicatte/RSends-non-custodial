"""Pydantic request/response schemas for /api/v1/auth/*."""

from typing import Optional
from pydantic import BaseModel, Field


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(min_length=20, max_length=4096)
    nonce: Optional[str] = Field(default=None, max_length=256)


class GitHubLoginRequest(BaseModel):
    access_token: str = Field(min_length=20, max_length=512)


class UserMeResponse(BaseModel):
    id: str
    email: str
    email_verified: bool = False
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    locale: Optional[str] = None


class AuthResponse(BaseModel):
    access_token: str
    expires_in: int
    user: UserMeResponse
