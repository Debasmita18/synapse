from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database import get_db
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.user import UpdateProfile, UserProfile

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserProfile)
async def get_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    sub = result.scalar_one_or_none()

    return UserProfile(
        id=user.id,
        email=user.email,
        name=user.name or "",
        plan=sub.plan.value if sub else "free",
        is_pro=sub.is_pro if sub else False,
        subscription_expires_at=sub.expires_at if sub else None,
    )


@router.patch("/me", response_model=UserProfile)
async def update_profile(
    body: UpdateProfile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.name is not None:
        user.name = body.name.strip() or None
        await db.commit()
        await db.refresh(user)

    return await get_profile(user, db)
