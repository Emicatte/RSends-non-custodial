"""Pydantic request/response schemas for /api/v1/auth/*."""

from typing import Optional
from pydantic import BaseModel


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
