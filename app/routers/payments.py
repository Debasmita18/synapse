from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.deps import get_current_user
from app.database import get_db
from app.models.payment import Payment, PaymentStatus
from app.models.subscription import PlanType, Subscription, SubscriptionStatus
from app.models.user import User
from app.schemas.payment import CreateOrderRequest, OrderResponse, VerifyPaymentRequest
from app.services.razorpay_service import (
    PLANS,
    create_order,
    get_plan,
    verify_payment_signature,
    verify_webhook_signature,
)

logger = structlog.get_logger()
settings = get_settings()
router = APIRouter(prefix="/api/payments", tags=["payments"])


# ── Create Order ──────────────────────────────────────────────────────────────

@router.post("/create-order", response_model=OrderResponse)
async def create_payment_order(
    body: CreateOrderRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        plan_meta = get_plan(body.plan_id)
        order = create_order(body.plan_id, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error("Razorpay order creation failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment gateway unavailable — try again",
        )

    payment = Payment(
        user_id=user.id,
        razorpay_order_id=order["id"],
        amount=order["amount"],
        currency=order["currency"],
        plan_id=body.plan_id,
    )
    db.add(payment)
    await db.commit()

    return OrderResponse(
        order_id=order["id"],
        amount=order["amount"],
        currency=order["currency"],
        key=settings.razorpay_key_id,
        plan_id=body.plan_id,
        description=plan_meta["description"],
    )


# ── Verify Payment (client-side callback) ─────────────────────────────────────

@router.post("/verify")
async def verify_payment(
    body: VerifyPaymentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_payment_signature(body.order_id, body.payment_id, body.signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment signature mismatch — possible tampering detected",
        )

    result = await db.execute(
        select(Payment).where(Payment.razorpay_order_id == body.order_id)
    )
    payment = result.scalar_one_or_none()
    if not payment or payment.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if payment.status == PaymentStatus.CAPTURED:
        return {"detail": "Already processed", "plan": "pro"}

    payment.razorpay_payment_id = body.payment_id
    payment.razorpay_signature = body.signature
    payment.status = PaymentStatus.CAPTURED

    await _activate_pro(db, user.id, payment.plan_id)
    await db.commit()

    logger.info("Payment captured", user=user.email, order=body.order_id)
    return {"detail": "Payment verified — SYNAPSE+ activated!", "plan": "pro"}


# ── Razorpay Webhook ───────────────────────────────────────────────────────────

@router.post("/webhook", include_in_schema=False)
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not verify_webhook_signature(raw_body, signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad signature")

    payload = await request.json()
    event: str = payload.get("event", "")

    if event == "payment.captured":
        entity = payload["payload"]["payment"]["entity"]
        order_id = entity.get("order_id")
        payment_id = entity.get("id")

        result = await db.execute(
            select(Payment).where(Payment.razorpay_order_id == order_id)
        )
        payment = result.scalar_one_or_none()

        if payment and payment.status == PaymentStatus.PENDING:
            payment.razorpay_payment_id = payment_id
            payment.status = PaymentStatus.CAPTURED
            await _activate_pro(db, payment.user_id, payment.plan_id)
            await db.commit()
            logger.info("Webhook: payment captured", order=order_id)

    elif event == "payment.failed":
        order_id = payload["payload"]["payment"]["entity"].get("order_id")
        result = await db.execute(
            select(Payment).where(Payment.razorpay_order_id == order_id)
        )
        payment = result.scalar_one_or_none()
        if payment:
            payment.status = PaymentStatus.FAILED
            await db.commit()

    return {"status": "ok"}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _activate_pro(db: AsyncSession, user_id: str, plan_id: str) -> None:
    duration_days = PLANS.get(plan_id, {}).get("duration_days", 30)

    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    sub = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if sub:
        sub.plan = PlanType.PRO
        sub.status = SubscriptionStatus.ACTIVE
        sub.started_at = now
        sub.expires_at = now + timedelta(days=duration_days)
    else:
        db.add(
            Subscription(
                user_id=user_id,
                plan=PlanType.PRO,
                status=SubscriptionStatus.ACTIVE,
                expires_at=now + timedelta(days=duration_days),
            )
        )
