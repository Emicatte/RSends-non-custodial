"""Pydantic schemas for /api/v1/user/routes CRUD."""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class RouteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    route_config: Dict[str, Any]
    is_favorite: Optional[bool] = False


class RouteUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    route_config: Optional[Dict[str, Any]] = None
    is_favorite: Optional[bool] = None


class RouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    route_config: Dict[str, Any]
    is_favorite: bool
    created_at: datetime
    updated_at: datetime
    last_used_at: Optional[datetime]
    use_count: int
