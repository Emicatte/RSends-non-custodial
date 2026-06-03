"""API Key Authentication Middleware — scope enforcement + environment tagging."""
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.security.api_keys import verify_api_key, is_exempt, is_get_public
from app.config import get_settings

ADMIN_PATHS = ("/api/v1/keys/generate", "/api/v1/keys/revoke")


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()

        if (
            os.getenv("RSEND_DEV_AUTH_BYPASS") == "1"
            and not os.getenv("ENVIRONMENT", "").lower().startswith("prod")
        ):
            request.state.client = {"client_id": "debug", "scope": "admin", "environment": "live"}
            return await call_next(request)

        if is_exempt(request.url.path):
            return await call_next(request)

        client = await verify_api_key(request)

        # GET requests (M8): deny-by-default. A valid API key always passes; a
        # GET without one passes only if the path is public / self-authenticating
        # (GET_PUBLIC_PREFIXES) — or if the kill-switch flag is off (legacy
        # "GET = public read" fallback).
        if request.method == "GET":
            if client:
                request.state.client = client
                return await call_next(request)
            if (not settings.api_get_deny_by_default) or is_get_public(request.url.path):
                return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={"error": "INVALID_API_KEY", "message": "Valid API key required"},
            )

        # Non-GET: auth is mandatory
        if client is None:
            return JSONResponse(
                status_code=401,
                content={"error": "INVALID_API_KEY", "message": "Valid API key required"},
            )

        scope = client.get("scope", "read")
        path = request.url.path

        # Read scope cannot make mutations
        if scope == "read":
            return JSONResponse(
                status_code=403,
                content={
                    "error": "INSUFFICIENT_SCOPE",
                    "message": f"This key has 'read' scope. {request.method} requests require 'write' or 'admin' scope.",
                },
            )

        # Admin-only paths
        if any(path.startswith(p) for p in ADMIN_PATHS):
            if scope != "admin":
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "ADMIN_REQUIRED",
                        "message": "This endpoint requires 'admin' scope.",
                    },
                )

        # Tag test keys
        if client.get("environment") == "test":
            request.state.testnet_only = True

        request.state.client = client
        return await call_next(request)
