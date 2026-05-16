import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    subscription: Mapped["Subscription"] = relationship(  # noqa: F821
        "Subscription", back_populates="user", uselist=False, lazy="select"
    )
    payments: Mapped[list["Payment"]] = relationship(  # noqa: F821
        "Payment", back_populates="user", lazy="select"
    )
    otp_records: Mapped[list["OTPRecord"]] = relationship(  # noqa: F821
        "OTPRecord", back_populates="user", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"
