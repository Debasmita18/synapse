import secrets
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import hash_otp, verify_otp_hash
from app.models.otp import OTPRecord

logger = structlog.get_logger()
settings = get_settings()


def _generate_otp() -> str:
    return f"{secrets.randbelow(900000) + 100000:06d}"


async def create_otp(db: AsyncSession, email: str, user_id: str | None = None) -> str:
    otp = _generate_otp()
    record = OTPRecord(
        email=email,
        user_id=user_id,
        otp_hash=hash_otp(otp),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.otp_expire_seconds),
    )
    db.add(record)
    await db.commit()

    if settings.otp_mode == "dev":
        logger.info("DEV OTP", email=email, otp=otp)

    return otp


async def verify_and_consume(db: AsyncSession, email: str, otp: str) -> bool:
    now = datetime.now(UTC)
    result = await db.execute(
        select(OTPRecord)
        .where(
            OTPRecord.email == email,
            OTPRecord.is_used.is_(False),
            OTPRecord.expires_at > now,
        )
        .order_by(OTPRecord.created_at.desc())
        .limit(1)
    )
    record = result.scalar_one_or_none()

    if not record or not verify_otp_hash(otp, record.otp_hash):
        return False

    record.is_used = True
    await db.commit()
    return True
