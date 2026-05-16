from pydantic import BaseModel


class CreateOrderRequest(BaseModel):
    plan_id: str = "pro_monthly"


class VerifyPaymentRequest(BaseModel):
    order_id: str
    payment_id: str
    signature: str


class OrderResponse(BaseModel):
    order_id: str
    amount: int       # in paise
    currency: str
    key: str          # Razorpay publishable key for the checkout widget
    plan_id: str
    description: str
