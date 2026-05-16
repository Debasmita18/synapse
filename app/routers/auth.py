import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.database import get_db
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.auth import GoogleAuthRequest, OTPRequest, OTPVerify, RefreshRequest, TokenResponse
from app.services.email import send_otp_email
from app.services.otp import create_otp, verify_and_consume

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/request-otp", status_code=200)
@limiter.limit("5/minute")
async def request_otp(
    request: Request,
    body: OTPRequest,
    db: AsyncSession = Depends(get_db),
):
    email = body.email.lower().strip()

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        user = User(email=email, name=body.name)
        db.add(user)
        await db.flush()

        sub = Subscription(user_id=user.id)
        db.add(sub)
        await db.commit()
        await db.refresh(user)

    from app.config import get_settings as _gs
    _settings = _gs()

    otp = await create_otp(db, email, user.id)
    await send_otp_email(email, otp, user.name)

    response: dict = {"detail": "OTP sent — check your inbox"}
    # In dev mode expose the OTP in the response so the browser can autofill it
    if _settings.otp_mode == "dev":
        response["dev_otp"] = otp

    return response


@router.post("/verify-otp", response_model=TokenResponse)
@limiter.limit("10/minute")
async def verify_otp(
    request: Request,
    body: OTPVerify,
    db: AsyncSession = Depends(get_db),
):
    email = body.email.lower().strip()
    ok = await verify_and_consume(db, email, body.otp)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP",
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one()

    return TokenResponse(
        access_token=create_access_token({"sub": user.email}),
        refresh_token=create_refresh_token({"sub": user.email}),
        user_id=user.id,
        email=user.email,
        name=user.name or "",
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError
        email: str = payload["sub"]
    except (JWTError, ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return TokenResponse(
        access_token=create_access_token({"sub": user.email}),
        refresh_token=create_refresh_token({"sub": user.email}),
        user_id=user.id,
        email=user.email,
        name=user.name or "",
    )


# ── Google OAuth ──────────────────────────────────────────────────────────────

async def _verify_google_id_token(token: str, client_id: str) -> dict:
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": token},
        )
    if resp.status_code != 200:
        raise ValueError("Google rejected the token")
    data = resp.json()
    if data.get("aud") != client_id:
        raise ValueError("Token audience mismatch")
    if data.get("email_verified") != "true":
        raise ValueError("Google email not verified")
    return data


@router.post("/google", response_model=TokenResponse)
async def google_sign_in(
    body: GoogleAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.config import get_settings as _gs
    _settings = _gs()

    if not _settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured on this server",
        )

    try:
        gdata = await _verify_google_id_token(body.id_token, _settings.google_client_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    email: str = gdata["email"].lower()
    name: str = gdata.get("name", "")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        user = User(email=email, name=name)
        db.add(user)
        await db.flush()
        db.add(Subscription(user_id=user.id))
        await db.commit()
        await db.refresh(user)
    elif not user.name and name:
        user.name = name
        await db.commit()

    return TokenResponse(
        access_token=create_access_token({"sub": user.email}),
        refresh_token=create_refresh_token({"sub": user.email}),
        user_id=user.id,
        email=user.email,
        name=user.name or "",
    )
