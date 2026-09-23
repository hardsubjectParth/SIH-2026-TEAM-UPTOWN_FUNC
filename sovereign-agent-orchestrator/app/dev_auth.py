import os
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException
from pydantic import BaseModel, Field


class DevLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class DevLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict[str, str]


def _enabled() -> bool:
    return os.getenv("DEV_AUTH_ENABLED", "false").lower() in {"1", "true", "yes"}


def issue_dev_token(request: DevLoginRequest) -> DevLoginResponse:
    if not _enabled():
        raise HTTPException(404, "DEV_AUTH_DISABLED")

    secret = os.getenv("JWT_SECRET", "").strip()
    if len(secret) < 32:
        raise HTTPException(503, "DEV_AUTH_SECRET_NOT_CONFIGURED")

    accounts = {
        "admin": (os.getenv("DEV_ADMIN_PASSWORD", "admin-test-only"), "admin"),
        "higher": (os.getenv("DEV_HIGHER_PASSWORD", "higher-test-only"), "higher"),
        "lower": (os.getenv("DEV_LOWER_PASSWORD", "lower-test-only"), "lower"),
    }
    # The console signs in with an email address, so accept the local part as the
    # account name: admin@anything resolves to "admin". A bare "admin" still works,
    # which keeps the CLI and the existing scripts unchanged. This only decides
    # which account is being named -- the password check below is untouched, and
    # the domain carries no authority, so it is not a way in for anyone who does
    # not already hold the account's password.
    account = accounts.get(request.username.strip().lower().split('@', 1)[0])
    if not account or request.password != account[0]:
        raise HTTPException(401, "INVALID_CREDENTIALS")

    password, role = account
    del password
    expires_in = min(max(int(os.getenv("DEV_AUTH_TTL_SECONDS", "900")), 60), 3600)
    now = datetime.now(UTC)
    user = {"id": f"dev-{role}", "role": role, "tenant_id": "local-test"}
    token = jwt.encode(
        {"sub": user["id"], "role": role, "tenant_id": user["tenant_id"], "iat": now, "exp": now + timedelta(seconds=expires_in)},
        secret,
        algorithm="HS256",
    )
    return DevLoginResponse(access_token=token, expires_in=expires_in, user=user)
