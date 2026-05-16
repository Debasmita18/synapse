from datetime import datetime

from pydantic import BaseModel


class SubscriptionInfo(BaseModel):
    plan: str
    status: str
    is_pro: bool
    expires_at: datetime | None = None
