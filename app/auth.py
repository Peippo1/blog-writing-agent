from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


async def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    if settings.dev_bypass_auth and not settings.is_production:
        return "local-developer"
    if not credentials or credentials.scheme.lower() != "bearer" or not settings.firebase_project_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is required")
    try:
        from firebase_admin import auth
        decoded = auth.verify_id_token(credentials.credentials, check_revoked=True)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token") from exc
    email = str(decoded.get("email", "")).lower()
    if not email or email not in settings.email_allowlist:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is not allowed")
    return str(decoded["uid"])


async def scheduler_authorized(request: Request, settings: Settings = Depends(get_settings)) -> None:
    supplied = request.headers.get("X-Scheduler-Secret")
    if not settings.scheduler_secret or not supplied or supplied != settings.scheduler_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid scheduler credential")
