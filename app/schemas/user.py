from datetime import datetime

from pydantic import BaseModel


class UserProfile(BaseModel):
    id: str
    email: str
    name: str
    plan: str
    is_pro: bool
    subscription_expires_at: datetime | None = None


class UpdateProfile(BaseModel):
    name: str | None = None
