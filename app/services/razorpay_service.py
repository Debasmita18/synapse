import razorpay
import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# Lazily initialised so missing keys don't crash import
_client: razorpay.Client | None = None


def get_client() -> razorpay.Client:
    global _client
    if _client is None:
        _client = razorpay.Client(
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
        )
    return _client


# ── Catalogue ─────────────────────────────────────────────────────────────────
# Amount is always in the smallest currency unit (paise for INR).
PLANS: dict[str, dict] = {
    "pro_monthly": {
        "amount": 11900,          # ₹119 / month
        "currency": "INR",
        "description": "SYNAPSE+ — Monthly Subscription",
        "duration_days": 30,
    },
    "pro_quarterly": {
        "amount": 30000,          # ₹300 / 3 months  (save 16%)
        "currency": "INR",
        "description": "SYNAPSE+ — Quarterly Subscription",
        "duration_days": 90,
    },
    "pro_annual": {
        "amount": 110000,         # ₹1,100 / year  (save 23%)
        "currency": "INR",
        "description": "SYNAPSE+ — Annual Subscription",
        "duration_days": 365,
    },
}


def get_plan(plan_id: str) -> dict:
    plan = PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id!r}")
    return plan


# ── Orders ────────────────────────────────────────────────────────────────────

def create_order(plan_id: str, user_id: str) -> dict:
    plan = get_plan(plan_id)
    client = get_client()
    order = client.order.create(
        {
            "amount": plan["amount"],
            "currency": plan["currency"],
            "notes": {"user_id": user_id, "plan_id": plan_id},
        }
    )
    logger.info(
        "Razorpay order created",
        order_id=order["id"],
        amount=plan["amount"],
        user=user_id,
    )
    return order


# ── Signature verification ────────────────────────────────────────────────────

def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    try:
        get_client().utility.verify_payment_signature(
            {
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            }
        )
        return True
    except Exception:
        return False


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    try:
        get_client().utility.verify_webhook_signature(
            raw_body.decode(), signature, settings.razorpay_webhook_secret
        )
        return True
    except Exception:
        return False
